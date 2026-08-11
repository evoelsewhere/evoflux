"""Inject the bounded Tier-1 skill catalog into every model call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.providers.model_metadata import get_model_limits
from app.agent.skills.catalog import SkillCatalogRender, render_skill_catalog
from app.core.skill_scope import normalize_skill_mode

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
        self._mode = normalize_skill_mode(mode)
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
            latest_user_text = self._latest_user_text(request.messages)
            rendered = render_skill_catalog(
                records,
                mode=self._mode,
                context_window=context_window,
                preferred=self._preferred_skills,
                query=latest_user_text,
            )
            state.metadata["skill_catalog"] = {
                "included": list(rendered.included),
                "omitted": list(rendered.omitted),
                "query_ranked": list(rendered.query_ranked),
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
            logger.debug(
                "skill_catalog_ready agent={} mode={} included={} query_ranked={}",
                ctx.agent_name,
                self._mode,
                list(rendered.included),
                list(rendered.query_ranked),
            )

        if not rendered.text:
            return None
        prompt = (
            f"{request.system_prompt}\n\n{rendered.text}"
            if request.system_prompt
            else rendered.text
        )
        return request.override(system_prompt=prompt)

    @staticmethod
    def _latest_user_text(messages: Sequence[Any]) -> str:
        for message in reversed(messages):
            if getattr(message, "role", None) != "user":
                continue
            text_content = getattr(message, "text_content", None)
            value = (
                text_content()
                if callable(text_content)
                else getattr(message, "content", "")
            )
            return value if isinstance(value, str) else ""
        return ""


__all__ = ["SkillCatalogHook"]
