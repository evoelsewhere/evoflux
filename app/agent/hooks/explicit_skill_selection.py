"""Materialise a user-selected skill through the canonical activation path."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import HumanMessage

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


_SLASH_DIRECTIVE_RE = re.compile(
    r"^/skill:"
    r"([a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?)"
    r"(?=\s|$)"
)
_DOLLAR_DIRECTIVE_RE = re.compile(
    r"(?<![a-zA-Z0-9_$])\$"
    r"([a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?)"
    r"(?=\s|[.,!?;:]|$)"
)


class ExplicitSkillSelectionHook(BaseAgentHook):
    """Materialise an exact ``$name`` or ``/skill:<name>`` directive."""

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        user_index, user_text = self._latest_user_message(state)
        if user_index is None or not user_text:
            return
        selector = self._selector(user_text)
        if selector is None:
            return

        from app.agent.tools.builtin.skill import discover_skill_records_runtime

        mode = "coding" if state.metadata.get("team_mode") == "coding" else "work"
        discovered = {
            name: record
            for name, record in discover_skill_records_runtime(mode=mode).items()
            if record.valid and record.user_invocable and mode in record.modes
        }
        skill_name = self._resolve_name(selector, discovered)
        if skill_name is None:
            logger.warning(
                "skill_explicit_not_found agent={} selector={}",
                ctx.agent_name,
                selector,
            )
            return
        # An exact user directive owns this turn even when its durable
        # activation pair already exists in history. Mark precedence before
        # the idempotency check so implicit resolution cannot select a second
        # workflow for the same request.
        state.metadata["explicit_skill_selected"] = skill_name
        if skill_name in self._loaded_skills(state):
            return
        if await self._inject(state, skill_name, discovered, insert_at=user_index + 1):
            logger.debug(
                "skill_explicit_selected agent={} skill={}",
                ctx.agent_name,
                skill_name,
            )

    @staticmethod
    def _latest_user_message(state: "AgentState") -> tuple[int | None, str | None]:
        for index in range(len(state.messages) - 1, -1, -1):
            message = state.messages[index]
            if isinstance(message, HumanMessage):
                return index, message.text_content()
        return None, None

    @staticmethod
    def _selector(message: str) -> str | None:
        # Composer quote context precedes the directive. Only the first real
        # user-content line can select a skill.
        for line in message.splitlines():
            if not line or line == ">" or line.startswith("> "):
                continue
            match = _SLASH_DIRECTIVE_RE.match(line) or _DOLLAR_DIRECTIVE_RE.search(line)
            return match.group(1) if match else None
        return None

    @staticmethod
    def _resolve_name(selector: str, discovered: Mapping[str, object]) -> str | None:
        if selector in discovered:
            return selector
        nested = selector.replace(":", "/", 1)
        return nested if nested in discovered else None

    @staticmethod
    def _loaded_skills(state: "AgentState") -> set[str]:
        # Use the same canonical rehydration contract as the runtime tool:
        # only a visible, paired ``action=load`` result containing the
        # structured <skill_content> activation counts. Metadata is an
        # ephemeral cache and may be stale after restore/compaction, while a
        # list/resource/failed or excluded historical call is not activation.
        from app.agent.tools.builtin.skill import _loaded_skills_from_messages

        loaded = _loaded_skills_from_messages(state)
        state.metadata["loaded_skills"] = loaded
        return set(loaded)

    @staticmethod
    async def _inject(
        state: "AgentState",
        skill_name: str,
        discovered: Mapping[str, object],
        *,
        insert_at: int,
    ) -> bool:
        from app.agent.skills.activation import (
            SkillDependencyError,
            activate_skill_with_runtime,
            inject_skill_activation,
        )
        from app.agent.skills.models import SkillRecord

        record = discovered.get(skill_name)
        if not isinstance(record, SkillRecord):
            return False
        try:
            rendered = await activate_skill_with_runtime(state, record)
        except (OSError, UnicodeError, ValueError, SkillDependencyError):
            return False
        inject_skill_activation(
            state,
            skill_name=skill_name,
            content=rendered,
            source="explicit",
            insert_at=insert_at,
        )
        return True
