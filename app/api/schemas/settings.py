"""Request and response schemas for ``/api/settings`` endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SandboxSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    denied_patterns: list[str] = Field(default_factory=list)
    worktree_location: Literal["repository", "user_data"] = "repository"
    inherit_shell_environment: bool = False
    load_shell_profile: bool = False
    outbound_data_policy: Literal["block", "redact", "off"] = "off"
    outbound_pii_policy: Literal["off", "standard", "strict"] = "off"
    max_execution_seconds: int = Field(default=600, ge=5, le=3600)
    max_output_bytes: int = Field(default=131072, ge=4096, le=1048576)


class IgnoredSettingBody(BaseModel):
    """A hand-edited ``settings.yaml`` value that failed validation."""

    model_config = ConfigDict(extra="forbid")

    #: Field name within its section, e.g. ``summary_trigger_tokens``.
    field: str
    #: Why it was rejected, in the validator's own words.
    message: str


class ContextSettingsBody(BaseModel):
    """Context-window tuning, global across sessions.

    The writable fields mirror
    :class:`app.core.runtime_settings.ContextSettings`, where ``null`` means
    "use the built-in default". ``defaults`` reports what those defaults
    currently are so the UI can label them without duplicating the cost
    model in TypeScript.
    """

    model_config = ConfigDict(extra="forbid")

    summary_trigger_tokens: int | None = Field(default=None, ge=20_000, le=2_000_000)
    summary_max_tokens: int | None = Field(default=None, ge=2_000, le=120_000)
    keep_recent_turns: int | None = Field(default=None, ge=0, le=10)
    tool_result_offload_chars: int | None = Field(default=None, ge=2_000, le=500_000)
    keep_recent_tool_batches: int | None = Field(default=None, ge=1, le=12)
    #: Read-only: the value each unset field falls back to, keyed by field
    #: name. These are the Work-mode built-ins.
    defaults: dict[str, int] = Field(default_factory=dict)
    #: Read-only: for the fields whose built-in differs in Coding, that value.
    #: Absent keys mean both modes share the value in ``defaults``.
    coding_defaults: dict[str, int] = Field(default_factory=dict)
    #: Read-only: values this section declares in ``settings.yaml`` that failed
    #: validation and are being ignored. Non-empty means the file says one
    #: thing and the running sessions do another; saving here repairs it.
    ignored: list[IgnoredSettingBody] = Field(default_factory=list)
    #: Read-only: hard ceiling the compaction threshold is clamped to.
    max_tokens: int = Field(default=0, ge=0)
    #: Read-only: fraction of a model's context window the threshold is
    #: clamped to, so a caller can name a model's own ceiling without
    #: restating the rule.
    context_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Providers (Settings → Providers tab) ────────────────────────────────────


class VersionControlSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_timeout_seconds: float = Field(ge=10.0, le=1800.0)
    max_diff_bytes: int = Field(ge=64_000, le=50_000_000)
    default_pull_strategy: Literal["ff_only", "merge", "rebase"]
    prune_on_fetch: bool
    allow_force_push: bool
    review_request_timeout_seconds: float = Field(ge=2.0, le=300.0)
    review_retry_attempts: int = Field(ge=0, le=5)
    review_retry_backoff_seconds: float = Field(ge=0.0, le=10.0)
    review_max_concurrent_repositories: int = Field(ge=1, le=32)
    review_max_pages_per_repository: int = Field(ge=1, le=20)
    allow_review_mutations: bool
    allow_insecure_connections: bool
    require_successful_checks_before_merge: bool


class WebBridgeSettingsBody(BaseModel):
    """User-editable browser policies exposed in Settings → Browser."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_evaluate: bool = True
    built_in_allowed_domains: list[str] = Field(default_factory=list)
    built_in_blocked_domains: list[str] = Field(default_factory=list)
    built_in_allow_evaluate: bool = True
    built_in_allow_storage: bool = True
    built_in_allow_cookie_values: bool = False
    built_in_allow_http_requests: bool = True
    built_in_allow_clipboard_read: bool = False
    built_in_allow_clipboard_write: bool = True
    built_in_allow_file_uploads: bool = False
    built_in_allow_downloads: bool = True
    built_in_allow_agent_permission_accept: bool = False


class ConductorSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    url: str = ""
    machine_credential_path: str | None = None
    sync_interval_seconds: float = Field(default=60.0, ge=5.0, le=86400.0)
    heartbeat_interval_seconds: float = Field(default=60.0, ge=30.0, le=300.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    enforcement_mode: Literal["report", "enforce"] = "report"


class ConductorEnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_token: str = Field(min_length=1, max_length=4096)


class ProviderInfo(BaseModel):
    """One catalog row enriched with the user's current configuration state."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    kind: str  # "api_key" | "oauth" | "local" | "cloud_creds"
    credentials: list[dict[str, object]] = Field(default_factory=list)
    saved_credentials: dict[str, str] = Field(default_factory=dict)
    env_var: str = ""
    env_vars: list[str] = Field(default_factory=list)
    # Only set for providers without a live model-listing endpoint
    # (currently just vertexai). Other providers return an empty list
    # here and the UI must call the `/models` endpoint to populate.
    fallback_models: list[str] = Field(default_factory=list)
    oauth_command: str = ""
    docs_url: str = ""
    # This provider can mint its own key through a browser sign-in, so the
    # UI offers that alongside the key field instead of only a docs link.
    browser_login: bool = False
    # State the UI uses to decide whether to render "Connected" or a CTA.
    is_configured: bool = False
    # Static credential/config presence, before reachability probes. This lets
    # the UI distinguish "not set up" from "saved but currently unreachable".
    is_saved: bool = False
    # True when live model discovery reached the provider. False means saved
    # credentials/tokens exist, but the provider could not be reached now.
    is_reachable: bool | None = None
    # Provider-local model IDs shown in normal model pickers. Empty means all
    # discovered models for this provider are visible.
    visible_models: list[str] = Field(default_factory=list)
    # How much EvoFlux knows about this provider: "builtin" for a curated
    # integration, "plugin" for an installed one, "catalog" for a row derived
    # from models.dev alone. The UI leads with the first two and keeps the
    # long tail behind a search, because 160-odd rows is a directory, not a
    # menu.
    source: str = "builtin"
    # Wire protocol, for catalog-derived rows where it is the only thing that
    # says how the endpoint will be spoken to.
    transport: str = ""
    # Number of models the catalog lists for this provider, and how many of
    # those cost nothing per token. Both are shown before connecting, which
    # is the only useful thing to say about a provider you have no key for.
    model_count: int = 0
    free_model_count: int = 0
    # Whether EvoFlux suggests connecting this one first, and where it sits
    # in that suggestion order. With ~200 providers reachable, a flat
    # alphabetical list makes the choice harder rather than easier.
    recommended: bool = False
    rank: int = 0


class ProvidersListBody(BaseModel):
    """``GET /api/settings/providers`` response."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderInfo]
    has_any_configured: bool


class ProviderModelDetail(BaseModel):
    """What the model catalog knows about one listed model.

    Every field is optional: a self-hosted checkpoint or a proxy that
    renames models is simply absent from the catalog, and a row for it
    should still list — just with less to say.
    """

    model_config = ConfigDict(extra="forbid")

    #: Catalog display name, e.g. ``MiMo-V2.5-Pro``.
    name: str | None = None
    description: str | None = None
    family: str | None = None
    #: ``beta`` / ``deprecated``.
    status: str | None = None
    release_date: str | None = None
    knowledge: str | None = None
    context_length: int | None = None
    max_output_tokens: int | None = None
    #: Zero per-token cost — a free tier, or included in a paid plan.
    free: bool | None = None
    vision: bool = False
    tool_call: bool | None = None
    attachment: bool | None = None
    #: Selectable reasoning levels, empty when the model exposes no control.
    thinking_levels: list[str] = Field(default_factory=list)


class ProviderModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    # Agent-usable model IDs. Discovery also publishes provider-owned model
    # metadata into the shared resolver consumed by ``/agents/registry``;
    # this settings response remains compact for the checkbox list.
    models: list[str] = Field(default_factory=list)
    # ``provider`` = list returned by the live provider API.
    # ``fallback`` = curated list from the catalog (provider has no
    # listing endpoint, or live discovery failed). Only providers with
    # ``fallback_models`` set in the catalog ever return this.
    source: Literal["provider", "fallback"]
    # Per-model cost metadata (input/output/cache read/write $/1M tokens)
    # derived from the shared model catalog. Empty when the catalog has no
    # pricing for the listed models.
    model_costs: dict[str, Any] = Field(default_factory=dict)
    # Everything else the catalog knows about each listed model, keyed by
    # provider-local model ID. The settings list used to render a bare
    # `provider:model` string per row even though the catalog carries a
    # name, a description, limits and capability flags for most of them.
    model_details: dict[str, ProviderModelDetail] = Field(default_factory=dict)


class ProviderUsageWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_percent: float
    window_minutes: int | None = None
    resets_at: int | None = None


class ProviderUsageCredits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_credits: bool
    unlimited: bool
    balance: str | None = None
    used: str | None = None
    total: str | None = None
    unit: str | None = None


class ProviderUsageLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit_id: str | None = None
    limit_name: str | None = None
    primary: ProviderUsageWindow | None = None
    secondary: ProviderUsageWindow | None = None
    credits: ProviderUsageCredits | None = None
    plan_type: str | None = None
    rate_limit_reached_type: str | None = None


class ProviderUsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    limits: list[ProviderUsageLimit] = Field(default_factory=list)


class ProviderTestRequest(BaseModel):
    """``POST /api/settings/providers/{id}/test`` request body."""

    model_config = ConfigDict(extra="forbid")

    # ``api_key`` lets the UI verify a key *before* persisting it. Empty
    # string means "use the already-saved key" — useful for re-testing
    # an existing config.
    api_key: str = ""
    model: str
    # Multi-field providers (vertexai) pass their extras here.
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    latency_ms: int | None = None
    error: str | None = None


class ProviderSaveRequest(BaseModel):
    """``PUT /api/settings/providers/{id}`` request body."""

    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool
    # Convenience: whether this save call resulted in the first
    # configured provider (frontend uses this to decide whether to
    # trigger the seed installer afterward).
    is_first_provider: bool = False


class ProviderVisibleModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[str] = Field(default_factory=list)


class ProviderVisibleModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    visible_models: list[str] = Field(default_factory=list)


class SeedInstallRequest(BaseModel):
    """``POST /api/settings/seed`` request body."""

    model_config = ConfigDict(extra="forbid")

    # Optional ``provider:model`` string that substitutes for
    # ``__PROVIDER_MODEL__`` in every seeded agent .md. Empty/null means the
    # seed keeps its internal placeholder until the user configures a model.
    provider_model: str | None = None

    @field_validator("provider_model")
    @classmethod
    def _validate_provider_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if ":" not in value:
            raise ValueError("provider_model must use '<provider>:<model>' format")
        return value


class SeedInstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents_written: list[str] = Field(default_factory=list)
    skills_written: list[str] = Field(default_factory=list)
    configs_written: list[str] = Field(default_factory=list)
    agents_removed: list[str] = Field(default_factory=list)
    source: str  # "local", "tag:v0.x.y", or "branch:main"
