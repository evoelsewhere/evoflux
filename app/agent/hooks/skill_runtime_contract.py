"""Rehydrate declarative runtime contracts for durable skill activations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.skills.activation import (
    SkillDependencyError,
    apply_skill_runtime_contract,
)

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


class SkillRuntimeContractHook(BaseAgentHook):
    """Apply dependencies and observation policy for every loaded skill."""

    def __init__(self, *, mode: str) -> None:
        self._mode = "coding" if mode == "coding" else "work"

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        from app.agent.tools.builtin.skill import (
            _loaded_skills_from_messages,
            discover_skill_records_runtime,
        )

        loaded = _loaded_skills_from_messages(state)
        state.metadata["loaded_skills"] = loaded
        if not loaded:
            return
        records = discover_skill_records_runtime(mode=self._mode)
        for name in loaded:
            record = records.get(name)
            if record is None or not record.valid:
                continue
            try:
                apply_skill_runtime_contract(state, record)
            except SkillDependencyError as exc:
                state.metadata.setdefault("skill_runtime_errors", {})[name] = str(exc)
                logger.warning(
                    "skill_runtime_contract_unavailable agent={} skill={} error={}",
                    ctx.agent_name,
                    name,
                    exc,
                )


__all__ = ["SkillRuntimeContractHook"]
