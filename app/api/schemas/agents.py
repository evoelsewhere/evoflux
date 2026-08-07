"""Request and response schemas for ``/api/agents`` endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.skill_scope import SkillMode, default_skill_modes


class AgentSummary(BaseModel):
    name: str
    role: str
    description: str | None = None
    model: str | None = None
    tools: list[str] = []
    mcp: list[str] = []
    skills: list[str] = []
    valid: bool
    error: str | None = None


class AgentDetail(BaseModel):
    name: str
    path: str
    content: str
    config: dict | None = None
    error: str | None = None


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


class RegistryResponse(BaseModel):
    tools: list[ToolCatalogEntry]
    skills: list[SkillCatalogEntry]
    providers: list[str]
    models: list[ModelCatalogEntry]
