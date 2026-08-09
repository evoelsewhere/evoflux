"""Schemas for the portable Agent Plugins lifecycle API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.plugin_platform.models import PluginInspection, PluginInstallation


class PluginInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    mode: Literal["install", "link"] = "install"
    enabled: bool = True


class PluginCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
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


class PluginListItem(BaseModel):
    installation: PluginInstallation
    inspection: PluginInspection


class PluginMcpRuntimeStatus(BaseModel):
    installation_id: str | None = None
    plugin_name: str | None = None
    server_name: str
    runtime_name: str
    transport: str
    enabled: bool
    state: Literal["stopped", "starting", "ready", "error"]
    error: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    started_at: str | None = None


class PluginListResponse(BaseModel):
    plugins: list[PluginListItem]
    mcp_servers: list[PluginMcpRuntimeStatus] = Field(default_factory=list)


class PluginPathResponse(BaseModel):
    path: str


__all__ = [
    "PluginCreateRequest",
    "PluginEnabledRequest",
    "PluginInstallRequest",
    "PluginListItem",
    "PluginListResponse",
    "PluginMcpRuntimeStatus",
    "PluginOperationResponse",
    "PluginPackRequest",
    "PluginPathResponse",
]
