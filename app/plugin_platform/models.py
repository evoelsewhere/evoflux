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


class PluginCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    portable_components: list[Literal["skills", "mcp"]] = Field(
        default_factory=list, alias="portableComponents"
    )
    compatible_clients: list[str] = Field(
        default_factory=list, alias="compatibleClients"
    )
    host_capabilities: list[
        Literal[
            "scheduler", "artifact-storage", "credential-broker", "browser-mediation"
        ]
    ] = Field(default_factory=list, alias="hostCapabilities")


class PluginCredentialField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    type: Literal["secret", "string", "boolean"]
    required: bool
    description: str = ""


class PluginConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str = ""
    transport: Literal["mcp", "http", "browser"]
    hosts: list[str] = Field(min_length=1)
    operations: list[Literal["read", "write", "delete", "export"]] = Field(min_length=1)
    resources: list[str] = Field(default_factory=list)
    credential_fields: list[PluginCredentialField] = Field(
        default_factory=list, alias="credentialFields"
    )


class PluginPolicyCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attribute: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    operator: Literal[
        "eq",
        "neq",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
    ]
    value: object


class PluginPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    version: str = Field(default="1", pattern=r"^[0-9]+(?:\.[0-9]+)*$")
    all_conditions: list[PluginPolicyCondition] = Field(
        default_factory=list, alias="all"
    )
    any_conditions: list[PluginPolicyCondition] = Field(
        default_factory=list, alias="any"
    )
    deny: list[PluginPolicyCondition] = Field(default_factory=list)
    rate_limit: int | None = Field(default=None, gt=0, alias="rateLimit")
    quota: int | None = Field(default=None, gt=0)


class PluginReportTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    path: str
    format: Literal["markdown", "html", "docx", "xlsx", "pdf"]
    model_schema: str | None = Field(default=None, alias="modelSchema")
    destinations: list[str] = Field(default_factory=list)

    @field_validator("path", "model_schema")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("path must be a safe relative package path")
        return value


class PluginReportContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    model_schema: str | None = Field(default=None, alias="modelSchema")
    templates: list[PluginReportTemplate] = Field(min_length=1)

    @field_validator("model_schema")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("modelSchema must be a safe relative package path")
        return value


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
    compatibility: PluginCompatibility | None = None
    connections: list[PluginConnection] = Field(default_factory=list)
    policy: PluginPolicy | None = None
    report: PluginReportContract | None = None
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


class PluginRunContext(BaseModel):
    """Immutable host context attached to every plugin-mediated run."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    installation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace_id: str
    project_id: str | None = None
    connection_profile_id: str | None = None
    tenant: str
    environment: str
    run_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=128)
    policy_version: str
    policy_allowed: bool


class PluginConnectionProfile(BaseModel):
    """Installation-scoped, least-privilege external connection grant."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    installation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    workspace_id: str | None = None
    project_id: str | None = None
    tenant: str | None = None
    environment: str | None = None
    package_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    endpoint: str = Field(pattern=r"^https://")
    resources: list[str] = Field(default_factory=list)
    operations: list[Literal["read", "write", "delete", "export"]] = Field(min_length=1)
    credential_refs: list[str] = Field(default_factory=list)
    enabled: bool = True
    approval: Literal["pending", "approved", "revoked"] = "pending"
    allowed_domains: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    rate_limit: int | None = Field(default=None, gt=0, alias="rateLimit")
    quota: int | None = Field(default=None, gt=0)
    created_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None


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


class PluginTrustCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str
    executable: str
    args: list[str] = Field(default_factory=list)


class PluginTrustRemoteHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str
    transport: str
    host: str
    url: str


class PluginTrustCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str


class PluginTrustReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable_commands: list[PluginTrustCommand] = Field(default_factory=list)
    remote_hosts: list[PluginTrustRemoteHost] = Field(default_factory=list)
    environment_fields: list[str] = Field(default_factory=list)
    capabilities: list[PluginTrustCapability] = Field(default_factory=list)


class PluginInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    valid: bool
    manifest: PluginManifest | None = None
    diagnostics: list[PluginDiagnostic] = Field(default_factory=list)
    skills: list[PluginSkillComponent] = Field(default_factory=list)
    mcp_servers: list[PluginMCPComponent] = Field(default_factory=list)
    trust: PluginTrustReview = Field(default_factory=PluginTrustReview)
    extension_namespaces: list[str] = Field(default_factory=list)
    content_sha256: str | None = None


class PluginProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    registry_url: str | None = None
    artifact_url: str | None = None
    source_revision: str | None = None
    publisher_id: str | None = None
    verification_state: Literal[
        "legacy",
        "unverified",
        "verified",
        "revoked",
        "changed",
        "invalid",
        "unavailable",
        "failed",
    ] = "legacy"
    verification_reason: str | None = None
    verified_at: str | None = None


class PluginVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: str
    root: str
    content_sha256: str
    source_ref: str
    artifact_url: str | None = None
    verification_state: Literal[
        "legacy",
        "unverified",
        "verified",
        "revoked",
        "changed",
        "invalid",
        "unavailable",
        "failed",
    ] = "legacy"
    provenance: PluginProvenance = Field(default_factory=PluginProvenance)
    installed_at: str


class PluginInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str
    version: str | None = None
    description: str | None = None
    root: str
    source_type: Literal["builtin", "installed", "linked"]
    source_ref: str
    content_sha256: str
    enabled: bool = True
    managed_by: Literal["conductor"] | None = None
    managed_project_id: str | None = None
    managed_resource_id: str | None = None
    managed_version_id: str | None = None
    installed_at: str
    updated_at: str
    provenance: PluginProvenance = Field(default_factory=PluginProvenance)
    connection_profile_ids: list[str] = Field(default_factory=list)
    policy_id: str | None = None
    version_history: list[PluginVersionRecord] = Field(default_factory=list)


class PluginRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1, 2] = 2
    installations: list[PluginInstallation] = Field(default_factory=list)


__all__ = [
    "MCP_SCHEMA_ID",
    "MCP_SERVER_ADAPTER",
    "PLUGIN_NAME_RE",
    "PLUGIN_SCHEMA_ID",
    "SKILL_NAME_RE",
    "PluginCompatibility",
    "PluginConnection",
    "PluginConnectionProfile",
    "PluginCredentialField",
    "PluginDiagnostic",
    "PluginInspection",
    "PluginInstallation",
    "PluginManifest",
    "PluginPolicy",
    "PluginRunContext",
    "PluginPolicyCondition",
    "PluginProvenance",
    "PluginReportContract",
    "PluginReportTemplate",
    "PluginVersionRecord",
    "PluginMCPComponent",
    "PluginRegistryDocument",
    "PluginSkillComponent",
    "PluginTrustCapability",
    "PluginTrustCommand",
    "PluginTrustRemoteHost",
    "PluginTrustReview",
    "PortableHttpServer",
    "PortableMCPServer",
    "PortableStdioServer",
]
