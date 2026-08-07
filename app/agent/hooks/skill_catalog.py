"""Inject the bounded Tier-1 skill catalog into every model call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.providers.model_metadata import get_model_limits
from app.agent.skills.catalog import SkillCatalogRender, render_skill_catalog

if TYPE_CHECKING:
    from app.agent.state import AgentState, ModelRequest, RunContext


class SkillCatalogHook(BaseAgentHook):
    """Expose name/description metadata without eagerly loading skill bodies."""

    def __init__(
        self,
        *,
        mode: str,
        model_id: str | None,
        preferred_skills: Sequence[str] = (),
    ) -> None:
        self._mode = "coding" if mode == "coding" else "work"
        self._model_id = model_id
        self._preferred_skills = tuple(preferred_skills)

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        state.metadata.pop("_skill_catalog_render", None)

    async def before_model(
        self,
        ctx: RunContext,
        state: AgentState,
        request: ModelRequest,
    ) -> ModelRequest | None:
        rendered = state.metadata.get("_skill_catalog_render")
        if not isinstance(rendered, SkillCatalogRender):
            from app.agent.tools.builtin.skill import discover_skill_records_runtime

            records = discover_skill_records_runtime(mode=self._mode).values()
            context_window = get_model_limits(self._model_id).context_length
            rendered = render_skill_catalog(
                records,
                mode=self._mode,
                context_window=context_window,
                preferred=self._preferred_skills,
            )
            state.metadata["skill_catalog"] = {
                "included": list(rendered.included),
                "omitted": list(rendered.omitted),
                "descriptions_shortened": rendered.descriptions_shortened,
                "budget_chars": rendered.budget_chars,
            }
            state.metadata["_skill_catalog_render"] = rendered
            if rendered.omitted:
                logger.warning(
                    "skill_catalog_budget_omitted agent={} mode={} skills={}",
                    ctx.agent_name,
                    self._mode,
                    list(rendered.omitted),
                )
            elif rendered.descriptions_shortened:
                logger.info(
                    "skill_catalog_descriptions_shortened agent={} mode={}",
                    ctx.agent_name,
                    self._mode,
                )

        if not rendered.text:
            return None
        prompt = (
            f"{request.system_prompt}\n\n{rendered.text}"
            if request.system_prompt
            else rendered.text
        )
        return request.override(system_prompt=prompt)


__all__ = ["SkillCatalogHook"]
