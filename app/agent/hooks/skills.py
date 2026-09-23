"""The Agent Skills runtime contract for one agent run.

See ``documents/architecture/agent-skills.md``. Per run this hook:

* discovers the Skill catalog for the run's authorized workspaces;
* adds every active Skill directory to the sandbox read-only roots so the
  model can ``read`` Skill files and run bundled scripts;
* turns ``$name`` mentions in the latest user message into ``read`` calls of
  the matching ``SKILL.md``;
* grants a plugin's MCP tools once one of its Skills has been read;
* appends the ``## Skills`` system-prompt section (Level 1 catalog plus any
  Skills preloaded by the agent's ``skills:`` field).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.model_context import PREFIX_SNAPSHOT_FROZEN_KEY
from app.agent.schemas.chat import HumanMessage
from app.agent.skills.activation import (
    activated_skills,
    full_read_path,
    insert_skill_read,
    plugin_root,
)
from app.agent.skills.invocation import skill_mentions
from app.agent.skills.prompt import read_skill_body, render_skills_section
from app.agent.skills.registry import (
    SkillCatalog,
    discover_skills,
    sandbox_workspace_roots,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage, ToolCall
    from app.agent.skills.models import Skill
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
        ToolCallHandler,
    )


CATALOG_KEY = "skill_catalog"
_PROMPT_KEY = "_skills_prompt"
_FINALIZE_KEY = "_finalize_skills_prompt"


def run_skill_catalog(state: AgentState) -> SkillCatalog | None:
    """The catalog discovered for the current run, if any."""

    catalog = state.metadata.get(CATALOG_KEY)
    return catalog if isinstance(catalog, SkillCatalog) else None


def _allow_skill_files(skills: Sequence[Skill]) -> None:
    from app.agent.sandbox import get_sandbox

    try:
        sandbox = get_sandbox()
    except Exception:  # noqa: BLE001 - no sandbox outside a run
        return
    for skill in skills:
        for directory in (skill.directory, plugin_root(skill)):
            if directory is None:
                continue
            resolved = directory.resolve()
            covered = [*sandbox.allowed_workspace_roots, *sandbox.read_only_paths]
            if not any(
                resolved == root or resolved.is_relative_to(root) for root in covered
            ):
                sandbox.read_only_paths.append(resolved)


def _grant_plugin_tools(state: AgentState, skill: Skill) -> None:
    """Make a plugin Skill's MCP tools callable from the next model call."""

    grant = state.metadata.get("_grant_plugin_mcp_tools")
    if skill.plugin_id and callable(grant):
        tools = grant(skill.plugin_id)
        state.metadata.setdefault("activated_deferred_tools", set()).update(tools)


def _record_activation(skill: Skill) -> None:
    try:
        from app.conductor.telemetry import record_skill_usage

        record_skill_usage(skill.name)
    except Exception:  # noqa: BLE001 - telemetry never blocks a run
        pass


class SkillsHook(BaseAgentHook):
    """Discovery, file access, ``$name`` activation and the prompt section."""

    def __init__(self, *, preloaded: Sequence[str] = ()) -> None:
        self._preloaded = tuple(dict.fromkeys(preloaded))

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        catalog = discover_skills(sandbox_workspace_roots())
        state.metadata[CATALOG_KEY] = catalog
        _allow_skill_files(catalog.active())

        await self._activate_mentions(ctx, state, catalog)
        for skill in activated_skills(state.messages, catalog).values():
            _grant_plugin_tools(state, skill)

        preloaded: list[tuple[Skill, str]] = []
        for name in self._preloaded:
            skill = catalog.get(name)
            if skill is None or not skill.valid or not skill.enabled:
                logger.warning(
                    "skill_preload_unavailable agent={} skill={}", ctx.agent_name, name
                )
                continue
            try:
                preloaded.append((skill, read_skill_body(skill)))
            except (OSError, UnicodeError) as exc:
                logger.warning(
                    "skill_preload_failed agent={} skill={} error={}",
                    ctx.agent_name,
                    name,
                    exc,
                )
                continue
            _grant_plugin_tools(state, skill)
        preloaded_names = {skill.name for skill, _body in preloaded}
        state.metadata[_PROMPT_KEY] = render_skills_section(
            [
                skill
                for skill in catalog.model_visible()
                if skill.name not in preloaded_names
            ],
            preloaded,
        )

    async def _activate_mentions(
        self, ctx: RunContext, state: AgentState, catalog: SkillCatalog
    ) -> None:
        latest = next(
            (
                (position, message)
                for position, message in reversed(list(enumerate(state.messages)))
                if isinstance(message, HumanMessage)
            ),
            None,
        )
        if latest is None:
            return
        index, message = latest
        text = message.text_content() or ""
        already = activated_skills(state.messages, catalog)
        insert_at = index + 1
        for name in skill_mentions(text):
            skill = catalog.get(name)
            if skill is None or not skill.user_visible or name in already:
                continue
            if await insert_skill_read(state, skill, insert_at=insert_at):
                insert_at += 2
                _record_activation(skill)
                logger.debug(
                    "skill_user_activated agent={} skill={}", ctx.agent_name, name
                )

    async def before_model(
        self, ctx: RunContext, state: AgentState, request: ModelRequest
    ) -> ModelRequest | None:
        if state.metadata.get(PREFIX_SNAPSHOT_FROZEN_KEY) is True:
            return None
        if state.metadata.get(_FINALIZE_KEY) is True:
            return None
        section = state.metadata.get(_PROMPT_KEY)
        if not section:
            return None
        return request.override(system_prompt=_append(request.system_prompt, section))

    async def wrap_tool_call(
        self,
        ctx: RunContext,
        state: AgentState,
        tool_call: ToolCall,
        handler: ToolCallHandler,
    ) -> str:
        result = await handler(ctx, state, tool_call)
        path = full_read_path(tool_call)
        catalog = run_skill_catalog(state)
        if path and catalog is not None and not str(result).startswith("Error:"):
            skill = catalog.for_location(Path(path))
            if skill is not None:
                _grant_plugin_tools(state, skill)
                _record_activation(skill)
        return result


class SkillsPromptFinalizerHook(BaseAgentHook):
    """Append the Skills section after the stable prompt in team runs.

    Installed at the end of the team hook pipeline so the section lands after
    the cache boundary; :class:`SkillsHook` then leaves the prompt alone.
    """

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        state.metadata[_FINALIZE_KEY] = True

    async def wrap_model_call(
        self,
        ctx: RunContext,
        state: AgentState,
        request: ModelRequest,
        handler: ModelCallHandler,
    ) -> AssistantMessage:
        section = state.metadata.get(_PROMPT_KEY)
        if state.metadata.get(PREFIX_SNAPSHOT_FROZEN_KEY) is True or not section:
            return await handler(request)
        return await handler(
            request.override(system_prompt=_append(request.system_prompt, section))
        )


def _append(system_prompt: str | None, section: str) -> str:
    return f"{system_prompt}\n\n{section}" if system_prompt else section


__all__ = [
    "CATALOG_KEY",
    "SkillsHook",
    "SkillsPromptFinalizerHook",
    "run_skill_catalog",
]
