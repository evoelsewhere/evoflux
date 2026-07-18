"""Code overview injection hook — auto-orients the agent on first turn.

Injects a compact code-graph overview as a synthetic ``code_overview`` tool
call/result pair after the first HumanMessage.  This gives the agent an
immediate map of the indexed workspace (languages, symbol counts, densest
files) without wasting a round-trip.

The injection is skipped when:
- The workspace has no code index.
- The agent has already called any code_* tool in its history (session resume).
- The overview was already injected in a prior activation.
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

_CODE_TOOL_NAMES = frozenset({"code_search", "code_graph", "code_overview"})


class CodeOverviewHook(BaseAgentHook):
    """Injects a pre-fetched code overview as synthetic tool messages.

    Attached by the loader for agents that have ``code_overview`` in their
    tool set.  The overview is fetched lazily on first ``before_agent`` call
    and cached for the duration of the session.
    """

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        # Skip if any code_* tool call already exists in history (resume or
        # prior turn already explored the graph).
        if self._code_tools_in_history(state):
            return

        # Find insertion point — after first HumanMessage.
        insert_idx = self._find_insertion_index(state)
        if insert_idx is None:
            return

        # Fetch the overview (cheap DB call, ~200 tokens output).
        overview_text = await self._fetch_overview()
        if not overview_text:
            return

        # Build synthetic tool_call + tool_result pair.
        call_id = f"overview_{uuid.uuid4().hex[:12]}"
        assistant_msg = AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=FunctionCall(
                        name="code_overview",
                        arguments=json.dumps({}),
                    ),
                )
            ],
        )
        tool_msg = ToolMessage(
            tool_call_id=call_id,
            name="code_overview",
            content=overview_text,
        )

        state.messages[insert_idx:insert_idx] = [assistant_msg, tool_msg]

        logger.info(
            "code_overview_injected agent={} at_index={}",
            ctx.agent_name,
            insert_idx,
        )

    @staticmethod
    def _code_tools_in_history(state: "AgentState") -> bool:
        """Return True if any code_* tool call is already in messages."""
        for msg in state.messages:
            if not isinstance(msg, AssistantMessage):
                continue
            for tc in msg.tool_calls or []:
                if tc.function.name in _CODE_TOOL_NAMES:
                    return True
        return False

    @staticmethod
    def _find_insertion_index(state: "AgentState") -> int | None:
        """Return the index AFTER the first HumanMessage, or None."""
        for i, msg in enumerate(state.messages):
            if isinstance(msg, HumanMessage):
                return i + 1
        return None

    @staticmethod
    async def _fetch_overview() -> str | None:
        """Run code_overview logic and return the text, or None."""
        from app.agent.sandbox import get_sandbox
        from app.core.db import async_session_factory
        from app.services import code_graph_service as svc

        try:
            sandbox = get_sandbox()
        except Exception:
            return None

        async with async_session_factory() as db:
            workspace_id = await svc.resolve_workspace_id(
                db, path=str(sandbox.workspace_root)
            )
            if workspace_id is None:
                return None
            ov = await svc.get_overview(db, workspace_id=workspace_id)

        if ov.file_count == 0:
            return None

        kinds = ", ".join(f"{k}={v}" for k, v in sorted(ov.kind_counts.items()))
        top = "\n".join(f"  {path} ({count} symbols)" for path, count in ov.top_files)
        return (
            f"Code index: {ov.node_count} nodes, {ov.edge_count} edges, "
            f"{ov.file_count} files.\n"
            f"Languages: {', '.join(ov.languages) or 'none'}\n"
            f"Symbol kinds: {kinds}\n"
            f"Densest files:\n{top}"
        )
