from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings

PROVIDER_MODEL_PLACEHOLDER = "__PROVIDER_MODEL__"


class TitleGenerationSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    model: str | None = None


class DreamSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    model: str | None = None
    schedule: str = "0 2 * * *"

    @model_validator(mode="after")
    def _validate_model(self) -> "DreamSettings":
        if self.model and ":" not in self.model:
            raise ValueError("Dream model must be 'provider:model'.")
        return self


class MemoryVectorSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    backend: str = "disabled"
    embedding_model: str | None = None
    dim: int | None = None
    index_path: str | None = None


class GitSettings(BaseModel):
    """Operational and safety defaults for local/remote Git commands."""

    model_config = ConfigDict(extra="ignore")

    network_timeout_seconds: float = Field(default=120.0, ge=10.0, le=1800.0)
    max_diff_bytes: int = Field(default=2_000_000, ge=64_000, le=50_000_000)
    default_pull_strategy: Literal["ff_only", "merge", "rebase"] = "ff_only"
    prune_on_fetch: bool = True
    allow_force_push: bool = False


class ContextSettings(BaseModel):
    """Context-window tuning shared by every session.

    Every field is an operator override: ``None`` means "use the built-in
    default", which for the trigger is the cost-optimal threshold derived in
    :mod:`app.agent.hooks.summarization` and for the rest is that module's
    ``DEFAULT_*`` constant. The hooks read these when they are built, once
    per run, so a change takes effect on the next turn without a restart.
    """

    model_config = ConfigDict(extra="ignore")

    #: Prompt size that triggers compaction. The per-model safety ceiling
    #: still applies, so a small-context model never gets a threshold its
    #: window cannot reach.
    summary_trigger_tokens: int | None = Field(default=None, ge=20_000, le=2_000_000)
    #: Ceiling on the summary the summariser is asked to produce.
    summary_max_tokens: int | None = Field(default=None, ge=2_000, le=120_000)
    #: Assistant turns kept verbatim after a compaction. 0 summarises
    #: everything; a small window preserves the exact text of the last diff
    #: or error, which a summary cannot reproduce byte-for-byte.
    keep_recent_turns: int | None = Field(default=None, ge=0, le=10)
    #: Tool results longer than this are written to a session artifact and
    #: replaced in context by a short receipt.
    tool_result_offload_chars: int | None = Field(default=None, ge=2_000, le=500_000)
    #: Tool-call batches kept verbatim at the provider boundary. Older
    #: results outside this window are replaced by deterministic receipts.
    keep_recent_tool_batches: int | None = Field(default=None, ge=1, le=12)


class CodeReviewSettings(BaseModel):
    """Provider-neutral PR/MR API reliability and mutation guardrails."""

    model_config = ConfigDict(extra="ignore")

    request_timeout_seconds: float = Field(default=20.0, ge=2.0, le=300.0)
    retry_attempts: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    max_concurrent_repositories: int = Field(default=4, ge=1, le=32)
    max_pages_per_repository: int = Field(default=5, ge=1, le=20)
    allow_mutations: bool = True
    allow_insecure_connections: bool = False
    require_successful_checks_before_merge: bool = False


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 4082
    access_key: str | None = None


class WebBridgeSharingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default: Literal["ask", "allow", "block"] = "ask"
    blocked_domains: list[str] = Field(default_factory=list)
    allow_selection: bool = True
    allow_readable_page: bool = True
    allow_screenshot: bool = True
    max_artifact_bytes: int = Field(default=5_000_000, ge=1, le=20_000_000)
    artifact_retention_hours: int = Field(default=24, ge=1, le=24 * 30)


class WebBridgeInteractionSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_background_triggers: bool = False
    max_per_minute: int = Field(default=30, ge=1, le=600)


class WebBridgeSettings(BaseModel):
    """Guardrails for the WebBridge tool, which drives the user's *real*,
    logged-in browser. Defaults are permissive (open loopback dev) so the
    feature keeps working out of the box; production installs tighten these.
    """

    model_config = ConfigDict(extra="ignore")

    # Master switch. When False the webbridge tool refuses every action.
    enabled: bool = True
    # When non-empty, ONLY these domains may be driven (suffix match, so
    # "example.com" also matches "app.example.com"). Empty = allow all.
    allowed_domains: list[str] = Field(default_factory=list)
    # Always-refused domains (suffix match). Takes precedence over the
    # allowlist — use for banking/webmail the agent must never touch.
    blocked_domains: list[str] = Field(default_factory=list)
    # Allow the `evaluate` action (arbitrary JS in the real browser). Off in
    # locked-down installs; the far safer selector/snapshot actions stay on.
    allow_evaluate: bool = True
    # Recent actions kept in the in-memory audit ring buffer (GET /audit).
    audit_log_size: int = 200
    sharing: WebBridgeSharingSettings = Field(default_factory=WebBridgeSharingSettings)
    interactions: WebBridgeInteractionSettings = Field(
        default_factory=WebBridgeInteractionSettings
    )


class BuiltInBrowserSettings(BaseModel):
    """Agent guardrails for the persistent in-app browser profile."""

    model_config = ConfigDict(extra="ignore")

    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    allow_evaluate: bool = True
    allow_storage: bool = True
    allow_cookie_values: bool = False
    allow_http_requests: bool = True
    allow_clipboard_read: bool = False
    allow_clipboard_write: bool = True
    allow_file_uploads: bool = False
    allow_downloads: bool = True
    allow_agent_permission_accept: bool = False


class ConductorSettings(BaseModel):
    """Connection and enforcement policy for the organization control plane."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    url: str = ""
    enrollment_token: str | None = Field(default=None, exclude=True)
    machine_credential_path: str | None = None
    sync_interval_seconds: float = Field(default=60.0, ge=5.0, le=86400.0)
    heartbeat_interval_seconds: float = Field(default=60.0, ge=30.0, le=300.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    enforcement_mode: Literal["report", "enforce"] = "report"
    installation_key: str | None = None
    installation_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    project_display_name: str | None = None
    project_logo_url: str | None = None
    member_id: str | None = None
    member_display_name: str | None = None
    member_primary_role: Literal["admin", "contribute", "user"] | None = None
    collection_level: Literal["L0", "L1", "L2"] | None = None

    @model_validator(mode="after")
    def _validate_connection(self) -> "ConductorSettings":
        value = self.url.strip().rstrip("/")
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    "Conductor URL must be an http:// or https:// origin without "
                    "credentials, path, query, or fragment."
                )
        self.url = value
        return self


class ProviderUiSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    visible_models: list[str] = Field(default_factory=list)


class MemoryExtractionSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Enable auto memory extraction after agent turns.
    enabled: bool = True
    # Minimum assistant messages in the session before extraction fires.
    min_assistant_messages: int = 3
    # Re-extract every N new assistant messages after the first extraction.
    every_n_messages: int = 10
    # Maximum characters of conversation to send to the extractor LLM.
    max_input_chars: int = 12000
    # Override the extraction model ('provider:model'). Null = use the chat model.
    model: str | None = None


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title_generation: TitleGenerationSettings = Field(
        default_factory=TitleGenerationSettings
    )
    dream: DreamSettings = Field(default_factory=DreamSettings)
    memory_extraction: MemoryExtractionSettings = Field(
        default_factory=MemoryExtractionSettings
    )
    memory_vector: MemoryVectorSettings = Field(default_factory=MemoryVectorSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: dict[str, ProviderUiSettings] = Field(default_factory=dict)
    git: GitSettings = Field(default_factory=GitSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    code_reviews: CodeReviewSettings = Field(default_factory=CodeReviewSettings)
    browser: BuiltInBrowserSettings = Field(default_factory=BuiltInBrowserSettings)
    webbridge: WebBridgeSettings = Field(default_factory=WebBridgeSettings)
    conductor: ConductorSettings = Field(default_factory=ConductorSettings)


def provider_visible_models(provider_id: str) -> list[str]:
    return (
        load_runtime_settings()
        .providers.get(provider_id, ProviderUiSettings())
        .visible_models
    )


def set_provider_visible_models(provider_id: str, models: list[str]) -> None:
    cfg = load_runtime_settings()
    cleaned = sorted({model.strip() for model in models if model.strip()})
    if cleaned:
        cfg.providers[provider_id] = ProviderUiSettings(visible_models=cleaned)
    else:
        cfg.providers.pop(provider_id, None)
    save_runtime_settings(cfg)


def runtime_settings_path() -> Path:
    return Path(settings.EVOFLUX_CONFIG_DIR) / "settings.yaml"


class IgnoredSetting(BaseModel):
    """One hand-edited value that failed validation and was dropped."""

    model_config = ConfigDict(frozen=True)

    #: Dotted path into ``settings.yaml``, e.g. ``context.summary_trigger_tokens``.
    field: str
    #: Why it was rejected, in the validator's own words.
    message: str


#: Give up after this many prune-and-revalidate rounds. Each round drops every
#: field the current error set names, so a handful covers any real file; the
#: cap only stops a pathological one from looping.
_MAX_PRUNE_ROUNDS = 8

_MISSING = object()

#: Settings are re-read on nearly every request, so the warning is emitted only
#: when the set of rejected fields changes rather than once per read.
_last_ignored_signature: tuple[str, ...] | None = None


def _drop_path(raw: dict, loc: tuple) -> bool:
    """Remove the value at *loc* from *raw*. True if something was removed."""
    node = raw
    for key in loc[:-1]:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return isinstance(node, dict) and node.pop(loc[-1], _MISSING) is not _MISSING


def _log_ignored_once(ignored: tuple[IgnoredSetting, ...], usable: bool) -> None:
    global _last_ignored_signature
    signature = tuple(item.field for item in ignored)
    if signature == _last_ignored_signature:
        return
    _last_ignored_signature = signature
    if not signature:
        return
    from loguru import logger

    logger.warning(
        "runtime_settings_ignored_fields fields={} usable={}", list(signature), usable
    )


def load_runtime_settings_report(
    path: Path | None = None,
) -> tuple[RuntimeSettings, tuple[IgnoredSetting, ...]]:
    """Load ``settings.yaml``, dropping values that fail validation.

    A hand-edited file is the one input here nobody reviews, and a single
    out-of-range number used to reach every caller as an exception: the
    Settings API answered 422 for unrelated sections, the PUT that would have
    repaired the file failed the same way — leaving no way out from the UI —
    and an endpoint that did not expect it took the sidecar down with it.

    So an invalid *value* is discarded rather than fatal: the rest of the file
    still applies, the field falls back to its built-in default, and what was
    dropped is returned so a caller can say so instead of pretending the file
    was obeyed. A file that will not parse as YAML at all still raises — there
    is nothing to salvage and nothing to merge into.
    """
    from pydantic import ValidationError

    resolved = path or runtime_settings_path()
    if not resolved.exists():
        return RuntimeSettings(), ()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"settings.yaml YAML parse error: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("settings.yaml must contain a YAML mapping.")

    ignored: list[IgnoredSetting] = []
    for _ in range(_MAX_PRUNE_ROUNDS):
        try:
            loaded = RuntimeSettings.model_validate(raw)
        except ValidationError as exc:
            dropped_any = False
            for error in exc.errors():
                loc = tuple(error["loc"])
                if not loc or not _drop_path(raw, loc):
                    continue
                dropped_any = True
                ignored.append(
                    IgnoredSetting(
                        field=".".join(str(part) for part in loc),
                        message=error["msg"],
                    )
                )
            if not dropped_any:
                break
        else:
            _log_ignored_once(tuple(ignored), usable=True)
            return loaded, tuple(ignored)

    # Nothing could be pruned into a valid shape — the whole file is unusable,
    # but the process still has to run.
    _log_ignored_once(tuple(ignored), usable=False)
    return RuntimeSettings(), tuple(ignored)


def load_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    return load_runtime_settings_report(path)[0]


def save_runtime_settings(cfg: RuntimeSettings, path: Path | None = None) -> Path:
    resolved = path or runtime_settings_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json", exclude_none=True)
    serialized = yaml.safe_dump(data, sort_keys=False)
    fd, temporary_name = tempfile.mkstemp(
        dir=resolved.parent,
        prefix=f".{resolved.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)
    return resolved


def _seed_model_value(provider_model: str) -> str | None:
    provider_model = provider_model.strip()
    if not provider_model or provider_model == PROVIDER_MODEL_PLACEHOLDER:
        return None
    return provider_model


def ensure_runtime_settings(path: Path, *, provider_model: str) -> bool:
    if path.exists():
        return False
    model = _seed_model_value(provider_model)
    save_runtime_settings(
        RuntimeSettings(
            title_generation=TitleGenerationSettings(model=model),
            dream=DreamSettings(model=model),
        ),
        path,
    )
    return True
