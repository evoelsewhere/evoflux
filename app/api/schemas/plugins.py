"""Schemas for the portable Agent Plugins lifecycle API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.plugin_platform.models import PluginInspection, PluginInstallation
from app.plugin_platform.credentials import PluginCredentialState
from app.conductor.models import ManagedResourceProvider


class PluginInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    mode: Literal["install", "link"] = "install"
    enabled: bool = False


class PluginUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)


class PluginCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    version: str | None = None
    author: str | None = None
    license: str | None = None
    skill_name: str | None = None


class PluginPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    output: str | None = None


class PluginEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class PluginOperationResponse(BaseModel):
    installation: PluginInstallation
    inspection: PluginInspection


class PluginLifecycleCapabilities(BaseModel):
    can_enable: bool = True
    can_edit: bool = True
    can_pack: bool = True
    can_update: bool = True
    can_uninstall: bool = True


class PluginListItem(BaseModel):
    installation: PluginInstallation
    inspection: PluginInspection
    credentials: PluginCredentialState
    capabilities: PluginLifecycleCapabilities = Field(
        default_factory=PluginLifecycleCapabilities
    )
    provider: ManagedResourceProvider | None = None


class PluginMcpRuntimeStatus(BaseModel):
    installation_id: str | None = None
    plugin_name: str | None = None
    server_name: str
    runtime_name: str
    transport: str
    enabled: bool
    state: Literal["stopped", "starting", "ready", "error", "auth_required"]
    error: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    started_at: str | None = None


class PluginListResponse(BaseModel):
    plugins: list[PluginListItem]
    mcp_servers: list[PluginMcpRuntimeStatus] = Field(default_factory=list)


class MarketplaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent_plugins", "claude_code"]
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)


class MarketplaceSourceResponse(BaseModel):
    id: str
    kind: Literal["agent_plugins", "claude_code"]
    name: str
    url: str
    added_at: datetime
    last_synced_at: datetime | None = None
    last_error: str | None = None


class MarketplacePluginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    marketplace_id: str
    name: str
    description: str
    version: str | None = None
    author: str | None = None
    source_type: Literal[
        "artifact",
        "relative",
        "url",
        "git-subdir",
        "github",
        "command",
        "npm",
        "unsupported",
    ]
    source_url: str | None = None
    source_path: str | None = None
    source_ref: str | None = None
    components: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    compatibility: Literal["compatible", "partial", "unsupported", "unknown"]
    installable: bool
    verification: str
    artifact_sha256: str | None = None
    artifact_size: int | None = None


class MarketplacePluginPreviewResponse(BaseModel):
    preview_id: str
    plugin: MarketplacePluginResponse
    supported_components: list[str] = Field(default_factory=list)
    unsupported_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    inspection: PluginInspection


class PluginPackageFile(BaseModel):
    path: str
    kind: str
    size: int


class PluginPackageReadme(BaseModel):
    path: str
    content: str | None = None
    truncated: bool | None = None


class PluginPackageReview(BaseModel):
    files: list[PluginPackageFile]
    truncated: bool
    readme: PluginPackageReadme | None = None


class PluginFileText(BaseModel):
    path: str
    content: str
    truncated: bool


class MarketplaceInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    allow_partial: bool = False


class PluginPathResponse(BaseModel):
    path: str


class PluginWorkspaceFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str


class PluginWorkspaceFileResponse(BaseModel):
    root: str
    path: str
    content: str


class PluginWorkspaceMutationResponse(BaseModel):
    ok: bool = True
    inspection: PluginInspection


class PluginWorkspaceEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1)
    path: str = Field(min_length=1)
    kind: Literal["file", "directory"]


class PluginWorkspaceDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1)
    path: str = Field(min_length=1)


class PluginCredentialUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, str | bool | None]


__all__ = [
    "PluginCreateRequest",
    "PluginCredentialUpdateRequest",
    "PluginEnabledRequest",
    "PluginInstallRequest",
    "PluginListItem",
    "PluginLifecycleCapabilities",
    "PluginListResponse",
    "PluginMcpRuntimeStatus",
    "PluginOperationResponse",
    "PluginPackRequest",
    "PluginPathResponse",
    "PluginUpdateRequest",
    "MarketplaceCreateRequest",
    "MarketplacePluginResponse",
    "MarketplacePluginPreviewResponse",
    "PluginPackageFile",
    "PluginPackageReadme",
    "PluginPackageReview",
    "PluginFileText",
    "MarketplaceInstallRequest",
    "MarketplaceSourceResponse",
    "PluginWorkspaceDeleteRequest",
    "PluginWorkspaceEntryRequest",
    "PluginWorkspaceFileRequest",
    "PluginWorkspaceFileResponse",
    "PluginWorkspaceMutationResponse",
]
