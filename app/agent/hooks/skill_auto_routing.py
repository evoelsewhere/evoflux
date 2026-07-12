"""Automatic skill routing hook — matches user intent to skills and loads them.

On the first human turn (or whenever new skills become relevant), this hook
scores every *unloaded* skill against the latest user message using trigger
keywords extracted from each skill's ``description`` field.  Skills whose
relevance score exceeds a configurable threshold are automatically loaded as
synthetic ``skill`` tool_call / tool_result message pairs — the same
injection pattern used by :class:`~app.agent.hooks.skill_preload.SkillPreloadHook`.

The hook is deliberately conservative:

* Only skills with a score above ``threshold`` (default 0.3) are considered.
* At most ``top_k`` (default 3) skills are loaded per turn.
* Skills already visible in message history or in
  ``state.metadata["loaded_skills"]`` are never re-loaded.

The hook operates on **every** ``before_agent`` call but is effectively a
no-op once all high-confidence skills are already in the conversation.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
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


class SkillAutoRoutingHook(BaseAgentHook):
    """Automatically loads relevant skills based on user intent.

    Parameters
    ----------
    threshold:
        Minimum match score (matching triggers / total triggers) for a
        skill to be auto-loaded.  Default 0.3.
    top_k:
        Maximum number of skills to auto-load per turn.  Default 3.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.3,
        top_k: int = 3,
    ) -> None:
        self._threshold = threshold
        self._top_k = top_k
        self._trigger_data: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------
    # Lazy one-time initialization
    # ------------------------------------------------------------------

    def _ensure_trigger_data(self) -> dict[str, list[str]]:
        """Lazily build and cache the skill → triggers mapping."""
        if self._trigger_data is not None:
            return self._trigger_data

        from app.agent.tools.builtin.skill import (
            _iter_skill_roots,
            discover_skills,
            extract_triggers,
        )

        trigger_data: dict[str, list[str]] = {}
        for root in [r for r in _iter_skill_roots() if r.is_dir()]:
            for info in discover_skills(skills_dir=root).values():
                skill_dir = Path(info["dir"])
                name = info["name"]
                if name in trigger_data:
                    continue
                triggers = extract_triggers(skill_dir)
                if triggers:
                    trigger_data[name] = triggers

        self._trigger_data = trigger_data
        logger.debug(
            "skill_auto_routing_loaded skills={} total_triggers={}",
            len(trigger_data),
            sum(len(t) for t in trigger_data.values()),
        )
        return trigger_data

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _score_message(message: str, triggers: list[str]) -> float:
        """Return the fraction of *triggers* found in *message*.

        Triggers are short keywords (single words or short phrases).
        Matching uses word-boundary prefix search so that ``test``
        matches "test", "tests", and "testing" but not "contested".
        """
        if not triggers:
            return 0.0
        msg_lower = message.lower()
        matched = sum(
            1 for t in triggers if re.search(r"\b" + re.escape(t), msg_lower)
        )
        return matched / len(triggers)

    # ------------------------------------------------------------------
    # Hook entry point
    # ------------------------------------------------------------------

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        trigger_data = self._ensure_trigger_data()
        if not trigger_data:
            return

        # Find the latest HumanMessage.
        user_text: str | None = None
        for msg in reversed(state.messages):
            if isinstance(msg, HumanMessage):
                user_text = msg.text_content()
                break
        if not user_text:
            return

        # Skills already loaded (explicit metadata or in message history).
        loaded: set[str] = set(state.metadata.get("loaded_skills", {}).keys())
        loaded |= self._loaded_from_messages(state)

        # Score every unloaded skill.
        scored: list[tuple[str, float]] = []
        for skill_name, triggers in trigger_data.items():
            if skill_name in loaded:
                continue
            score = self._score_message(user_text, triggers)
            if score > self._threshold:
                scored.append((skill_name, score))

        if not scored:
            return

        # Take top_k by descending score.
        scored.sort(key=lambda x: x[1], reverse=True)
        top_skills = scored[: self._top_k]

        # Find insertion point — after the first HumanMessage.
        insert_idx = self._find_insertion_index(state)
        if insert_idx is None:
            return

        # Read skill bodies and build synthetic messages.
        from app.agent.tools.builtin.skill import (
            _parse_frontmatter,
            _render_tokens,
            discover_skills,
        )

        discovered = discover_skills()
        tool_calls: list[ToolCall] = []
        tool_messages: list[ToolMessage] = []

        for skill_name, score in top_skills:
            info = discovered.get(skill_name)
            if info is None:
                continue
            skill_dir = Path(info["dir"])
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            _, body = _parse_frontmatter(text)
            rendered = _render_tokens(body, skill_dir=skill_dir)

            call_id = f"auto_{uuid.uuid4().hex[:12]}"
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
                    content=rendered,
                )
            )

            # Pre-seed loaded_skills metadata.
            state.metadata.setdefault("loaded_skills", {})[skill_name] = rendered

        if not tool_calls:
            return

        assistant_msg = AssistantMessage(
            content=None,
            tool_calls=tool_calls,
        )
        synthetic = [assistant_msg, *tool_messages]
        state.messages[insert_idx:insert_idx] = synthetic

        logger.info(
            "skill_auto_routed agent={} skills={} scores={}",
            ctx.agent_name,
            [name for name, _ in top_skills],
            {name: round(s, 3) for name, s in top_skills},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _loaded_from_messages(state: "AgentState") -> set[str]:
        """Return names of skills already referenced in message history."""
        loaded: set[str] = set()
        for msg in state.messages:
            if not isinstance(msg, AssistantMessage):
                continue
            for tc in msg.tool_calls or []:
                if tc.function.name == "skill":
                    try:
                        args = json.loads(tc.function.arguments)
                        name = args.get("skill_name")
                        if isinstance(name, str) and name:
                            loaded.add(name)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
        return loaded

    @staticmethod
    def _find_insertion_index(state: "AgentState") -> int | None:
        """Return the index AFTER the first HumanMessage, or None."""
        for i, msg in enumerate(state.messages):
            if isinstance(msg, HumanMessage):
                return i + 1
        return None
