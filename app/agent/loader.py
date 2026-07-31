"""Agent configuration loader.

Loads agent definitions from per-agent Markdown files with YAML frontmatter.

Configuration philosophy
------------------------

Each agent lives in its own ``.md`` file inside a directory (default
``{CONFIG_DIR}/agents/``).  YAML frontmatter carries all config fields; the
Markdown body is the system prompt.  A thin ``team.yaml`` (optional) in the
same directory holds team-level metadata (name, description).

File format
-----------

agents/
  orchestrator.md   ← role: lead (exactly one per directory)
  explorer.md
  executor.md

Each file::

    ---
    name: orchestrator
    role: lead
    description: Coordinates the team.
    model: googlegenai:gemini-3.1-pro-preview
    thinking_level: low
    tools: [date, read, ls]
    skills: [mcp-installer]
    fallback_model: copilot:gpt-5-mini
    ---

    You are the team orchestrator. Coordinate — do not do the work yourself.

Optional ``team.yaml`` in the same directory::

    name: task-force
    description: A versatile task force.

Usage
-----

.. code-block:: python

    from pathlib import Path
    from app.agent.loader import load_team_from_dir

    team = load_team_from_dir(Path(".evoflux/config/agents"))
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.agent.schemas.agent import AgentContext
from app.agent.config import (
    PROVIDER_MODEL_TOKEN,
    AgentConfig,
    _FRONTMATTER_RE,
    member_model_is_configured,
    parse_agent_md,
)

if TYPE_CHECKING:
    from app.agent.mode.team.team import AgentTeam

from loguru import logger
from app.agent.agent_loop import Agent
from app.agent.drift import ConfigStamp, detect_drift, stamp_agent_files
from app.agent.providers.factory import ProviderFactory, build_provider
from app.agent.tools.registry import Tool
from app.core.db import DbFactory, resolve_db_factory

# Re-exports for callers that historically imported these symbols from
# ``app.agent.loader``.
__all__ = [
    "AgentConfig",
    "ConfigStamp",
    "PROVIDER_MODEL_TOKEN",
    "ProviderFactory",
    "_FRONTMATTER_RE",
    "detect_drift",
    "member_model_is_configured",
    "parse_agent_md",
    "stamp_agent_files",
]


def _builtin_agent_md(
    *,
    name: str,
    role: str,
    description: str,
    model: str | None,
    thinking_level: str,
    skills: list[str] | None = None,
) -> str:
    frontmatter: dict[str, Any] = {
        "name": name,
        "role": role,
        "description": description,
        "model": model,
        "thinking_level": thinking_level,
    }
    if skills:
        frontmatter["skills"] = skills
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def ensure_builtin_agent_blueprints(agents_dir: Path, *, mode: str) -> list[str]:
    """Materialise missing first-party member ``.md`` files for *mode*.

    Built-in prompt/tool definitions live in code, so this does not depend on
    the source ``seed/`` tree being bundled in production. User-owned files win:
    existing ``.md`` files are never overwritten.
    """
    from app.agent.builtin_prompts import BUILTIN_AGENT_BLUEPRINTS

    agents_dir.mkdir(parents=True, exist_ok=True)
    model = _lead_model_for_dir(agents_dir) or PROVIDER_MODEL_TOKEN
    written: list[str] = []
    for name, blueprint in BUILTIN_AGENT_BLUEPRINTS.get(mode, {}).items():
        target = agents_dir / f"{name}.md"
        if target.exists():
            continue
        _atomic_write_text(
            target,
            _builtin_agent_md(
                name=blueprint["name"],
                role=blueprint["role"],
                description=blueprint["description"],
                model=model,
                thinking_level=blueprint["thinking_level"],
                skills=blueprint.get("skills"),
            ),
        )
        written.append(target.name)
    if written:
        logger.info(
            "builtin_agent_blueprints_materialized mode={} dir={} files={}",
            mode,
            agents_dir,
            written,
        )
    return written


def _lead_model_for_dir(agents_dir: Path) -> str | None:
    if not agents_dir.exists():
        return None
    for path in sorted(agents_dir.glob("*.md")):
        try:
            cfg = parse_agent_md(path)
        except Exception:
            continue
        if cfg.role == "lead" and member_model_is_configured(cfg.model):
            return cfg.model
    return None


def _dir_has_lead(agents_dir: Path) -> bool:
    """Return whether *agents_dir* already contains any ``role: lead`` agent."""
    if not agents_dir.exists():
        return False
    for path in sorted(agents_dir.glob("*.md")):
        try:
            cfg = parse_agent_md(path)
        except Exception:
            continue
        if cfg.role == "lead":
            return True
    return False


def ensure_builtin_lead_blueprint(agents_dir: Path, *, mode: str) -> str | None:
    """Materialise a builtin ``evoflux.md`` lead file if *agents_dir* has none.

    This is a first-run/self-heal safety net for ``ensure_workspace_initialized``:
    normally the lead agent comes from the downloaded seed bundle, but if that
    download fails (offline, 404, ...) only member blueprints get backfilled by
    ``ensure_builtin_agent_blueprints`` and the workspace is left without a lead.
    Callers that validate team invariants (e.g. the agents CRUD API rejecting a
    delete that would leave zero leads) must not call this — it is only safe to
    run at workspace bootstrap, before any user-driven CRUD has happened.
    """
    from app.agent.builtin_prompts import (
        CODING_EVOFLUX_DESCRIPTION,
        WORK_EVOFLUX_DESCRIPTION,
    )

    agents_dir.mkdir(parents=True, exist_ok=True)
    if _dir_has_lead(agents_dir):
        return None

    model = PROVIDER_MODEL_TOKEN
    description = (
        CODING_EVOFLUX_DESCRIPTION if mode == "coding" else WORK_EVOFLUX_DESCRIPTION
    )
    target = agents_dir / "evoflux.md"
    _atomic_write_text(
        target,
        _builtin_agent_md(
            name="evoflux",
            role="lead",
            description=description,
            model=model,
            thinking_level="low",
        ),
    )
    return target.name


def _is_retired_builtin_member(mode: str, name: str) -> bool:
    """Return whether a first-party member should be hidden for *mode*.

    This lets newer curated builtin sets stop exposing old generated/shipped
    files without deleting user config. A custom file with the same name still
    stays on disk; it is just not a spawnable first-party blueprint in that mode.
    """
    if mode != "coding":
        return False
    return name == "executor"


# ---------------------------------------------------------------------------
# Built-in tool registry
# ---------------------------------------------------------------------------


def _default_tool_registry() -> dict[str, Tool]:
    from app.agent.mcp import mcp_manager
    from app.agent.tools.builtin import (
        add_code_review_comment,
        add_code_review_inline_comment,
        background_process,
        browser_use,
        close_code_review,
        create_pull_request,
        get_code_review,
        get_code_review_checks,
        edit_file,
        get_date,
        glob_files,
        grep_files,
        list_directory,
        list_code_reviews,
        load_skill,
        merge_code_review,
        patch_file,
        python_tool,
        read_file,
        reopen_code_review,
        reopen_code_review_thread,
        reply_code_review_thread,
        remove_path,
        resolve_code_review_thread,
        schedule_task,
        shell_tool,
        submit_code_review,
        todo_manage,
        web_fetch,
        web_search,
        webbridge,
        update_code_review,
        image_search,
        write_file,
    )
    from app.agent.tools.builtin.pptx_engine import pptx_engine as pptx_engine_tool
    from app.agent.tools.builtin.xlsx_tool import xlsx_engine
    from app.agent.tools.builtin.docx_tool import docx_engine
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.tools.builtin.memory_search import memory_search
    from app.agent.tools.builtin.note import note_tool
    from app.agent.tools.builtin.wiki_search import wiki_search
    from app.agent.tools.builtin.code_graph import (
        code_search,
        code_graph,
        code_overview,
        code_path,
    )
    from app.agent.tools.builtin.plan import enter_plan_mode, exit_plan_mode
    from app.agent.tools.builtin.ask_user import ask_user
    from app.agent.tools.builtin.chapter import mark_chapter
    from app.agent.tools.builtin.bg_tasks import (
        shell_bg_start,
        shell_bg_status,
        shell_bg_wait,
    )
    from app.agent.tools.builtin.worktree import worktree_start, worktree_finish
    from app.agent.tools.builtin.lsp import (
        code_definition,
        code_references,
        lsp_diagnostics,
        lsp_definition,
        lsp_references,
        static_diagnostics,
    )
    from app.agent.tools.builtin.visualize import visualize_read_me, show_widget
    from app.agent.tools.builtin.preview import preview_tool
    from app.agent.tools.builtin.aim import (
        aim_capture,
        aim_claim,
        aim_compare,
        aim_execute,
        aim_readiness,
        aim_rules,
        aim_suggestions,
        aim_understanding,
        aim_units,
        aim_verify,
    )
    from app.agent.tools.builtin.terminal import terminal_run

    registry: dict[str, Tool] = {
        "web_search": web_search,
        "web_fetch": web_fetch,
        "image_search": image_search,
        "browser_use": browser_use,
        "webbridge": webbridge,
        "preview": preview_tool,
        "date": get_date,
        "read": read_file,
        "write": write_file,
        "edit": edit_file,
        "ls": list_directory,
        "grep": grep_files,
        "glob": glob_files,
        "patch": patch_file,
        "rm": remove_path,
        "python": python_tool,
        "pptx_engine": pptx_engine_tool,
        "xlsx_engine": xlsx_engine,
        "docx_engine": docx_engine,
        "shell": shell_tool,
        "bg": background_process,
        "skill": load_skill,
        "load_tool": load_tool,
        "schedule_task": schedule_task,
        "todo_manage": todo_manage,
        "wiki_search": wiki_search,
        "memory_search": memory_search,
        "note": note_tool,
        "code_search": code_search,
        "code_graph": code_graph,
        "code_overview": code_overview,
        "code_path": code_path,
        "enter_plan_mode": enter_plan_mode,
        "exit_plan_mode": exit_plan_mode,
        "ask_user": ask_user,
        "shell_bg_start": shell_bg_start,
        "shell_bg_status": shell_bg_status,
        "shell_bg_wait": shell_bg_wait,
        "worktree_start": worktree_start,
        "worktree_finish": worktree_finish,
        "create_pull_request": create_pull_request,
        "list_code_reviews": list_code_reviews,
        "get_code_review": get_code_review,
        "add_code_review_comment": add_code_review_comment,
        "add_code_review_inline_comment": add_code_review_inline_comment,
        "reply_code_review_thread": reply_code_review_thread,
        "resolve_code_review_thread": resolve_code_review_thread,
        "reopen_code_review_thread": reopen_code_review_thread,
        "submit_code_review": submit_code_review,
        "update_code_review": update_code_review,
        "get_code_review_checks": get_code_review_checks,
        "merge_code_review": merge_code_review,
        "close_code_review": close_code_review,
        "reopen_code_review": reopen_code_review,
        "lsp_diagnostics": lsp_diagnostics,
        "lsp_definition": lsp_definition,
        "lsp_references": lsp_references,
        "static_diagnostics": static_diagnostics,
        "code_definition": code_definition,
        "code_references": code_references,
        "mark_chapter": mark_chapter,
        "visualize_read_me": visualize_read_me,
        "show_widget": show_widget,
        "aim_units": aim_units,
        "aim_capture": aim_capture,
        "aim_compare": aim_compare,
        "aim_readiness": aim_readiness,
        "aim_rules": aim_rules,
        "aim_suggestions": aim_suggestions,
        "aim_understanding": aim_understanding,
        "aim_claim": aim_claim,
        "aim_execute": aim_execute,
        "aim_verify": aim_verify,
        "terminal_run": terminal_run,
    }
    # Merge MCP tools from healthy servers. Names follow ``mcp_<server>_<tool>``
    # so they cannot collide with the builtins above.
    registry.update(mcp_manager.get_tools_dict())
    return registry


# ---------------------------------------------------------------------------
# Internal agent builder
# ---------------------------------------------------------------------------


def _build_agent(
    cfg: AgentConfig,
    tool_registry: dict[str, Tool],
    provider_factory: ProviderFactory,
    *,
    source_path: Path | None = None,
    mode: str = "work",
) -> Agent:
    """Construct one Agent.  ``source_path`` enables drift detection."""
    system_prompt = cfg.system_prompt
    if cfg.role == "lead" and cfg.name.lower() == "evoflux":
        from app.agent.builtin_prompts import (
            apply_EVOFLUX_extra_prompt,
            EVOFLUX_description_for_mode,
        )

        cfg.description = cfg.description or EVOFLUX_description_for_mode(mode)
        system_prompt = apply_EVOFLUX_extra_prompt(mode, cfg.system_prompt)
    elif cfg.role == "member":
        from app.agent.builtin_prompts import (
            apply_member_extra_prompt,
            builtin_member_profile,
        )

        profile = builtin_member_profile(mode, cfg.name)
        if profile is not None:
            built_in_prompt = profile["prompt"]
            cfg.description = cfg.description or profile["description"]
            cfg.skills = [*profile["skills"], *cfg.skills]
            cfg.mcp = [*profile["mcp"], *cfg.mcp]
            system_prompt = apply_member_extra_prompt(
                cfg.name, built_in_prompt, cfg.system_prompt
            )

    # Tier grant: every agent gets all tools of its mode's tier (filtered by
    # role for lead_only tools). Frontmatter ``tools:`` entries remain as
    # extras on top — useful for custom agents referencing MCP tools by name.
    from app.agent.builtin_prompts import tier_tools

    cfg.tools = [*tier_tools(tool_registry, mode=mode, role=cfg.role), *cfg.tools]

    if cfg.skills:
        cfg.skills = list(dict.fromkeys(cfg.skills))

    # Validate assigned skills exist and pre-load their bodies for injection
    # as synthetic tool messages (via SkillPreloadHook) rather than bloating
    # the system prompt on every turn.
    preloaded_skills: dict[str, str] = {}
    if cfg.skills:
        from app.agent.tools.builtin.skill import (
            _parse_frontmatter,
            _render_tokens,
            discover_skills as _discover,
        )

        available = _discover()
        for sk in cfg.skills:
            if sk not in available:
                logger.warning(
                    "agent_skill_not_found agent={} skill={}",
                    cfg.name,
                    sk,
                )
                continue
            skill_path = Path(available[sk]["dir"]) / "SKILL.md"
            try:
                text = skill_path.read_text(encoding="utf-8")
                _, body = _parse_frontmatter(text)
                if body:
                    rendered = _render_tokens(body, skill_dir=skill_path.parent)
                    preloaded_skills[sk] = rendered
            except OSError:
                logger.warning(
                    "agent_skill_read_failed agent={} skill={} path={}",
                    cfg.name,
                    sk,
                    skill_path,
                )

    from app.agent.tools.builtin.schedule import schedule_task as _schedule_task_tool
    from app.agent.tools.builtin.skill import load_skill as _load_skill_tool
    from app.agent.tools.builtin.todo import todo_manage

    _load_skill = tool_registry.get("skill", _load_skill_tool)
    tools: list[Tool] = [_load_skill]

    # These tools are always available to the lead agent — not listed in frontmatter.
    if cfg.role == "lead":
        from app.agent.tools.builtin.note import note_tool as _note_tool

        _todo_manage = tool_registry.get("todo_manage", todo_manage)
        _schedule_task = tool_registry.get("schedule_task", _schedule_task_tool)
        _note = tool_registry.get("note", _note_tool)
        tools += [_todo_manage, _schedule_task, _note]

    seen: set[str] = {t.name for t in tools}
    cfg.tools = list(dict.fromkeys(cfg.tools))
    cfg.mcp = list(dict.fromkeys(cfg.mcp))
    for tool_name in cfg.tools:
        if tool_name in ("skill", "todo_manage", "schedule_task", "note"):
            continue
        if tool_name not in tool_registry:
            # Soft-skip: settings/self-healing edits and disabled-then-rebuild
            # flows can leave a name in frontmatter briefly after the
            # underlying tool/MCP server disappears between loads.

            logger.warning(
                "agent_unknown_tool agent={} tool={} available={}",
                cfg.name,
                tool_name,
                sorted(tool_registry.keys()),
            )
            continue
        if tool_name in seen:
            continue
        # lead_only is an invariant, not just a tier-grant default: a
        # frontmatter extra cannot hand a member a user-interaction /
        # session-structure tool (ask_user would deadlock a delegation).
        if getattr(tool_registry[tool_name], "lead_only", False) and cfg.role != "lead":
            logger.warning(
                "agent_lead_only_tool_skipped agent={} tool={}",
                cfg.name,
                tool_name,
            )
            continue
        seen.add(tool_name)
        tools.append(tool_registry[tool_name])

    # MCP servers: each entry grants the agent access to *all* tools exposed
    # by that server. Unknown / not-ready servers are warn-and-skip so the
    # agent still loads when an MCP server is disabled, mid-restart, or
    # removed from mcp.json while still referenced by config.
    if cfg.mcp:
        from app.agent.mcp import mcp_manager

        for server_name in cfg.mcp:
            server_tools = mcp_manager.get_tools_for_server(server_name)
            if server_tools is None:
                logger.warning(
                    "agent_unknown_mcp_server agent={} server={} configured={}",
                    cfg.name,
                    server_name,
                    sorted(mcp_manager.server_names()),
                )
                continue
            for tool in server_tools:
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                tools.append(tool)

    model_kwargs: dict[str, Any] = {}
    if cfg.thinking_level is not None:
        model_kwargs["thinking_level"] = cfg.thinking_level
    if cfg.responses_api is not None:
        model_kwargs["responses_api"] = cfg.responses_api

    # Agents seeded with the ``__PROVIDER_MODEL__`` placeholder load with
    # an :class:`UnconfiguredProvider` stub so the team manager survives
    # first-run before the user picks a provider. The stub raises
    # :class:`UnconfiguredProviderError` on first LLM call, which the
    # turn-runner translates into a typed
    # :class:`AgentNotConfiguredEvent` SSE message.
    from app.agent.providers.unconfigured import (
        UnconfiguredProvider,
        UnconfiguredProviderError,
    )

    try:
        provider = provider_factory(cfg.model, model_kwargs=model_kwargs)
    except Exception as exc:
        if not isinstance(exc, UnconfiguredProviderError):
            logger.warning(
                "agent_provider_unavailable agent={} model={} error={}",
                cfg.name,
                cfg.model,
                exc,
            )
        else:
            logger.warning(
                "agent_unconfigured_provider agent={} model={}", cfg.name, cfg.model
            )
        provider = UnconfiguredProvider(agent_name=cfg.name)

    fallback_provider = None
    if cfg.fallback_model:
        try:
            fallback_provider = provider_factory(
                cfg.fallback_model, model_kwargs=model_kwargs
            )
        except Exception as exc:
            logger.warning(
                "agent_fallback_provider_unavailable agent={} model={} error={}",
                cfg.name,
                cfg.fallback_model,
                exc,
            )
            fallback_provider = None

    agent = Agent[AgentContext](
        name=cfg.name,
        description=cfg.description,
        llm_provider=provider,
        model_id=cfg.model,
        system_prompt=system_prompt,
        tools=tools,
        skills=cfg.skills,
        mcp_servers=cfg.mcp,
        fallback_provider=fallback_provider,
        fallback_model_id=cfg.fallback_model,
    )

    # Attach skill preload hook — injects skill bodies as synthetic tool
    # messages on first activation, saving tokens on subsequent turns.
    if preloaded_skills:
        from app.agent.hooks.skill_preload import SkillPreloadHook

        agent.hooks.append(SkillPreloadHook(preloaded_skills))

    # Attach skill auto-routing hook — matches user intent to unloaded skills
    # and injects relevant ones automatically on each turn.
    from app.agent.hooks.skill_auto_routing import SkillAutoRoutingHook

    agent.hooks.append(SkillAutoRoutingHook())

    # Attach code overview hook — auto-injects a compact workspace map on first
    # turn so the agent starts oriented without wasting a round-trip.
    if "code_overview" in {t.name for t in tools}:
        from app.agent.hooks.code_overview_injection import CodeOverviewHook

        agent.hooks.append(CodeOverviewHook())

    # Stamp config dependencies for end-of-turn drift detection.
    if source_path is not None:
        from app.agent.mcp.config import config_path as _mcp_config_path
        from app.core.config import settings as _settings

        skills_root = Path(_settings.SKILLS_DIR)
        agent.source_path = source_path
        agent.config_stamp = stamp_agent_files(
            agent_md_path=source_path,
            skill_names=cfg.skills,
            skills_dir=skills_root,
            mcp_config_path=_mcp_config_path(),
        )

    return agent


# ---------------------------------------------------------------------------
# Team loader — main public API
# ---------------------------------------------------------------------------


def load_team_from_dir(
    agents_dir: str | Path,
    *,
    provider_factory: ProviderFactory | None = None,
    extra_tools: dict[str, Tool] | None = None,
    db_factory: DbFactory | None = None,
    mode: str = "work",
    workspace: str | None = None,
) -> "AgentTeam | None":
    """Load an AgentTeam from a directory of per-agent ``.md`` files.

    The lead is built eagerly; member ``.md`` files are kept as **blueprints**
    on the team and only constructed when the lead calls ``team_manage``.
    This
    means a fresh server start touches only the lead's tool/MCP/skill
    resolution — members impose zero startup cost until first use.

    Returns ``None`` if the directory does not exist or contains no ``.md`` files.
    """
    from app.agent.mode.team.member import TeamLead
    from app.agent.mode.team.team import AgentTeam, MemberBlueprint

    agents_dir = Path(agents_dir).resolve()
    if not agents_dir.exists():
        return None

    md_files = sorted(agents_dir.glob("*.md"))
    if not md_files:
        return None

    if mode in ("work", "coding"):
        ensure_builtin_agent_blueprints(agents_dir, mode=mode)
        md_files = sorted(agents_dir.glob("*.md"))

    # Carry source path so _build_agent can stamp config dependencies.
    agent_configs: list[tuple[AgentConfig, Path]] = []
    parse_errors: list[str] = []
    for md_path in md_files:
        try:
            cfg = parse_agent_md(md_path)
            agent_configs.append((cfg, md_path))
            logger.debug(
                "agent_discovered file={} name={} role={} model={}",
                md_path.name,
                cfg.name,
                cfg.role,
                cfg.model or "(none)",
            )
        except Exception as exc:
            parse_errors.append(f"  {md_path.name}: {exc}")

    if parse_errors:
        raise ValueError(
            f"Failed to parse {len(parse_errors)} agent file(s) in '{agents_dir}':\n"
            + "\n".join(parse_errors)
        )

    # Validate: exactly one lead
    leads = [(c, p) for (c, p) in agent_configs if c.role == "lead"]
    if not leads:
        raise ValueError(
            f"No agent with 'role: lead' found in '{agents_dir}'. "
            "Exactly one agent must have 'role: lead'."
        )
    if len(leads) > 1:
        names = [c.name for (c, _) in leads]
        raise ValueError(
            f"Multiple agents with 'role: lead' found in '{agents_dir}': {names}. "
            "Exactly one agent must have 'role: lead'."
        )

    lead_cfg, lead_path = leads[0]
    member_entries = [
        (c, p)
        for (c, p) in agent_configs
        if c.role == "member"
        and member_model_is_configured(c.model)
        and not _is_retired_builtin_member(mode, c.name)
    ]

    # Validate: blueprint names must be unique and must not collide with the
    # lead.  Also reject ``#`` in blueprint names since we use ``blueprint#N``
    # as the runtime instance handle (see AgentTeam.spawn).
    blueprints: dict[str, MemberBlueprint] = {}
    for cfg, path in member_entries:
        if "#" in cfg.name:
            raise ValueError(
                f"Member blueprint '{cfg.name}' in '{path.name}' contains '#'. "
                "Reserved character — instances are named 'blueprint#N'."
            )
        if cfg.name == lead_cfg.name:
            raise ValueError(
                f"Member '{cfg.name}' in '{path.name}' shares the lead's name."
            )
        if cfg.name in blueprints:
            raise ValueError(f"Duplicate member name '{cfg.name}' in '{path.name}'.")
        description = cfg.description
        if description is None:
            from app.agent.builtin_prompts import builtin_member_profile

            profile = builtin_member_profile(mode, cfg.name)
            description = profile["description"] if profile is not None else cfg.name
        blueprints[cfg.name] = MemberBlueprint(
            name=cfg.name,
            description=description,
            source_path=path,
        )

    tool_registry = _default_tool_registry()
    if extra_tools:
        tool_registry.update(extra_tools)

    if provider_factory is None:
        provider_factory = build_provider

    db_factory = resolve_db_factory(db_factory)

    # Unknown tools / MCP servers in frontmatter are warn-and-skipped by
    # ``_build_agent`` so stale config entries or mcp.json edits never break
    # agent load.

    # Build the lead.  Members are NOT built — they are described by their
    # blueprints on the team and built on demand by ``AgentTeam.spawn``.
    lead_agent = _build_agent(
        lead_cfg, tool_registry, provider_factory, source_path=lead_path, mode=mode
    )
    lead_member = TeamLead(lead_agent, db_factory=db_factory)

    team = AgentTeam(
        lead=lead_member,
        blueprints=blueprints,
        provider_factory=provider_factory,
        extra_tools=extra_tools,
        db_factory=db_factory,
        mode=mode,
        workspace=workspace,
    )
    logger.info(
        "team_loaded lead={} blueprints={}",
        lead_cfg.name,
        sorted(blueprints.keys()),
    )
    return team


# ---------------------------------------------------------------------------
# Single-agent rebuild — used by ``TeamMemberBase`` for in-place refresh
# ---------------------------------------------------------------------------


def rebuild_agent_from_disk(
    source_path: Path,
    *,
    provider_factory: ProviderFactory | None = None,
    extra_tools: dict[str, Tool] | None = None,
    mode: str = "work",
) -> Agent:
    """Re-parse one agent ``.md`` and return a fresh :class:`Agent`.

    Called by :class:`TeamMemberBase` when drift is detected.  Caller
    swaps the new agent in place; ``ValueError`` on parse/registry failure.
    """
    cfg = parse_agent_md(source_path)

    tool_registry = _default_tool_registry()
    if extra_tools:
        tool_registry.update(extra_tools)

    if provider_factory is None:
        provider_factory = build_provider

    return _build_agent(
        cfg, tool_registry, provider_factory, source_path=source_path, mode=mode
    )
