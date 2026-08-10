"""Typed portable package, inspection, and installation records."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
PLUGIN_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PluginAuthor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str | None = None
    email: str | None = None
    url: str | None = None


class PluginManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
    )

    schema_id: Literal["https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"] = (
        Field(alias="$schema")
    )
    name: str = Field(min_length=1, max_length=64)
    version: str | None = None
    description: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] | None = None
    extensions: dict[str, dict] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if PLUGIN_NAME_RE.fullmatch(value) is None:
            raise ValueError("name does not satisfy Agent Plugins 1.0 constraints")
        return value


class PortableStdioServer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["stdio"]
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class PortableHttpServer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["streamable-http", "sse"]
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


PortableMCPServer = Annotated[
    PortableStdioServer | PortableHttpServer,
    Field(discriminator="type"),
]
MCP_SERVER_ADAPTER = TypeAdapter(PortableMCPServer)


class PluginDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["warning", "error"]
    code: str
    message: str
    scope: str = "package"


class PluginSkillComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    path: str
    valid: bool
    diagnostics: list[PluginDiagnostic] = Field(default_factory=list)


class PluginMCPComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    transport: str
    valid: bool
    config: dict = Field(default_factory=dict)
    diagnostics: list[PluginDiagnostic] = Field(default_factory=list)


class PluginInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    valid: bool
    manifest: PluginManifest | None = None
    diagnostics: list[PluginDiagnostic] = Field(default_factory=list)
    skills: list[PluginSkillComponent] = Field(default_factory=list)
    mcp_servers: list[PluginMCPComponent] = Field(default_factory=list)
    extension_namespaces: list[str] = Field(default_factory=list)
    content_sha256: str | None = None


class PluginInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str
    version: str | None = None
    description: str | None = None
    root: str
    source_type: Literal["installed", "linked"]
    source_ref: str
    content_sha256: str
    enabled: bool = True
    installed_at: str
    updated_at: str


class PluginRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    installations: list[PluginInstallation] = Field(default_factory=list)


__all__ = [
    "MCP_SCHEMA_ID",
    "MCP_SERVER_ADAPTER",
    "PLUGIN_NAME_RE",
    "PLUGIN_SCHEMA_ID",
    "SKILL_NAME_RE",
    "PluginDiagnostic",
    "PluginInspection",
    "PluginInstallation",
    "PluginManifest",
    "PluginMCPComponent",
    "PluginRegistryDocument",
    "PluginSkillComponent",
    "PortableHttpServer",
    "PortableMCPServer",
    "PortableStdioServer",
]
