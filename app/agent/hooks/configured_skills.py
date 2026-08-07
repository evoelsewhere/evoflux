"""Preload skills explicitly assigned in an agent configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.skills.activation import activate_skill, inject_skill_activation

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


MAX_CONFIGURED_SKILL_BYTES = 96_000
# Compatibility alias for extensions; accounting is UTF-8 byte-based.
MAX_CONFIGURED_SKILL_CHARS = MAX_CONFIGURED_SKILL_BYTES


class ConfiguredSkillsHook(BaseAgentHook):
    """Make the ``skills:`` agent field an explicit, durable capability.

    This is the one intentional full-body preload path: a user assigned these
    skills to this agent. Unassigned skills remain progressively disclosed via
    the metadata catalog.
    """

    def __init__(self, names: Sequence[str], *, mode: str) -> None:
        self._names = tuple(dict.fromkeys(names))
        self._mode = "coding" if mode == "coding" else "work"

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        if not self._names:
            return
        from app.agent.tools.builtin.skill import (
            _loaded_skills_from_messages,
            discover_skill_records_runtime,
        )

        loaded = state.metadata.get("loaded_skills")
        if not isinstance(loaded, dict):
            loaded = _loaded_skills_from_messages(state)
            state.metadata["loaded_skills"] = loaded
        records = discover_skill_records_runtime(mode=self._mode)
        insert_at = len(state.messages)
        used_bytes = 0

        for name in self._names:
            if name in loaded:
                continue
            record = records.get(name)
            if record is None or not record.valid or self._mode not in record.modes:
                logger.warning(
                    "configured_skill_unavailable agent={} skill={} mode={}",
                    ctx.agent_name,
                    name,
                    self._mode,
                )
                continue
            try:
                content = await activate_skill(record)
            except (OSError, UnicodeError, ValueError) as exc:
                logger.warning(
                    "configured_skill_load_failed agent={} skill={} error={}",
                    ctx.agent_name,
                    name,
                    exc,
                )
                continue
            content_bytes = len(content.encode("utf-8"))
            if used_bytes + content_bytes > MAX_CONFIGURED_SKILL_BYTES:
                logger.warning(
                    "configured_skill_budget_skipped agent={} skill={} budget={}",
                    ctx.agent_name,
                    name,
                    MAX_CONFIGURED_SKILL_BYTES,
                )
                continue
            inject_skill_activation(
                state,
                skill_name=name,
                content=content,
                source="configured",
                insert_at=insert_at,
            )
            insert_at += 2
            used_bytes += content_bytes
            logger.info(
                "configured_skill_loaded agent={} skill={}", ctx.agent_name, name
            )


__all__ = [
    "ConfiguredSkillsHook",
    "MAX_CONFIGURED_SKILL_BYTES",
    "MAX_CONFIGURED_SKILL_CHARS",
]
