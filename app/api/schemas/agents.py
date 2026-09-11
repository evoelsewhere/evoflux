"""Request and response schemas for ``/api/agents`` endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.conductor.models import ManagedResourceProvider
from app.core.skill_scope import SkillMode, default_skill_modes


class AgentSummary(BaseModel):
    name: str
    role: str
    lead: str | None = None
    description: str | None = None
    model: str | None = None
    tools: list[str] = []
    mcp: list[str] = []
    skills: list[str] = []
    valid: bool
    error: str | None = None
    editable: bool = True
    provider: ManagedResourceProvider | None = None
    runtime_model_editable: bool = False
    bundle_model: str | None = None
    model_override: str | None = None
    extra_tools: list[str] = []
    extra_skills: list[str] = []
    extra_mcp: list[str] = []


class AgentDetail(BaseModel):
    name: str
    path: str
    content: str
    config: dict | None = None
    error: str | None = None
    editable: bool = True
    provider: ManagedResourceProvider | None = None
    runtime_model_editable: bool = False
    bundle_model: str | None = None
    model_override: str | None = None
    extra_tools: list[str] = []
    extra_skills: list[str] = []
    extra_mcp: list[str] = []


class AgentWriteRequest(BaseModel):
    name: str = Field(description="Agent name (filename stem).")
    content: str = Field(description="Full .md file contents.")


class AgentDeleteResponse(BaseModel):
    name: str


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]


class AgentBulkModelRequest(BaseModel):
    names: list[str] = Field(description="Agent names (filename stems) to update.")
    model: str = Field(description="New model id, e.g. 'anthropic:claude-sonnet-5'.")


class AgentRuntimeModelRequest(BaseModel):
    model: str | None = Field(
        description=(
            "Installation-local model override. Null restores the model declared "
            "by the managed Agent bundle."
        )
    )


class AgentRuntimeSettingsRequest(BaseModel):
    model: str | None = Field(
        default=None,
        description="Installation-local model selection for the managed Agent.",
    )
    extra_tools: list[str] = Field(default_factory=list, max_length=200)
    extra_skills: list[str] = Field(default_factory=list, max_length=200)
    extra_mcp: list[str] = Field(default_factory=list, max_length=200)


class AgentBulkModelResult(BaseModel):
    name: str
    ok: bool
    error: str | None = None


class AgentBulkModelResponse(BaseModel):
    results: list[AgentBulkModelResult]


# ── Registry ────────────────────────────────────────────────────────────────


class ToolCatalogEntry(BaseModel):
    name: str
    description: str
    # Tier membership: None = available in every tier; an explicit list
    # (e.g. ["work"]) restricts the tool to those team modes.
    tiers: list[str] | None = None
    # Lead-only tools (user interaction / session structure) are never
    # granted to members — UIs should hide them from member tool pickers.
    lead_only: bool = False


class SkillCatalogEntry(BaseModel):
    name: str
    description: str
    display_name: str | None = None
    short_description: str | None = None
    allow_implicit_invocation: bool = True
    user_invocable: bool = True
    dependencies: list[dict] = Field(default_factory=list)
    # User/project skills default to both modes; bundled workflows have an
    # explicit scope in the code-owned catalog.
    modes: list[SkillMode] = Field(default_factory=default_skill_modes)


class ModelCatalogEntry(BaseModel):
    id: str
    provider: str
    model: str
    vision: bool
    input_audio: bool = False
    input_video: bool = False
    output_image: bool = False
    output_video: bool = False
    summary_trigger_tokens: int
    # Maximum context window size in tokens. null = unknown.
    context_length: int | None = None
    # Non-empty only for models that support extended thinking (e.g. Claude Opus 4).
    # The frontend uses this to decide whether to show the thinking-level pill.
    thinking_levels: list[str] = []
    thinking_control: str | None = None
    thinking_default_level: str | None = None
    thinking_default_enabled: bool | None = None
    thinking_source: str | None = None
    interfaces: list[str] = []

    # ------------------------------------------------------------------
    # Catalog facts
    # ------------------------------------------------------------------
    # Everything below is read from the model catalog rather than restated
    # in EvoFlux, so a model's price, limits, lifecycle and capabilities in
    # the picker follow the catalog the next time it refreshes. All of it is
    # optional: a self-hosted or brand-new model the catalog has never seen
    # still lists, just without the extra detail.

    #: Catalog display name (``MiMo-V2.5-Pro``) and one-line blurb.
    display_name: str | None = None
    description: str | None = None
    #: Model family (``claude-opus``, ``gemini-pro``), for grouping.
    family: str | None = None
    #: ``beta`` / ``deprecated``. The picker badges these.
    status: str | None = None
    release_date: str | None = None
    last_updated: str | None = None
    #: Training-data cutoff as the catalog states it (``"2024-12"``).
    knowledge: str | None = None

    max_output_tokens: int | None = None
    tool_call: bool | None = None
    attachment: bool | None = None
    temperature: bool | None = None
    structured_output: bool | None = None
    open_weights: bool | None = None

    #: USD per million tokens, plus any long-context tiers.
    cost: dict[str, Any] = Field(default_factory=dict)
    #: Whether this model costs nothing per token. True for genuinely free
    #: tiers and for models included in a subscription plan the user already
    #: pays for — either way the next token is free. ``None`` means the
    #: catalog quotes no price at all, which is not the same as free.
    free: bool | None = None
    #: Bounds on an explicit thinking-token budget: ``{"min": …, "max": …}``.
    thinking_budget: dict[str, int | None] = Field(default_factory=dict)
    #: Alternate service tiers this model offers (``["fast"]``).
    modes: list[str] = Field(default_factory=list)
    #: What each tier costs relative to the standard rate, by output price.
    #: A ``fast`` lane commonly bills at 2.5-5x, so a toggle that switches
    #: one on has to be able to say so.
    mode_cost_multiplier: dict[str, float] = Field(default_factory=dict)


class RegistryResponse(BaseModel):
    tools: list[ToolCatalogEntry]
    skills: list[SkillCatalogEntry]
    providers: list[str]
    models: list[ModelCatalogEntry]
