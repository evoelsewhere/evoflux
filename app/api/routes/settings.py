"""Generic ``/api/settings`` endpoints.

Exposes the user-editable sandbox deny-list and the provider catalog.
"""

from __future__ import annotations

import asyncio
import json
import re
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from loguru import logger

from app.agent.sandbox_config import SandboxFileConfig, load_config, save_config
from app.core.config import settings
from app.core.runtime_settings import (
    BuiltInBrowserSettings,
    CodeReviewSettings,
    ConductorSettings,
    ContextSettings,
    GitSettings,
    WebBridgeSettings,
    load_runtime_settings,
    load_runtime_settings_report,
    provider_visible_models,
    save_runtime_settings,
    set_provider_visible_models,
)

if TYPE_CHECKING:
    from app.agent.providers.catalog import ProviderEntry
from app.api.schemas.settings import (
    ConductorEnrollmentRequest,
    ConductorSettingsBody,
    ContextSettingsBody,
    IgnoredSettingBody,
    ProviderInfo,
    ProviderModelsRequest,
    ProviderModelDetail,
    ProviderModelsResponse,
    ProviderSaveRequest,
    ProviderSaveResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderUsageResponse,
    ProviderVisibleModelsRequest,
    ProviderVisibleModelsResponse,
    ProvidersListBody,
    SandboxSettingsBody,
    SeedInstallRequest,
    SeedInstallResponse,
    VersionControlSettingsBody,
    WebBridgeSettingsBody,
)
from app.services.provider_usage import (
    ProviderUsageCredentialsError,
    ProviderUsageUnavailableError,
    ProviderUsageUnsupportedError,
    get_provider_usage as load_provider_usage,
)

router = APIRouter()

# Serialises concurrent provider tests. ``build_provider`` reads credentials
# from ``os.environ`` deep in the factory; the test endpoint has to mutate
# it temporarily, so a lock prevents two in-flight tests from clobbering
# each other's keys.
_TEST_PROVIDER_LOCK = asyncio.Lock()

# Per-provider reachability cache (provider_id → (monotonic_ts, reachable)).
# Local-daemon providers (Ollama, 9Router, CLIProxyAPI) need an actual ping
# — without it every install would falsely show "Connected" just because
# the env var was set or the catalog row exists. We cache the result
# briefly so listing providers doesn't fan out probes on every render.
_LOCAL_REACHABLE_TTL_S = 10.0
_LOCAL_REACHABLE_TIMEOUT_S = 1.0
_local_reachable_cache: dict[str, tuple[float, bool]] = {}

# Providers that run as a local-ish daemon — even when authed by API key,
# "Connected" should mean the daemon actually responds.
_DAEMON_PROVIDER_IDS = frozenset({"ollama", "router9", "cliproxy"})


def _conductor_settings_body() -> ConductorSettingsBody:
    cfg = load_runtime_settings().conductor
    return ConductorSettingsBody(
        enabled=cfg.enabled,
        url=cfg.url,
        machine_credential_path=cfg.machine_credential_path,
        sync_interval_seconds=cfg.sync_interval_seconds,
        heartbeat_interval_seconds=cfg.heartbeat_interval_seconds,
        request_timeout_seconds=cfg.request_timeout_seconds,
        enforcement_mode=cfg.enforcement_mode,
    )


@router.get("/conductor")
async def get_conductor_settings() -> ConductorSettingsBody:
    return _conductor_settings_body()


@router.put("/conductor")
async def update_conductor_settings(
    body: ConductorSettingsBody,
) -> ConductorSettingsBody:
    cfg = load_runtime_settings()
    from app.conductor import conductor_service

    previous = cfg.conductor
    if previous.url and previous.url != body.url.strip().rstrip("/"):
        await conductor_service.disconnect()
        cfg = load_runtime_settings()
        previous = cfg.conductor
    cfg.conductor = ConductorSettings.model_validate(
        {**previous.model_dump(mode="python"), **body.model_dump(mode="python")}
    )
    save_runtime_settings(cfg)
    await conductor_service.restart()
    return _conductor_settings_body()


@router.post("/conductor/enroll", include_in_schema=False)
@router.post("/conductor/connect")
async def connect_conductor(body: ConductorEnrollmentRequest) -> dict:
    from app.conductor import conductor_service
    from app.conductor.client import ConductorRequestError, CredentialStoreError

    try:
        status = await conductor_service.connect(body.enrollment_token)
    except ConductorRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return status.model_dump(mode="json")


@router.post("/conductor/disconnect")
async def disconnect_conductor() -> dict:
    from app.conductor import conductor_service
    from app.conductor.client import CredentialStoreError

    try:
        status = await conductor_service.disconnect()
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return status.model_dump(mode="json")


@router.post("/conductor/sync")
async def sync_conductor() -> dict:
    from app.conductor import conductor_service

    try:
        status = await conductor_service.sync_now()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return status.model_dump(mode="json")


@router.get("/conductor/status")
async def get_conductor_status() -> dict:
    from app.conductor import conductor_service

    return conductor_service.status_payload()


@router.post("/conductor/resources/{resource_id}/approve")
async def approve_conductor_resource(resource_id: str) -> dict:
    from app.conductor import conductor_service

    try:
        return conductor_service.approve_governed_plugin(resource_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Managed Plugin is not waiting for trust approval."
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/conductor/resources/{resource_id}/pull")
async def pull_conductor_resource(resource_id: str) -> dict:
    from app.conductor import conductor_service
    from app.conductor.client import ConductorRequestError

    try:
        return await conductor_service.pull_governed_resource(resource_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Managed resource is not available to pull."
        ) from exc
    except ConductorRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Live-discovered provider models cached per provider so ``GET /providers``
# doesn't fan out to every configured backend on each render (mirrors
# ``_registry_model_cache`` in app/api/routes/agents.py). Only successful
# (non-empty) saved-credential discoveries are cached — failures stay live
# so a just-fixed key shows as connected immediately, and per-request
# credential overrides (POST /providers/{id}/models) never hit this cache.
_PROVIDER_MODEL_CACHE_TTL_S = 60.0
_provider_model_cache: dict[str, tuple[float, list[str]]] = {}

#: Manual (``auto_connect=False``) providers are connected by an explicit
#: "list models" request, never by a background poll, so their model list
#: has no other source to fall back on. Keeping it in memory alone meant a
#: daemon restart silently un-listed every catalog provider — the picker
#: lost the models and any session already pinned to one was refused with
#: "Choose a model from the registry". These ids are mirrored to disk.
_manual_model_ids: set[str] = set()
_manual_cache_loaded_from: str | None = None


def _manual_models_persist(entry: "ProviderEntry") -> bool:
    """Whether this provider's manual model list survives a restart.

    A remote catalog provider's list is a fact about its API and stays
    true, so re-listing after every restart is pure friction. A local
    daemon's is a fact about a process that may since have stopped, and
    Ollama deliberately stays disconnected until the user asks — so it
    keeps its in-memory-only cache.
    """
    return not entry.get("auto_connect", True) and entry.get("kind") != "local"


def _manual_model_cache_path() -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR or "") / "provider-models.json"


def _load_manual_model_cache() -> None:
    """Seed the in-memory cache from disk once per cache directory."""
    global _manual_cache_loaded_from

    path = _manual_model_cache_path()
    if _manual_cache_loaded_from == str(path):
        return
    _manual_cache_loaded_from = str(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    now = time.monotonic()
    for provider_id, models in raw.items():
        if not isinstance(provider_id, str) or not isinstance(models, list):
            continue
        cleaned = [m for m in models if isinstance(m, str) and m]
        if not cleaned or provider_id in _provider_model_cache:
            continue
        _provider_model_cache[provider_id] = (now, cleaned)
        _manual_model_ids.add(provider_id)


def _save_manual_model_cache() -> None:
    """Mirror the manual providers' model lists to disk. Best-effort."""
    payload = {
        provider_id: cached[1]
        for provider_id in sorted(_manual_model_ids)
        if (cached := _provider_model_cache.get(provider_id))
    }
    path = _manual_model_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("manual_model_cache_write_failed path={} error={}", path, exc)


def _cached_provider_models(entry: "ProviderEntry") -> list[str] | None:
    """Return reusable discovered models without contacting the provider."""
    if _manual_models_persist(entry):
        _load_manual_model_cache()
    cached = _provider_model_cache.get(entry["id"])
    if cached is None:
        return None
    if entry.get("auto_connect", True):
        age = time.monotonic() - cached[0]
        if age >= _PROVIDER_MODEL_CACHE_TTL_S:
            return None
    return list(cached[1])


def _cache_provider_models(entry: "ProviderEntry", models: list[str]) -> None:
    """Remember successful discovery, or clear failed manual connections."""
    if models:
        _provider_model_cache[entry["id"]] = (time.monotonic(), list(models))
    elif not entry.get("auto_connect", True):
        _provider_model_cache.pop(entry["id"], None)
    if _manual_models_persist(entry):
        _load_manual_model_cache()
        if models:
            _manual_model_ids.add(entry["id"])
        else:
            _manual_model_ids.discard(entry["id"])
        _save_manual_model_cache()


def _manual_provider_is_connected(entry: "ProviderEntry") -> bool:
    """Whether a manual provider is usable, not merely once reachable.

    Listing a catalog provider's models proves the endpoint answered the
    key typed into the form — which is not the same as that key having
    been *saved*. Requiring both keeps "connected" honest: a listed but
    unsaved provider used to show as configured and offer its models to
    the picker, and every turn using one was then refused because the
    credential the request needed was never on disk.
    """
    return _provider_is_configured(entry) and bool(_cached_provider_models(entry))


@router.get("/sandbox")
async def get_sandbox_settings() -> SandboxSettingsBody:
    """Return the current sandbox deny-list.

    On first run this seeds ``sandbox.yaml`` with sensible defaults
    (``**/.env``, ``**/.env.*``).
    """
    try:
        cfg = load_config()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SandboxSettingsBody(
        denied_patterns=list(cfg.denied_patterns),
        worktree_location=cfg.worktree_location,
        inherit_shell_environment=cfg.inherit_shell_environment,
        load_shell_profile=cfg.load_shell_profile,
        outbound_data_policy=cfg.outbound_data_policy,
        outbound_pii_policy=cfg.outbound_pii_policy,
        max_execution_seconds=cfg.max_execution_seconds,
        max_output_bytes=cfg.max_output_bytes,
    )


@router.put("/sandbox")
async def update_sandbox_settings(body: SandboxSettingsBody) -> SandboxSettingsBody:
    """Replace the sandbox deny-list with the supplied glob patterns."""
    cleaned = [p.strip() for p in body.denied_patterns if p.strip()]
    save_config(
        SandboxFileConfig(
            denied_patterns=cleaned,
            worktree_location=body.worktree_location,
            inherit_shell_environment=body.inherit_shell_environment,
            load_shell_profile=body.load_shell_profile,
            outbound_data_policy=body.outbound_data_policy,
            outbound_pii_policy=body.outbound_pii_policy,
            max_execution_seconds=body.max_execution_seconds,
            max_output_bytes=body.max_output_bytes,
        )
    )
    return SandboxSettingsBody(
        denied_patterns=cleaned,
        worktree_location=body.worktree_location,
        inherit_shell_environment=body.inherit_shell_environment,
        load_shell_profile=body.load_shell_profile,
        outbound_data_policy=body.outbound_data_policy,
        outbound_pii_policy=body.outbound_pii_policy,
        max_execution_seconds=body.max_execution_seconds,
        max_output_bytes=body.max_output_bytes,
    )


# ── Providers (Settings → Providers tab) ────────────────────────────────────


# Version control (Settings -> Git & reviews tab)


def _version_control_settings_body() -> VersionControlSettingsBody:
    cfg = load_runtime_settings()
    return VersionControlSettingsBody(
        network_timeout_seconds=cfg.git.network_timeout_seconds,
        max_diff_bytes=cfg.git.max_diff_bytes,
        default_pull_strategy=cfg.git.default_pull_strategy,
        prune_on_fetch=cfg.git.prune_on_fetch,
        allow_force_push=cfg.git.allow_force_push,
        review_request_timeout_seconds=cfg.code_reviews.request_timeout_seconds,
        review_retry_attempts=cfg.code_reviews.retry_attempts,
        review_retry_backoff_seconds=cfg.code_reviews.retry_backoff_seconds,
        review_max_concurrent_repositories=(
            cfg.code_reviews.max_concurrent_repositories
        ),
        review_max_pages_per_repository=cfg.code_reviews.max_pages_per_repository,
        allow_review_mutations=cfg.code_reviews.allow_mutations,
        allow_insecure_connections=cfg.code_reviews.allow_insecure_connections,
        require_successful_checks_before_merge=(
            cfg.code_reviews.require_successful_checks_before_merge
        ),
    )


def _context_settings_body() -> ContextSettingsBody:
    from app.agent.hooks.summarization import (
        CODING_KEEP_LAST_ASSISTANTS,
        DEFAULT_KEEP_LAST_ASSISTANTS,
        DEFAULT_MAX_TOKEN_LENGTH,
        MAX_PROMPT_TOKEN_THRESHOLD,
        PROMPT_TOKEN_THRESHOLD_CONTEXT_RATIO,
        cost_optimal_prompt_token_threshold,
    )
    from app.agent.hooks.tool_context_projection import (
        CODING_KEEP_RECENT_BATCHES,
        DEFAULT_KEEP_RECENT_BATCHES,
    )
    from app.agent.hooks.tool_result_offload import DEFAULT_CHAR_THRESHOLD

    loaded, ignored = load_runtime_settings_report()
    ctx = loaded.context
    return ContextSettingsBody(
        summary_trigger_tokens=ctx.summary_trigger_tokens,
        summary_max_tokens=ctx.summary_max_tokens,
        keep_recent_turns=ctx.keep_recent_turns,
        tool_result_offload_chars=ctx.tool_result_offload_chars,
        keep_recent_tool_batches=ctx.keep_recent_tool_batches,
        defaults={
            "summary_trigger_tokens": cost_optimal_prompt_token_threshold(),
            "summary_max_tokens": DEFAULT_MAX_TOKEN_LENGTH,
            "keep_recent_turns": DEFAULT_KEEP_LAST_ASSISTANTS,
            "tool_result_offload_chars": DEFAULT_CHAR_THRESHOLD,
            "keep_recent_tool_batches": DEFAULT_KEEP_RECENT_BATCHES,
        },
        # Two of the built-ins are mode-aware. Reporting only Work's would
        # tell a Coding user their sessions keep 3 turns and 4 batches when
        # they keep 2 and 3 — so name the Coding value wherever it differs
        # and let the UI say so.
        coding_defaults={
            "keep_recent_turns": CODING_KEEP_LAST_ASSISTANTS,
            "keep_recent_tool_batches": CODING_KEEP_RECENT_BATCHES,
        },
        # Only this section's rejects: another section's bad value is that
        # page's business, not a warning to show here.
        ignored=[
            IgnoredSettingBody(
                field=item.field.removeprefix("context."), message=item.message
            )
            for item in ignored
            if item.field.startswith("context.")
        ],
        max_tokens=MAX_PROMPT_TOKEN_THRESHOLD,
        context_ratio=PROMPT_TOKEN_THRESHOLD_CONTEXT_RATIO,
    )


@router.get("/context")
async def get_context_settings() -> ContextSettingsBody:
    try:
        return _context_settings_body()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/context")
async def update_context_settings(body: ContextSettingsBody) -> ContextSettingsBody:
    """Replace the global context-window overrides.

    ``defaults`` and ``max_tokens`` are derived and ignored on write; they
    are echoed back so the response keeps one shape. Any field sent as
    ``null`` reverts to its built-in default.
    """
    try:
        cfg = load_runtime_settings()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cfg.context = ContextSettings(
        summary_trigger_tokens=body.summary_trigger_tokens,
        summary_max_tokens=body.summary_max_tokens,
        keep_recent_turns=body.keep_recent_turns,
        tool_result_offload_chars=body.tool_result_offload_chars,
        keep_recent_tool_batches=body.keep_recent_tool_batches,
    )
    save_runtime_settings(cfg)
    return _context_settings_body()


@router.get("/version-control")
async def get_version_control_settings() -> VersionControlSettingsBody:
    try:
        return _version_control_settings_body()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/version-control")
async def update_version_control_settings(
    body: VersionControlSettingsBody,
) -> VersionControlSettingsBody:
    try:
        cfg = load_runtime_settings()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cfg.git = GitSettings(
        network_timeout_seconds=body.network_timeout_seconds,
        max_diff_bytes=body.max_diff_bytes,
        default_pull_strategy=body.default_pull_strategy,
        prune_on_fetch=body.prune_on_fetch,
        allow_force_push=body.allow_force_push,
    )
    cfg.code_reviews = CodeReviewSettings(
        request_timeout_seconds=body.review_request_timeout_seconds,
        retry_attempts=body.review_retry_attempts,
        retry_backoff_seconds=body.review_retry_backoff_seconds,
        max_concurrent_repositories=body.review_max_concurrent_repositories,
        max_pages_per_repository=body.review_max_pages_per_repository,
        allow_mutations=body.allow_review_mutations,
        allow_insecure_connections=body.allow_insecure_connections,
        require_successful_checks_before_merge=(
            body.require_successful_checks_before_merge
        ),
    )
    save_runtime_settings(cfg)
    return _version_control_settings_body()


def _webbridge_settings_body() -> WebBridgeSettingsBody:
    cfg = load_runtime_settings()
    return WebBridgeSettingsBody(
        enabled=cfg.webbridge.enabled,
        allow_evaluate=cfg.webbridge.allow_evaluate,
        built_in_allowed_domains=cfg.browser.allowed_domains,
        built_in_blocked_domains=cfg.browser.blocked_domains,
        built_in_allow_evaluate=cfg.browser.allow_evaluate,
        built_in_allow_storage=cfg.browser.allow_storage,
        built_in_allow_cookie_values=cfg.browser.allow_cookie_values,
        built_in_allow_http_requests=cfg.browser.allow_http_requests,
        built_in_allow_clipboard_read=cfg.browser.allow_clipboard_read,
        built_in_allow_clipboard_write=cfg.browser.allow_clipboard_write,
        built_in_allow_file_uploads=cfg.browser.allow_file_uploads,
        built_in_allow_downloads=cfg.browser.allow_downloads,
        built_in_allow_agent_permission_accept=cfg.browser.allow_agent_permission_accept,
    )


@router.get("/webbridge")
async def get_webbridge_settings() -> WebBridgeSettingsBody:
    try:
        return _webbridge_settings_body()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/webbridge")
async def update_webbridge_settings(
    body: WebBridgeSettingsBody,
) -> WebBridgeSettingsBody:
    try:
        cfg = load_runtime_settings()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cfg.webbridge = WebBridgeSettings(
        enabled=body.enabled,
        allow_evaluate=body.allow_evaluate,
        allowed_domains=cfg.webbridge.allowed_domains,
        blocked_domains=cfg.webbridge.blocked_domains,
        audit_log_size=cfg.webbridge.audit_log_size,
        sharing=cfg.webbridge.sharing,
        interactions=cfg.webbridge.interactions,
    )
    cfg.browser = BuiltInBrowserSettings(
        allowed_domains=body.built_in_allowed_domains,
        blocked_domains=body.built_in_blocked_domains,
        allow_evaluate=body.built_in_allow_evaluate,
        allow_storage=body.built_in_allow_storage,
        allow_cookie_values=body.built_in_allow_cookie_values,
        allow_http_requests=body.built_in_allow_http_requests,
        allow_clipboard_read=body.built_in_allow_clipboard_read,
        allow_clipboard_write=body.built_in_allow_clipboard_write,
        allow_file_uploads=body.built_in_allow_file_uploads,
        allow_downloads=body.built_in_allow_downloads,
        allow_agent_permission_accept=body.built_in_allow_agent_permission_accept,
    )
    save_runtime_settings(cfg)
    # Keep the live policy cache in sync without waiting for the cleanup loop.
    from app.services.webbridge_service import webbridge_manager

    webbridge_manager.reload_policy()
    return _webbridge_settings_body()


# Providers (Settings -> Providers tab)


def _env_has_provider_key(env_file: "Path") -> bool:
    """Return True if ``.env`` already contains *any* known API-key env var.

    Used by ``save_provider`` to decide whether this save is the user's
    first credential and the frontend should kick off seed installation
    afterward. OAuth tokens (which live in CACHE_DIR, not .env) and the
    Ollama local default don't count — the seed installer needs a
    chat-capable provider:model string, which OAuth providers without a
    saved model don't yet have.
    """
    from app.agent.providers.catalog import PROVIDER_KEY_VAR

    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return False
    keys = {key for key in PROVIDER_KEY_VAR.values() if key}
    for line in text.splitlines():
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() in keys and value.strip():
            return True
    return False


def _provider_is_configured(entry: "ProviderEntry") -> bool:
    """Return True if the user's .env has credentials for this provider.

    Synchronous static check — does **not** probe daemons or networks.
    For ``kind="local"`` (Ollama) this returns optimistically; callers
    that care about actual reachability should use
    :func:`_provider_is_reachable` instead, which adds an async daemon
    ping on top of this.
    """
    kind = entry.get("kind")
    from app.agent.providers.plugin_registry import (
        ProviderCredentialStore,
        find_provider_plugin,
    )

    plugin = find_provider_plugin(entry["id"])
    if plugin is not None:
        store = ProviderCredentialStore(plugin.id)
        if plugin.is_configured is not None:
            return plugin.is_configured(store)
        return all(
            store.get(field.name) for field in plugin.credentials if field.required
        )
    if kind == "local":
        return True
    if kind == "oauth":
        if entry["id"] == "copilot":
            # Accept env-token fallback when OAuth cache is missing.
            if any(
                os.environ.get(k)
                for k in (
                    "COPILOT_GITHUB_TOKEN",
                    "GH_TOKEN",
                    "GITHUB_TOKEN",
                    "GITHUB_COPILOT_TOKEN",
                )
            ):
                return True
        cache_dir = Path(settings.EVOFLUX_CACHE_DIR or "")
        token_files = {
            "codex": cache_dir / "codex_oauth.json",
            "copilot": cache_dir / "copilot_oauth.json",
        }
        token_file = token_files.get(entry["id"])
        return bool(token_file and token_file.is_file())
    if kind == "cloud_creds":
        if entry["id"] == "foundry":
            # The generic env_vars check below only reads os.environ, which
            # loses saved credentials after a daemon restart — the store
            # also consults the saved .env file.
            store = ProviderCredentialStore(entry["id"])
            return bool(
                store.get("FOUNDRY_API_KEY") and store.get("FOUNDRY_RESOURCE_NAME")
            )
        if entry["id"] == "bedrock":
            store = ProviderCredentialStore(entry["id"])
            profile = os.environ.get("AWS_BEDROCK_PROFILE") or store.get(
                "AWS_BEDROCK_PROFILE"
            )
            access_key = os.environ.get("AWS_ACCESS_KEY_ID") or store.get(
                "AWS_ACCESS_KEY_ID"
            )
            secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or store.get(
                "AWS_SECRET_ACCESS_KEY"
            )
            return bool(profile or (access_key and secret_key))
        # Vertex AI: need project + location *and* gcloud ADC. We can't
        # check gcloud from here without shelling out, so the UI's
        # "Test connection" button is the source of truth.
        names = entry.get("env_vars") or []
        return all(os.environ.get(name) for name in names)
    # api_key
    env_var = entry.get("env_var") or ""
    if not env_var:
        return False
    # Check both os.environ (mutated by recent saves) and settings
    # (loaded once at startup) and the user's config .env (loaded by the
    # credential store) so saved keys survive daemon restarts.
    store = ProviderCredentialStore(entry["id"])
    return bool(store.get(env_var))


def _provider_saved_overrides(entry: "ProviderEntry") -> dict[str, str]:
    """Return saved credential values for provider model discovery."""
    from app.agent.providers.plugin_registry import ProviderCredentialStore

    store = ProviderCredentialStore(entry["id"])
    names: set[str] = set()
    if entry.get("env_var"):
        names.add(str(entry["env_var"]))
    names.update(str(name) for name in entry.get("env_vars") or [])
    for field in entry.get("credentials") or []:
        name = str(field.get("name", ""))
        if name:
            names.add(name)
    names.update({"OLLAMA_BASE_URL", "ROUTER9_BASE_URL", "CLIPROXY_BASE_URL"})
    return {name: value for name in names if (value := store.get(name))}


def _provider_saved_display_credentials(entry: "ProviderEntry") -> dict[str, str]:
    """Return saved non-secret credential values that are safe to echo to the UI."""
    saved = _provider_saved_overrides(entry)
    visible_names = {
        str(field.get("name", ""))
        for field in entry.get("credentials") or []
        if field.get("name") and not field.get("secret")
    }
    return {name: value for name, value in saved.items() if name in visible_names}


def _daemon_base_url(provider_id: str) -> str:
    """Resolve the daemon base URL for a local/local-proxy provider."""
    if provider_id == "ollama":
        return os.getenv("OLLAMA_BASE_URL") or settings.OLLAMA_BASE_URL or ""
    if provider_id == "router9":
        return os.getenv("ROUTER9_BASE_URL") or settings.ROUTER9_BASE_URL or ""
    if provider_id == "cliproxy":
        return os.getenv("CLIPROXY_BASE_URL") or settings.CLIPROXY_BASE_URL or ""
    return ""


async def _local_provider_reachable(entry: "ProviderEntry") -> bool:
    """Short-timeout daemon probe for local-daemon providers.

    Returns True only if the daemon actually responds. Cached per-provider
    for :data:`_LOCAL_REACHABLE_TTL_S` seconds so listing the providers
    page doesn't fan out one HTTP request per render.

    On any error (connection refused, timeout, DNS failure) returns
    False — we'd rather show "not connected" than a false positive.
    """
    provider_id = entry["id"]
    now = time.monotonic()
    cached = _local_reachable_cache.get(provider_id)
    if cached and now - cached[0] < _LOCAL_REACHABLE_TTL_S:
        return cached[1]

    base_url = _daemon_base_url(provider_id)
    reachable = False
    if base_url:
        try:
            async with httpx.AsyncClient(timeout=_LOCAL_REACHABLE_TIMEOUT_S) as client:
                response = await client.get(f"{base_url.rstrip('/')}/models")
                reachable = response.status_code < 500
        except Exception as exc:
            logger.debug(
                "local_provider_unreachable provider={} url={} error={}",
                provider_id,
                base_url,
                exc,
            )
            reachable = False

    _local_reachable_cache[provider_id] = (now, reachable)
    return reachable


async def _empty_models() -> list[str]:
    return []


async def _provider_is_reachable(entry: "ProviderEntry") -> bool:
    """Configuration check including a daemon probe for daemon providers.

    Ollama is never contacted here because it requires an explicit user
    action. For 9Router / CLIProxyAPI we require the daemon to respond on
    its base URL; other providers use the static configuration check.
    """
    provider_id = entry["id"]
    if not entry.get("auto_connect", True):
        return _manual_provider_is_connected(entry)
    if provider_id in _DAEMON_PROVIDER_IDS:
        # For api_key daemon providers (router9, cliproxy) the static
        # check additionally requires the env var. No env var → don't
        # bother probing.
        if entry.get("kind") == "api_key" and not _provider_is_configured(entry):
            return False
        return await _local_provider_reachable(entry)
    return _provider_is_configured(entry)


@router.get("/providers")
async def list_providers() -> ProvidersListBody:
    """Return the provider catalog enriched with per-provider configuration state.

    ``is_configured`` reflects *actual* availability: API keys present,
    OAuth token files on disk, cloud creds set, and reachable local proxy
    daemons. Ollama remains disconnected until the user explicitly lists
    its models, so this endpoint never contacts the local Ollama daemon.
    """
    from app.agent.providers.catalog import all_providers
    from app.agent.providers.model_discovery import filter_agent_model_ids
    from app.agent.providers.model_registry import provider_model_counts
    from app.agent.providers.registry import is_recommended, provider_rank

    entries = all_providers()
    counts = provider_model_counts()
    saved_states = [
        _provider_is_configured(entry)
        if entry.get("auto_connect", True)
        else _manual_provider_is_connected(entry)
        for entry in entries
    ]
    reachability = await asyncio.gather(
        *(_provider_is_reachable(entry) for entry in entries),
        return_exceptions=False,
    )
    from app.agent.providers.model_discovery import discover_provider_models

    now = time.monotonic()

    async def _discover_cached(entry: "ProviderEntry") -> list[str]:
        cached = _cached_provider_models(entry)
        if cached is not None:
            return cached
        if not entry.get("auto_connect", True):
            return []
        models = await discover_provider_models(
            entry, overrides=_provider_saved_overrides(entry)
        )
        if models:
            _provider_model_cache[entry["id"]] = (now, models)
        return models

    discovery_results = await asyncio.gather(
        *(
            _discover_cached(entry) if is_configured else _empty_models()
            for entry, is_configured in zip(entries, reachability, strict=True)
        ),
        return_exceptions=False,
    )

    out: list[ProviderInfo] = []
    for entry, is_saved, is_configured, live_models in zip(
        entries, saved_states, reachability, discovery_results, strict=True
    ):
        out.append(
            ProviderInfo(
                id=entry["id"],
                label=entry["label"],
                description=entry.get("description", ""),
                kind=entry["kind"],
                credentials=list(entry.get("credentials", [])),
                saved_credentials=_provider_saved_display_credentials(entry),
                env_var=entry.get("env_var", ""),
                env_vars=list(entry.get("env_vars", [])),
                fallback_models=filter_agent_model_ids(
                    entry["id"], list(entry.get("fallback_models", []))
                ),
                oauth_command=entry.get("oauth_command", ""),
                docs_url=entry.get("docs_url", ""),
                browser_login=bool(entry.get("browser_login", False)),
                is_configured=is_configured and bool(live_models),
                is_saved=is_saved,
                is_reachable=bool(live_models) if is_configured else None,
                visible_models=provider_visible_models(entry["id"]),
                source=entry.get("source", "builtin"),
                transport=entry.get("transport", ""),
                model_count=counts.get(entry["id"], (0, 0))[0],
                free_model_count=counts.get(entry["id"], (0, 0))[1],
                recommended=is_recommended(entry["id"]),
                rank=provider_rank(entry["id"]),
            )
        )
    has_any = any(p.is_configured for p in out)
    return ProvidersListBody(providers=out, has_any_configured=has_any)


def _build_overrides(
    entry: "ProviderEntry", body_api_key: str, body_extra: dict[str, str]
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    credentials = entry.get("credentials") or []
    if body_api_key and entry.get("env_var"):
        overrides[entry["env_var"]] = body_api_key
    elif body_api_key and credentials:
        name = str(credentials[0].get("name", ""))
        if name:
            overrides[name] = body_api_key
    # Blank form fields are not candidate credentials — the UI echoes
    # non-secret values but leaves saved secrets empty, and an empty
    # override must not clobber the saved value during discovery.
    overrides.update({name: value for name, value in body_extra.items() if value})
    return overrides


def _model_cost_map(model_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per-model pricing in USD per 1M tokens, for the models we know rates for.

    Lets the Settings model listing show pricing next to each model without
    an extra round-trip. Models with no known input *and* no known output
    rate are omitted so the UI can tell "free" apart from "unknown".
    """
    from app.agent.providers.model_metadata import get_model_cost

    costs: dict[str, dict[str, Any]] = {}
    for model_id in model_ids:
        cost = get_model_cost(model_id)
        if cost.input is None and cost.output is None:
            continue
        costs[model_id] = {k: v for k, v in cost.to_dict().items() if v is not None}
    return costs


def _model_detail_map(
    provider_id: str, model_ids: list[str]
) -> dict[str, "ProviderModelDetail"]:
    """Catalog detail per listed model, for the settings model list.

    The list used to show a bare ``provider:model`` string per row, which
    told a reader nothing they did not already type. The catalog carries a
    name, a description, a context window and capability flags for most
    models, and this is what puts them on the row.
    """
    from app.agent.providers.capabilities import get_capabilities
    from app.agent.providers.model_metadata import (
        get_model_metadata,
        qualified_model_id,
    )
    from app.agent.providers.thinking import offered_levels_for

    details: dict[str, ProviderModelDetail] = {}
    for model_id in model_ids:
        qualified = qualified_model_id(provider_id, model_id)
        metadata = get_model_metadata(qualified)
        features = metadata.features
        cost = metadata.cost
        detail = ProviderModelDetail(
            name=features.name,
            description=features.description,
            family=features.family,
            status=features.status,
            release_date=features.release_date,
            knowledge=features.knowledge,
            context_length=metadata.limits.context_length,
            max_output_tokens=metadata.limits.max_completion_tokens,
            free=(
                cost.input == 0 and cost.output == 0
                if cost.input is not None and cost.output is not None
                else None
            ),
            vision=get_capabilities(qualified).input.vision,
            tool_call=features.tool_call,
            attachment=features.attachment,
            thinking_levels=list(offered_levels_for(qualified)),
        )
        # A row with nothing to add stays out of the payload rather than
        # shipping a wall of nulls for every model.
        if detail != ProviderModelDetail(vision=detail.vision) or detail.vision:
            details[model_id] = detail
    return details


@router.post("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: str, body: ProviderModelsRequest
) -> ProviderModelsResponse:
    """Return live provider models, or an empty list when discovery fails.

    Per-request credentials in ``body`` are threaded through to
    :func:`discover_provider_models` via the ``overrides`` parameter — we
    never touch ``os.environ`` because a concurrent request would observe
    the leaked value.
    """
    from app.agent.providers.catalog import find
    from app.agent.providers.model_discovery import (
        discover_provider_models,
        filter_agent_model_ids,
    )

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    overrides = _provider_saved_overrides(entry) | _build_overrides(
        entry, body.api_key, body.extra
    )
    discovered = filter_agent_model_ids(
        provider_id,
        await discover_provider_models(entry, overrides=overrides),
    )
    if not entry.get("auto_connect", True):
        _cache_provider_models(entry, discovered)
    if discovered:
        return ProviderModelsResponse(
            provider=provider_id,
            models=discovered,
            source="provider",
            model_costs=_model_cost_map(discovered),
            model_details=_model_detail_map(provider_id, discovered),
        )
    return ProviderModelsResponse(provider=provider_id, models=[], source="provider")


#: Where models.dev serves provider logos. Every provider in the catalog has
#: one, drawn with ``fill="currentColor"`` so it inherits the UI's text
#: colour in either theme.
_LOGO_URL = "https://models.dev/logos/{provider_id}.svg"

#: Markup an SVG has no business carrying. The renderer loads these through
#: ``<img>``, where scripts do not execute, but a cached file is also written
#: to disk and served back by this API — so anything active is rejected at
#: the door rather than trusted to a downstream sandbox.
_SVG_FORBIDDEN = ("<script", "javascript:", "<foreignobject", "onload=", "onerror=")

_LOGO_MAX_BYTES = 256 * 1024


def _logo_cache_path(provider_id: str) -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR) / "provider-logos" / f"{provider_id}.svg"


def _logo_source_id(provider_id: str) -> str | None:
    """The models.dev ID whose logo represents *provider_id*.

    A curated provider borrows the logo of the catalog row it reads — Codex
    shows OpenAI's mark, Vertex shows Google's — because that is whose API
    it is. Returns ``None`` for an ID no provider claims, which is what
    stops this endpoint being a fetch-anything proxy.
    """
    from app.agent.providers.model_registry import models_dev_provider_entry
    from app.agent.providers.registry import resolve_provider

    normalized = (provider_id or "").strip().lower()
    if not normalized or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", normalized):
        return None
    # The registry's catalog ID is the right source here even where the
    # model registry deliberately does not follow it: Codex reads OpenAI's
    # rows without taking them over, but it is still OpenAI's API and so
    # OpenAI's mark.
    config = resolve_provider(normalized)
    source = config.models_dev_provider_id if config else normalized
    if models_dev_provider_entry(source) is None:
        return None
    return source


def _read_cached_logo(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except (FileNotFoundError, OSError):
        return None


async def _fetch_logo(source_id: str) -> bytes | None:
    """Fetch one provider logo, refusing anything that is not a plain SVG."""
    url = _LOGO_URL.format(provider_id=source_id)
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "EvoFlux"})
    except httpx.HTTPError as exc:
        logger.debug("provider_logo_fetch_failed provider={} error={}", source_id, exc)
        return None
    if response.status_code != 200:
        return None
    if "svg" not in response.headers.get("content-type", "").lower():
        return None
    payload = response.content
    if not payload or len(payload) > _LOGO_MAX_BYTES:
        return None
    lowered = payload[:4096].lower()
    if any(marker.encode() in lowered for marker in _SVG_FORBIDDEN):
        logger.warning(
            "provider_logo_rejected provider={} reason=active-svg", source_id
        )
        return None
    return payload


#: A colour the caller may ask a logo to be tinted. Kept to hex so the value
#: can never smuggle CSS into the SVG it is substituted into.
_LOGO_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _tint_logo(payload: bytes, color: str | None) -> bytes:
    """Resolve a logo's ``currentColor`` to an explicit colour.

    Nearly every mark models.dev publishes is drawn with
    ``fill="currentColor"``, which is exactly right for an inlined SVG: it
    inherits the surrounding text colour and works in either theme. Loaded
    through ``<img>`` it is exactly wrong — the image is an isolated
    document that CSS on the page cannot reach, so ``currentColor`` falls
    back to its initial value and every logo renders black.

    Inlining the markup instead would fix the colour by handing third-party
    SVG to the DOM, so the substitution happens here: the caller passes the
    colour it would have inherited, and the bytes leave with that colour
    baked in. A handful of marks are full-colour artwork with no
    ``currentColor`` at all; those pass through untouched.

    Literal ``black`` is treated the same way. Three providers hardcode it,
    which is invisible against a dark background.
    """
    if not color or not _LOGO_COLOR_RE.match(color):
        return payload
    encoded = color.encode()
    tinted = payload.replace(b"currentColor", encoded)
    tinted = tinted.replace(b'fill="black"', b'fill="' + encoded + b'"')
    tinted = tinted.replace(b'stroke="black"', b'stroke="' + encoded + b'"')
    return tinted


@router.get("/providers/{provider_id}/logo", include_in_schema=False)
async def get_provider_logo(
    provider_id: str,
    color: Annotated[str | None, Query()] = None,
) -> Response:
    """Serve a provider's logo, proxied and cached from models.dev.

    The catalog publishes a mark for every provider it lists, which is the
    only way a 200-provider picker gets icons without vendoring 200 files or
    falling back to initials for most of them.

    It is proxied rather than linked so the renderer makes no third-party
    request, so a restricted network breaks nothing after the first fetch,
    and so the same offline story as the rest of the catalog holds.

    *color* is the colour the mark would have inherited had it been inlined;
    see :func:`_tint_logo` for why an ``<img>`` cannot inherit it. Only the
    response is tinted — the cache holds the original bytes, so one fetch
    serves every theme.
    """
    source_id = _logo_source_id(provider_id)
    if source_id is None:
        raise HTTPException(status_code=404, detail="Unknown provider")

    path = _logo_cache_path(source_id)
    payload = _read_cached_logo(path)
    if payload is None:
        payload = await _fetch_logo(source_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="No logo for this provider")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        except OSError as exc:
            logger.debug("provider_logo_cache_write_failed path={} error={}", path, exc)

    return Response(
        content=_tint_logo(payload, color),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=604800",
            # The payload is a validated static asset, but it is still
            # third-party markup: forbid it sourcing anything of its own.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/providers/{provider_id}/usage")
async def get_provider_usage(provider_id: str) -> ProviderUsageResponse:
    """Return live provider usage details when the provider exposes them."""
    try:
        return await load_provider_usage(provider_id)
    except ProviderUsageUnsupportedError as exc:
        raise HTTPException(
            status_code=404, detail=f"Usage monitoring unsupported for '{provider_id}'."
        ) from exc
    except ProviderUsageCredentialsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderUsageUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Provider usage unavailable."
        ) from exc


@router.put("/providers/{provider_id}/visible-models")
async def save_provider_visible_models(
    provider_id: str, body: ProviderVisibleModelsRequest
) -> ProviderVisibleModelsResponse:
    """Persist provider-local model IDs shown in normal model pickers."""
    from app.agent.providers.catalog import find

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    set_provider_visible_models(provider_id, body.models)
    return ProviderVisibleModelsResponse(
        provider=provider_id,
        visible_models=provider_visible_models(provider_id),
    )


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str, body: ProviderTestRequest
) -> ProviderTestResponse:
    """Run a one-token completion to verify the supplied credentials.

    ``build_provider`` reads credentials from ``os.environ`` deep in the
    factory, so this endpoint has to mutate the environment temporarily.
    A module-level :class:`asyncio.Lock` serialises concurrent tests so
    one request's candidate key cannot leak to another.
    """
    from app.agent.providers.catalog import find
    from app.agent.providers.factory import build_provider

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    async with _TEST_PROVIDER_LOCK:
        overrides: dict[str, str | None] = {}
        if body.api_key and entry.get("env_var"):
            env_var = entry["env_var"]
            overrides[env_var] = os.environ.get(env_var)
            os.environ[env_var] = body.api_key
        for name, value in body.extra.items():
            overrides[name] = os.environ.get(name)
            os.environ[name] = value

        started = time.perf_counter()
        try:
            provider = build_provider(f"{provider_id}:{body.model}")
            from app.agent.schemas.chat import HumanMessage

            await provider.chat(
                messages=[HumanMessage(content="ping")],
                max_tokens=1,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ProviderTestResponse(ok=True, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning(
                "provider_test_failed provider={} error={}", provider_id, exc
            )
            return ProviderTestResponse(ok=False, error=str(exc))
        finally:
            for name, prev in overrides.items():
                if prev is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = prev


@router.put("/providers/{provider_id}")
async def save_provider(
    provider_id: str, body: ProviderSaveRequest
) -> ProviderSaveResponse:
    """Persist provider credentials to ``$EVOFLUX_CONFIG_DIR/.env``.

    Side effects:

    - Updates ``os.environ`` so the next ``build_provider`` call sees the
      new value without restarting the server.
    - Returns ``is_first_provider=True`` on the first-ever provider save
      (kept for the CLI's ``evoflux init`` flow, which still uses the
      seed installer; the web UI no longer triggers seed install on save).
    """
    from app.agent.providers.catalog import find
    from app.cli.seed import write_env_credentials

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    creds: dict[str, str] = {}
    credentials = entry.get("credentials") or []
    if credentials:
        if body.api_key and len(credentials) == 1:
            creds[str(credentials[0].get("name", ""))] = body.api_key
        elif body.api_key and credentials:
            creds[str(credentials[0].get("name", ""))] = body.api_key
        for field in credentials:
            name = str(field.get("name", ""))
            if name in body.extra:
                creds[name] = body.extra[name]
    elif entry.get("kind") == "api_key" and entry.get("env_var"):
        # Empty api_key means "leave the existing key alone" — the UI sends
        # blank when the user only edits optional knobs like ROUTER9_BASE_URL.
        # Clearing a key is the DELETE endpoint's job; writing "" here would
        # delete the .env line via write_env_credentials.
        if body.api_key:
            creds[entry["env_var"]] = body.api_key
    elif entry.get("kind") == "cloud_creds":
        for name in entry.get("env_vars") or []:
            if name in body.extra:
                creds[name] = body.extra[name]
    # ``body.extra`` also carries optional knobs like ROUTER9_BASE_URL /
    # CLIPROXY_BASE_URL / OLLAMA_BASE_URL — users running the proxy on
    # another host need a way to point at it without hand-editing .env.
    # Empty string means "remove the override and fall back to the
    # pydantic-settings default", which ``write_env_credentials`` honours
    # by deleting the line.
    for name, value in body.extra.items():
        if name not in creds:
            creds[name] = value
    # OAuth/local providers don't write env vars from this endpoint — OAuth
    # uses the auth route, local needs no credentials.

    if not creds:
        # Nothing to write, but report success so the UI can proceed to
        # seed materialisation.
        return ProviderSaveResponse(saved=False)

    # "First provider" = no .env yet (or .env exists but contains no
    # API keys). OAuth-only and local-only states don't count: the seed
    # installer needs a chat-capable model in EVOFLUX_MODEL or in a
    # provider env var, which a bare Copilot OAuth token doesn't satisfy.
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    is_first = not env_file.exists() or not _env_has_provider_key(env_file)

    write_env_credentials(env_file, creds)

    # Mirror writes into os.environ so build_provider sees them now.
    # ``settings`` is a frozen Pydantic instance — it doesn't refresh,
    # but the providers read from os.environ via require_api_key.
    for key, val in creds.items():
        if val:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)

    logger.info(
        "provider_credentials_saved provider={} env_vars={}",
        provider_id,
        list(creds.keys()),
    )

    # A workspace seeded before this save may still carry the placeholder
    # model, which quietly keeps every member out of the roster. Adopt the
    # lead's model for those now rather than at the next restart.
    from app.agent.loader import backfill_placeholder_agent_models

    agents_dir = Path(settings.AGENTS_DIR)
    backfill_placeholder_agent_models(agents_dir, agents_dir / "coding")

    return ProviderSaveResponse(
        saved=True,
        is_first_provider=is_first,
    )


@router.post("/seed")
async def install_seed_defaults(body: SeedInstallRequest) -> SeedInstallResponse:
    """Install bundled first-run agents/skills into the user's config dir."""
    from app.cli.seed import PROVIDER_MODEL_TOKEN, SeedDownloadError, install_seed

    provider_model = body.provider_model or PROVIDER_MODEL_TOKEN
    try:
        # Downloads + extracts a tarball (up to ~40s) — keep it off the loop.
        result = await asyncio.to_thread(
            install_seed,
            Path(settings.EVOFLUX_CONFIG_DIR),
            provider_model=provider_model,
        )
    except SeedDownloadError as exc:
        logger.warning("seed_install_failed error={}", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SeedInstallResponse(
        agents_written=result.agents_written,
        skills_written=result.skills_written,
        configs_written=result.configs_written,
        agents_removed=result.agents_removed,
        source=result.source,
    )


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str) -> dict[str, bool]:
    """Remove all credentials for a provider.

    Handles different credential storage mechanisms:
    - api_key: Removes every declared credential field from .env
    - oauth: Deletes the token JSON file from cache
    - cloud_creds: Removes env vars from .env
    - local: No-op (local providers don't store credentials)
    """
    from app.agent.providers.catalog import find
    from app.cli.seed import write_env_credentials

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    kind = entry.get("kind")

    # Drop the discovered model list too: for a manual provider it is the
    # only thing keeping it in the picker, and it outlives the process.
    _cache_provider_models(entry, [])
    _provider_model_cache.pop(provider_id, None)

    # OAuth providers: delete the token file
    if kind == "oauth":
        cache_dir = Path(settings.EVOFLUX_CACHE_DIR or "")
        token_files = {
            "codex": cache_dir / "codex_oauth.json",
            "copilot": cache_dir / "copilot_oauth.json",
        }
        token_file = token_files.get(provider_id)
        if token_file and token_file.is_file():
            token_file.unlink()
            logger.info(
                "oauth_token_deleted provider={} file={}", provider_id, token_file
            )
        return {"deleted": True}

    # Local providers: nothing to clear
    if kind == "local":
        return {"deleted": True}

    # API key and cloud credential providers: remove from .env
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    if not env_file.exists():
        return {"deleted": True}

    # Collect all env vars to clear
    creds_to_clear: dict[str, str] = {}
    if kind == "api_key":
        for field in entry.get("credentials") or []:
            name = str(field.get("name", ""))
            if name:
                creds_to_clear[name] = ""
        env_var = str(entry.get("env_var") or "")
        if env_var:
            creds_to_clear.setdefault(env_var, "")
    elif kind == "cloud_creds":
        for name in entry.get("env_vars") or []:
            creds_to_clear[name] = ""

    # Also clear any credentials from the plugin registry
    from app.agent.providers.plugin_registry import (
        ProviderCredentialStore,
        find_provider_plugin,
    )

    plugin = find_provider_plugin(provider_id)
    if plugin is not None:
        store = ProviderCredentialStore(plugin.id)
        for field in plugin.credentials:
            store.delete(field.name)

    if creds_to_clear:
        write_env_credentials(env_file, creds_to_clear)
        # Remove from os.environ
        for key in creds_to_clear:
            os.environ.pop(key, None)
        logger.info(
            "provider_credentials_deleted provider={} env_vars={}",
            provider_id,
            list(creds_to_clear.keys()),
        )

    return {"deleted": True}
