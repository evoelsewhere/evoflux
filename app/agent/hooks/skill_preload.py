"""Skill preload hook — injects assigned skill bodies as synthetic tool messages.

Instead of bloating the system prompt with full skill instructions (which are
re-sent every turn), this hook injects them as synthetic
``skill`` tool_call / tool_result pairs in the message history.  This gives
the LLM immediate access to skill instructions on the first turn while
allowing the summarization hook to compact them on subsequent turns.

The synthetic messages are only injected once — on the first run where no
prior skill tool calls are visible in the message history.  On session
resume, the persisted synthetic messages are loaded from the DB naturally.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


class SkillPreloadHook(BaseAgentHook):
    """Injects pre-loaded skill bodies as synthetic tool messages.

    On the first activation (no prior ``skill`` tool calls in history),
    inserts ``[AssistantMessage(tool_calls), ToolMessage, ToolMessage, ...]``
    after the first HumanMessage.  On subsequent activations the messages
    are already in history (persisted by the checkpointer), so this is a
    no-op.

    Parameters
    ----------
    preloaded_skills:
        Mapping of ``{skill_name: rendered_body}``.
    """

    def __init__(self, preloaded_skills: dict[str, str]) -> None:
        self._skills = preloaded_skills

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        if not self._skills:
            return

        # Check if skills are already in message history (session resume
        # or prior turn already injected them).
        if self._skills_already_in_history(state):
            return

        # Find insertion point — after the first HumanMessage so all
        # providers (Anthropic, Gemini) see a valid user→assistant→tool
        # sequence.
        insert_idx = self._find_insertion_index(state)
        if insert_idx is None:
            # No HumanMessage yet — cannot inject safely.  The skill tool
            # description still lists these skills so the agent can load
            # them on-demand.
            return

        # Build synthetic tool_call + tool_result pairs
        tool_calls: list[ToolCall] = []
        tool_messages: list[ToolMessage] = []

        for skill_name, body in self._skills.items():
            call_id = f"preload_{uuid.uuid4().hex[:12]}"
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    function=FunctionCall(
                        name="skill",
                        arguments=json.dumps({"skill_name": skill_name}),
                    ),
                )
            )
            tool_messages.append(
                ToolMessage(
                    tool_call_id=call_id,
                    name="skill",
                    content=body,
                )
            )

        assistant_msg = AssistantMessage(
            content=None,
            tool_calls=tool_calls,
        )

        # Insert: [HumanMessage, ...existing...] → [HumanMessage, Assistant(tool_calls), Tool, Tool, ...existing...]
        synthetic = [assistant_msg, *tool_messages]
        state.messages[insert_idx:insert_idx] = synthetic

        # Pre-seed loaded_skills metadata so the skill tool's reuse check
        # works immediately without scanning message history.
        loaded = state.metadata.setdefault("loaded_skills", {})
        for skill_name, body in self._skills.items():
            loaded[skill_name] = body

        logger.info(
            "skill_preload_injected agent={} skills={} at_index={}",
            ctx.agent_name,
            list(self._skills.keys()),
            insert_idx,
        )

    def _skills_already_in_history(self, state: "AgentState") -> bool:
        """Return True if any skill tool_call is already in messages."""
        for msg in state.messages:
            if not isinstance(msg, AssistantMessage):
                continue
            for tc in msg.tool_calls or []:
                if tc.function.name == "skill":
                    return True
        return False

    def _find_insertion_index(self, state: "AgentState") -> int | None:
        """Return the index AFTER the first HumanMessage, or None."""
        for i, msg in enumerate(state.messages):
            if isinstance(msg, HumanMessage):
                return i + 1
        return None
