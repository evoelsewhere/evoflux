"""Agent CRUD: writes ``.md`` files under ``AGENTS_DIR``.

Validates each write against ``AgentConfig`` and team invariants
(one lead, known tools, valid models).  Failed validation rolls the
file back.  Running agents pick up new config on their next turn.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from app.conductor.provenance import (
    managed_resource_provider,
    managed_resource_providers,
)
from app.conductor.agent_runtime import (
    agent_model_override,
    apply_managed_agent_runtime_model,
)
from app.conductor.models import ManagedResourceProvider
from app.core.agent_settings import (
    AgentSettingsError,
    delete_agent_runtime_model,
    read_agent_runtime_settings,
    write_agent_runtime_model,
    write_agent_runtime_settings,
)
from app.core.runtime_settings import provider_visible_models
from app.api.schemas.agents import (
    AgentBulkModelRequest,
    AgentBulkModelResponse,
    AgentBulkModelResult,
    AgentDeleteResponse,
    AgentDetail,
    AgentListResponse,
    AgentRuntimeModelRequest,
    AgentRuntimeSettingsRequest,
    AgentSummary,
    AgentWriteRequest,
    ModelCatalogEntry,
    RegistryResponse,
    SkillCatalogEntry,
    ToolCatalogEntry,
)
from app.services import agent_fs
from app.services.agent_fs import (
    AgentFsConflictError,
    AgentFsNotFoundError,
    AgentFsPathError,
)

if TYPE_CHECKING:
    from app.agent.config import AgentConfig
    from app.agent.providers.catalog import ProviderEntry

router = APIRouter()

# Live-discovered provider models are cached per-provider so each
# ``/agents/registry`` call doesn't fan out to every configured backend.
# TTL is short so newly-added models become visible without a restart.
_REGISTRY_MODEL_CACHE_TTL_S = 60.0
_registry_model_cache: dict[str, tuple[float, list[str]]] = {}


def _selectable_thinking_levels(model_id: str) -> list[str]:
    """Levels a picker may offer for this model, weakest first.

    Deliberately *not* the raw catalog list, and shared with the request
    validators so the UI cannot offer a level the API then rejects. See
    :func:`app.agent.providers.thinking.offered_levels_for`.
    """
    from app.agent.providers.thinking import offered_levels_for

    return list(offered_levels_for(model_id))


def _mode_cost_multipliers(
    modes: dict[str, Any], base_cost: dict[str, Any]
) -> dict[str, float]:
    """How much each alternate tier costs relative to the standard rate.

    Measured on the output price, which is the larger half of a coding
    agent's bill and the rate every tier that publishes one quotes. A tier
    with no price of its own is omitted rather than reported as 1.0 —
    "unknown" and "same price" are different answers, and a Fast toggle
    that silently implies parity would be the wrong one to get wrong.
    """
    base_output = base_cost.get("output")
    if not isinstance(base_output, int | float) or base_output <= 0:
        return {}
    multipliers: dict[str, float] = {}
    for name, spec in modes.items():
        rate = (spec or {}).get("cost", {}).get("output")
        if isinstance(rate, int | float) and rate > 0:
            multipliers[name] = round(rate / base_output, 2)
    return multipliers


async def discover_provider_models(
    entry: ProviderEntry, *, overrides: dict[str, str]
) -> list[str]:
    """Patch-compatible lazy wrapper for live provider discovery."""
    from app.agent.providers.model_discovery import discover_provider_models as discover

    return await discover(entry, overrides=overrides)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_summary(
    name: str,
    content: str,
    *,
    provider: ManagedResourceProvider | None = None,
) -> AgentSummary:
    """Never raises; invalid agents are flagged via ``valid=False``."""
    try:
        cfg = _parse_content(name, content)
    except ValueError as exc:
        return AgentSummary(
            name=name,
            role="member",
            description=None,
            model=None,
            tools=[],
            mcp=[],
            skills=[],
            valid=False,
            error=str(exc),
        )
    mode = _mode_for_agent_path(name)
    effective = _effective_config(cfg, mode=mode, provider=provider)
    model_override = agent_model_override(provider) if provider is not None else None
    additions = _runtime_additions(provider)
    return AgentSummary(
        name=name,
        role=effective.role,
        lead=effective.lead,
        description=effective.description,
        model=effective.model,
        tools=effective.tools,
        mcp=effective.mcp,
        skills=effective.skills,
        valid=True,
        error=None,
        runtime_model_editable=provider is not None,
        bundle_model=cfg.model if provider is not None else None,
        model_override=model_override,
        extra_tools=additions["extra_tools"],
        extra_skills=additions["extra_skills"],
        extra_mcp=additions["extra_mcp"],
    )


def _runtime_additions(
    provider: ManagedResourceProvider | None,
) -> dict[str, list[str]]:
    if provider is None:
        return {"extra_tools": [], "extra_skills": [], "extra_mcp": []}
    local = read_agent_runtime_settings(
        project_id=provider.project_id,
        resource_id=provider.resource_id,
    )
    return {
        "extra_tools": list(local.extra_tools),
        "extra_skills": list(local.extra_skills),
        "extra_mcp": list(local.extra_mcp),
    }


def _mode_for_agent_path(name: str) -> Literal["work", "coding"]:
    first = Path(name).parts[:1]
    if first == ("coding",):
        return "coding"
    return "work"


def _effective_config(
    cfg: AgentConfig,
    *,
    mode: str,
    provider: ManagedResourceProvider | None = None,
) -> AgentConfig:
    """Compile the same effective config used by the runtime."""

    from app.agent.effective_config import compile_agent_config
    from app.agent.loader import _default_tool_registry

    registry = _default_tool_registry()
    runtime_config = apply_managed_agent_runtime_model(cfg, provider=provider)
    data = compile_agent_config(runtime_config, mode=mode, tool_registry=registry)
    if data.role != "lead":
        data.tools = [
            name
            for name in data.tools
            if not getattr(registry.get(name), "lead_only", False)
        ]
    return data


def _parse_content(name: str, content: str) -> AgentConfig:
    """Parse raw .md text into an ``AgentConfig`` (no disk I/O)."""
    from app.agent.config import parse_agent_definition

    return parse_agent_definition(
        content,
        default_name=_frontmatter_name_for_path(name),
    )


def _require_frontmatter_name(name: str, content: str) -> None:
    cfg = _parse_content(name, content)
    expected_name = _frontmatter_name_for_path(name)
    if cfg.name != expected_name:
        raise HTTPException(
            status_code=422,
            detail=(f"Frontmatter name '{cfg.name}' does not match URL name '{name}'."),
        )


def _frontmatter_name_for_path(name: str) -> str:
    return Path(name).name


def _validation_dir_for_name(name: str) -> Path:
    rel_parent = Path(name).parent
    if str(rel_parent) == ".":
        return agent_fs.agents_dir()
    return agent_fs.agents_dir() / rel_parent


async def _validate_or_restore(
    rollback_name: str | None, rollback_content: str | None
) -> None:
    """Re-validate the agents directory; roll back on failure.

    ``rollback_content=None`` → delete the just-created file; otherwise
    restore the previous text.
    """
    from app.agent.loader import load_team_from_dir

    try:
        validation_dir = (
            agent_fs.agents_dir()
            if rollback_name is None
            else _validation_dir_for_name(rollback_name)
        )
        mode = _mode_for_agent_path(rollback_name or "")
        candidate = load_team_from_dir(validation_dir, mode=mode)
        if candidate is None:
            raise ValueError(
                f"No agents would remain in '{validation_dir}'. "
                "At least one .md file with 'role: lead' is required."
            )
    except ValueError as exc:
        if rollback_name is not None and rollback_content is not None:
            try:
                try:
                    agent_fs.write_agent(rollback_name, rollback_content, create=True)
                except agent_fs.AgentFsConflictError:
                    agent_fs.write_agent(rollback_name, rollback_content, create=False)
            except Exception:
                logger.exception("agents_rollback_failed name={}", rollback_name)
        elif rollback_name is not None and rollback_content is None:
            try:
                agent_fs.delete_agent(rollback_name)
            except Exception:
                logger.exception("agents_rollback_delete_failed name={}", rollback_name)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_agents() -> AgentListResponse:
    rows: list[AgentSummary] = []
    providers = managed_resource_providers()
    for name in agent_fs.list_agents():
        provider = providers.get(("agent", name))
        try:
            record = agent_fs.read_agent(name)
        except Exception as exc:
            rows.append(
                AgentSummary(
                    name=name,
                    role="member",
                    valid=False,
                    error=str(exc),
                    editable=provider is None,
                    provider=provider,
                )
            )
            continue
        rows.append(
            _parse_summary(name, record.content, provider=provider).model_copy(
                update={
                    "editable": provider is None,
                    "provider": provider,
                    "runtime_model_editable": provider is not None,
                }
            )
        )
    return AgentListResponse(agents=rows)


@router.get("/registry")
async def get_registry(
    workspace: Annotated[
        list[str] | None,
        Query(
            description="Repeat for every repository in the active workspace/project."
        ),
    ] = None,
    mode: Annotated[Literal["work", "coding"] | None, Query()] = None,
) -> RegistryResponse:
    """Dropdown catalog: tools, skills, providers, known models."""
    from app.agent.hooks.summarization import prompt_token_threshold_for_model
    from app.agent.loader import _default_tool_registry
    from app.agent.providers.capabilities import get_capabilities
    from app.agent.providers.catalog import all_providers
    from app.agent.providers.model_metadata import (
        get_effective_model_thinking,
        get_model_limits,
        get_model_metadata,
        get_model_modes,
    )
    from app.api.routes.skills import _discover_runtime_skills, _workspace_paths

    tool_registry = _default_tool_registry()
    hidden_tools = {"skill", "load_tool", "todo_manage", "schedule_task", "note"}
    tools = sorted(
        (
            ToolCatalogEntry(
                name=t.name,
                description=t.description or "",
                tiers=sorted(t.tiers or ()) or None,
                lead_only=getattr(t, "lead_only", False),
            )
            for t in tool_registry.values()
            if t.name not in hidden_tools
        ),
        key=lambda t: t.name,
    )

    skill_map = _discover_runtime_skills(_workspace_paths(workspace), mode=mode)
    skills = sorted(
        (
            SkillCatalogEntry(
                name=k,
                description=v.get("description", ""),
                display_name=v.get("display_name"),
                short_description=v.get("short_description"),
                allow_implicit_invocation=bool(
                    v.get("allow_implicit_invocation", True)
                ),
                user_invocable=bool(v.get("user_invocable", True)),
                dependencies=list(v.get("dependencies") or []),
                modes=list(v.get("modes", ("work", "coding"))),
            )
            for k, v in skill_map.items()
        ),
        key=lambda s: s.name,
    )

    # Provider IDs straight from the catalog — single source of truth.
    # Previously this was derived from the capability resolver's prefix
    # table; the resolver no longer has one (see capabilities.py).
    providers = sorted(entry["id"] for entry in all_providers())

    seen: set[str] = set()
    models: list[ModelCatalogEntry] = []

    def _append(provider: str, model: str) -> None:
        model_id = f"{provider}:{model}"
        if model_id in seen:
            return
        seen.add(model_id)
        caps = get_capabilities(model_id)
        metadata = get_model_metadata(model_id)
        effective_thinking = get_effective_model_thinking(model_id)
        limits = get_model_limits(model_id)
        features = metadata.features
        modes = get_model_modes(model_id)
        cost = {
            key: value
            for key, value in metadata.cost.to_dict().items()
            if value not in (None, [])
        }
        models.append(
            ModelCatalogEntry(
                id=model_id,
                provider=provider,
                model=model,
                vision=caps.input.vision,
                input_audio=caps.input.audio,
                input_video=caps.input.video,
                output_image=caps.output.image,
                output_video=caps.output.video,
                summary_trigger_tokens=prompt_token_threshold_for_model(model_id),
                context_length=limits.context_length,
                thinking_levels=_selectable_thinking_levels(model_id),
                thinking_control=effective_thinking.control,
                thinking_default_level=effective_thinking.default_level,
                thinking_default_enabled=effective_thinking.default_enabled,
                thinking_source=effective_thinking.source,
                interfaces=list(metadata.interfaces),
                display_name=features.name,
                description=features.description,
                family=features.family,
                status=features.status,
                release_date=features.release_date,
                last_updated=features.last_updated,
                knowledge=features.knowledge,
                max_output_tokens=limits.max_completion_tokens,
                tool_call=features.tool_call,
                attachment=features.attachment,
                temperature=features.temperature,
                structured_output=features.structured_output,
                open_weights=features.open_weights,
                cost=cost,
                free=(
                    cost["input"] == 0 and cost["output"] == 0
                    if "input" in cost and "output" in cost
                    else None
                ),
                thinking_budget=(
                    {
                        "min": effective_thinking.budget_min,
                        "max": effective_thinking.budget_max,
                    }
                    if effective_thinking.budget_min is not None
                    or effective_thinking.budget_max is not None
                    else {}
                ),
                modes=sorted(modes),
                mode_cost_multiplier=_mode_cost_multipliers(modes, cost),
            )
        )

    visible_by_provider: dict[str, set[str]] = {}
    for provider, model in await _discover_configured_registry_models():
        visible = visible_by_provider.setdefault(
            provider, set(provider_visible_models(provider))
        )
        if not visible or model in visible:
            _append(provider, model)

    models.sort(key=lambda item: (item.provider, item.model))

    return RegistryResponse(
        tools=tools,
        skills=skills,
        providers=providers,
        models=models,
    )


async def _discover_configured_registry_models() -> list[tuple[str, str]]:
    """Concurrently discover live models for every configured provider.

    Results are cached per-provider for :data:`_REGISTRY_MODEL_CACHE_TTL_S`
    seconds, and discovery failures degrade silently (the cached fallback
    or just the curated catalog is shown instead). We *only* poll
    providers that are already configured — otherwise we'd send empty
    requests to every backend on every registry call.
    """
    # Avoid a circular-import-on-startup hazard: this helper is imported
    # from settings.py for the configuration check.
    from app.api.routes.settings import (
        _cached_provider_models,
        _provider_is_configured,
        _provider_saved_overrides,
    )
    from app.agent.providers.catalog import all_providers
    from app.agent.providers.model_discovery import filter_agent_model_ids

    configured: list[ProviderEntry] = []
    cached_manual: list[tuple[str, list[str]]] = []
    for entry in all_providers():
        if not entry.get("auto_connect", True):
            if models := _cached_provider_models(entry):
                cached_manual.append((entry["id"], models))
        elif _provider_is_configured(entry):
            configured.append(entry)
    if not configured and not cached_manual:
        return []

    now = time.monotonic()

    async def _fetch(entry: ProviderEntry) -> tuple[str, list[str]]:
        provider_id = entry["id"]
        cached = _registry_model_cache.get(provider_id)
        if cached and now - cached[0] < _REGISTRY_MODEL_CACHE_TTL_S:
            return provider_id, cached[1]
        models = await discover_provider_models(
            entry, overrides=_provider_saved_overrides(entry)
        )
        _registry_model_cache[provider_id] = (now, models)
        return provider_id, models

    discovered = await asyncio.gather(
        *(_fetch(entry) for entry in configured),
        return_exceptions=True,
    )
    results: list[tuple[str, list[str]] | BaseException] = [
        *cached_manual,
        *discovered,
    ]

    out: list[tuple[str, str]] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.info("registry_model_discovery_failed error={}", result)
            continue
        provider_id, model_ids = result
        out.extend(
            (provider_id, model)
            for model in filter_agent_model_ids(provider_id, model_ids)
        )
    return out


async def is_registered_model_id(model_id: str) -> bool:
    """Return whether *model_id* is currently selectable from the registry."""
    if ":" not in model_id:
        return False
    provider, model = model_id.split(":", 1)
    if not provider or not model:
        return False

    from app.api.routes.settings import _provider_is_configured
    from app.agent.providers.catalog import all_providers

    for entry in all_providers():
        if entry["id"] != provider or not _provider_is_configured(entry):
            continue
        visible = set(provider_visible_models(provider))
        if visible and model not in visible:
            return False
        discovered = await _discover_configured_registry_models()
        return any(p == provider and m == model for p, m in discovered)
    return False


@router.patch("/model")
async def bulk_update_model(body: AgentBulkModelRequest) -> AgentBulkModelResponse:
    """Set ``model:`` on many agent files in one round trip.

    Each agent is patched and validated independently — one bad file
    doesn't block the rest. A model-field edit can't violate the
    "exactly one lead" invariant, so this skips the whole-team-reload
    rollback ``update_agent`` uses and just restores that single file's
    previous content on failure.
    """
    import yaml

    from app.agent.config import _FRONTMATTER_RE

    results: list[AgentBulkModelResult] = []
    for name in body.names:
        provider = managed_resource_provider("agent", name)
        if provider is not None:
            results.append(
                AgentBulkModelResult(
                    name=name,
                    ok=False,
                    error=(
                        f"Agent '{name}' is managed by Conductor project "
                        f"'{provider.project_name}'."
                    ),
                )
            )
            continue
        try:
            previous = agent_fs.read_agent(name)
        except (AgentFsNotFoundError, AgentFsPathError) as exc:
            results.append(AgentBulkModelResult(name=name, ok=False, error=str(exc)))
            continue

        m = _FRONTMATTER_RE.match(previous.content)
        if not m:
            results.append(
                AgentBulkModelResult(
                    name=name, ok=False, error="Missing YAML frontmatter."
                )
            )
            continue

        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as exc:
            results.append(
                AgentBulkModelResult(
                    name=name, ok=False, error=f"Invalid YAML frontmatter: {exc}"
                )
            )
            continue
        if not isinstance(meta, dict):
            results.append(
                AgentBulkModelResult(
                    name=name, ok=False, error="Frontmatter must be a YAML mapping."
                )
            )
            continue

        meta["model"] = body.model
        new_content = (
            f"---\n{yaml.safe_dump(meta, sort_keys=False).strip()}\n---\n{m.group(2)}"
        )

        try:
            _parse_content(name, new_content)
        except ValueError as exc:
            results.append(AgentBulkModelResult(name=name, ok=False, error=str(exc)))
            continue

        try:
            agent_fs.write_agent(name, new_content, create=False)
        except AgentFsPathError as exc:
            results.append(AgentBulkModelResult(name=name, ok=False, error=str(exc)))
            continue

        results.append(AgentBulkModelResult(name=name, ok=True))

    return AgentBulkModelResponse(results=results)


@router.patch("/runtime-model/{name:path}")
async def update_agent_runtime_model(
    name: str, body: AgentRuntimeModelRequest
) -> AgentDetail:
    """Set or reset one installation's model for a managed Agent."""

    try:
        agent_fs.read_agent(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    provider = managed_resource_provider("agent", name)
    if provider is None:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{name}' is not managed by Conductor.",
        )
    if body.model is not None and not await is_registered_model_id(body.model):
        raise HTTPException(
            status_code=422,
            detail=f"Model '{body.model}' is not configured or selectable.",
        )
    try:
        if body.model is None:
            delete_agent_runtime_model(
                project_id=provider.project_id,
                resource_id=provider.resource_id,
            )
        else:
            write_agent_runtime_model(
                project_id=provider.project_id,
                resource_id=provider.resource_id,
                name=name,
                model=body.model,
            )
    except AgentSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _read_agent_detail(name, provider=provider)


@router.patch("/runtime-settings/{name:path}")
async def update_agent_runtime_settings(
    name: str, body: AgentRuntimeSettingsRequest
) -> AgentDetail:
    """Persist the installation-owned additive layer for a managed Agent."""

    try:
        agent_fs.read_agent(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    provider = managed_resource_provider("agent", name)
    if provider is None:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{name}' is not managed by Conductor.",
        )
    if body.model is not None and not await is_registered_model_id(body.model):
        raise HTTPException(
            status_code=422,
            detail=f"Model '{body.model}' is not configured or selectable.",
        )
    registry = await get_registry(workspace=None, mode=_mode_for_agent_path(name))
    known_tools = {item.name for item in registry.tools}
    known_skills = {item.name for item in registry.skills}
    unknown_tools = sorted(set(body.extra_tools) - known_tools)
    unknown_skills = sorted(set(body.extra_skills) - known_skills)
    if unknown_tools or unknown_skills:
        detail = []
        if unknown_tools:
            detail.append(f"unknown tools: {', '.join(unknown_tools)}")
        if unknown_skills:
            detail.append(f"unknown skills: {', '.join(unknown_skills)}")
        raise HTTPException(status_code=422, detail="; ".join(detail))
    try:
        write_agent_runtime_settings(
            project_id=provider.project_id,
            resource_id=provider.resource_id,
            name=name,
            model=body.model,
            extra_tools=body.extra_tools,
            extra_skills=body.extra_skills,
            extra_mcp=body.extra_mcp,
        )
    except AgentSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _read_agent_detail(name, provider=provider)


def _read_agent_detail(
    name: str, *, provider: ManagedResourceProvider | None = None
) -> AgentDetail:
    """Read one Agent and expose its effective runtime model metadata."""

    try:
        record = agent_fs.read_agent(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    owner = (
        provider if provider is not None else managed_resource_provider("agent", name)
    )
    config: dict[str, Any] | None = None
    bundle_model: str | None = None
    error: str | None = None
    try:
        cfg = _parse_content(name, record.content)
        bundle_model = cfg.model if owner is not None else None
        config = _effective_config(
            cfg,
            mode=_mode_for_agent_path(name),
            provider=owner,
        ).model_dump(exclude_none=True)
    except ValueError as exc:
        error = str(exc)

    additions = _runtime_additions(owner)
    return AgentDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        config=config,
        error=error,
        editable=owner is None,
        provider=owner,
        runtime_model_editable=owner is not None,
        bundle_model=bundle_model,
        model_override=agent_model_override(owner) if owner is not None else None,
        extra_tools=additions["extra_tools"],
        extra_skills=additions["extra_skills"],
        extra_mcp=additions["extra_mcp"],
    )


@router.get("/{name}")
@router.get("/{name:path}")
async def get_agent(name: str) -> AgentDetail:
    return _read_agent_detail(name)


@router.post("", status_code=201)
async def create_agent(body: AgentWriteRequest) -> AgentDetail:
    try:
        cfg = _parse_content(body.name, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    expected_name = _frontmatter_name_for_path(body.name)
    if cfg.name != expected_name:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Frontmatter name '{cfg.name}' must match the request name "
                f"'{expected_name}'."
            ),
        )

    try:
        record = agent_fs.write_agent(body.name, body.content, create=True)
    except AgentFsConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _validate_or_restore(rollback_name=body.name, rollback_content=None)

    return AgentDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        config=cfg.model_dump(exclude_none=True),
    )


@router.put("/{name}")
@router.put("/{name:path}")
async def update_agent(name: str, body: AgentWriteRequest) -> AgentDetail:
    if body.name != name:
        raise HTTPException(
            status_code=422,
            detail=f"URL name '{name}' does not match body name '{body.name}'.",
        )

    provider = managed_resource_provider("agent", name)
    if provider is not None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{name}' is managed by Conductor project "
                f"'{provider.project_name}' and cannot be edited locally."
            ),
        )

    try:
        previous = agent_fs.read_agent(name)
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        cfg = _parse_content(name, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _require_frontmatter_name(name, body.content)

    try:
        record = agent_fs.write_agent(name, body.content, create=False)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _validate_or_restore(rollback_name=name, rollback_content=previous.content)

    return AgentDetail(
        name=record.name,
        path=record.path,
        content=record.content,
        config=cfg.model_dump(exclude_none=True),
    )


@router.delete("/{name}")
@router.delete("/{name:path}")
async def delete_agent(name: str) -> AgentDeleteResponse:
    """422 if removal would leave the team without a lead."""
    provider = managed_resource_provider("agent", name)
    if provider is not None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{name}' is managed by Conductor project "
                f"'{provider.project_name}' and cannot be deleted locally."
            ),
        )
    try:
        previous = agent_fs.read_agent(name)
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        agent_fs.delete_agent(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _validate_or_restore(rollback_name=name, rollback_content=previous.content)
    return AgentDeleteResponse(name=name)
