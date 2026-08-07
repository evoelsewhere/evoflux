"""Resolve and activate one implicit skill before the main agent call."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import HumanMessage
from app.agent.skills.activation import (
    SkillDependencyError,
    activate_skill_with_runtime,
    inject_skill_activation,
)
from app.agent.skills.resolution import resolve_skill

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


class SkillResolutionHook(BaseAgentHook):
    """Run the generic implicit-resolution stage once per user turn."""

    def __init__(self, *, mode: str) -> None:
        self._mode = "coding" if mode == "coding" else "work"

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        if state.metadata.get("explicit_skill_selected"):
            return
        request = self._latest_user_text(state)
        if not request:
            return
        provider = state.metadata.get("_runtime_provider")
        if provider is None:
            logger.warning("skill_resolution_provider_missing agent={}", ctx.agent_name)
            return

        from app.agent.tools.builtin.skill import discover_skill_records_runtime

        records = tuple(discover_skill_records_runtime(mode=self._mode).values())
        try:
            decision = await resolve_skill(
                provider,
                request=request,
                mode=self._mode,
                records=records,
            )
        except Exception as exc:  # noqa: BLE001 - resolution is best-effort
            state.metadata["skill_resolution"] = {
                "skill_name": None,
                "confidence": 0.0,
                "reason": type(exc).__name__,
                "status": "error",
            }
            logger.warning(
                "skill_resolution_failed agent={} mode={} error={}",
                ctx.agent_name,
                self._mode,
                exc,
            )
            return

        state.metadata["skill_resolution"] = decision.as_dict()
        logger.info(
            "skill_resolution_decided agent={} mode={} status={} skill={} confidence={:.2f}",
            ctx.agent_name,
            self._mode,
            decision.status,
            decision.skill_name,
            decision.confidence,
        )
        if decision.skill_name is None:
            return

        record = next(
            (record for record in records if record.name == decision.skill_name), None
        )
        if record is None:
            return
        # AgentState metadata is per-run, while canonical activation pairs are
        # durable conversation state. Rehydrate before injecting so a
        # follow-up turn never duplicates a skill body already in history.
        from app.agent.tools.builtin.skill import _loaded_skills_from_messages

        loaded = _loaded_skills_from_messages(state)
        state.metadata["loaded_skills"] = loaded
        if decision.skill_name in loaded:
            return
        try:
            content = await activate_skill_with_runtime(state, record)
        except (OSError, UnicodeError, ValueError, SkillDependencyError) as exc:
            logger.warning(
                "skill_resolution_activation_failed agent={} skill={} error={}",
                ctx.agent_name,
                decision.skill_name,
                exc,
            )
            return
        inject_skill_activation(
            state,
            skill_name=decision.skill_name,
            content=content,
            source="resolved",
        )
        logger.info(
            "skill_resolution_activated agent={} skill={}",
            ctx.agent_name,
            decision.skill_name,
        )

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.messages):
            if isinstance(message, HumanMessage):
                return message.text_content() or ""
        return ""


__all__ = ["SkillResolutionHook"]
