from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.conductor.constants.resource import (
    DEFAULT_RESOURCE_TARGET_MODES,
    ResourceTargetMode,
    ResourceVersionGap,
    ResourceVersionStatus,
)

ResourceKind = Literal["agent_team", "skill", "mcp", "plugin"]
GovernedResourceKind = Literal["agent_team", "skill", "plugin"]
ReleaseChannel = Literal["beta", "published"]
ObservedResourceState = Literal[
    "pending",
    "staged",
    "trust_pending",
    "update_pending",
    "applied",
    "in_sync",
    "declined",
    "incompatible",
    "ownership_conflict",
    "dependency_missing",
    "project_scope_mismatch",
    "error",
    "removed",
]
_HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# Requests EvoFlux builds keep ``extra="forbid"`` so a typo here fails at
# construction. Everything parsed out of a Conductor response uses
# ``extra="ignore"``: Conductor is free to add fields, and a client that
# refused them would stop enrolling the moment the server shipped one — which
# is exactly what `project.description` did.
class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_key: str
    display_name: str
    platform: Literal["macos", "linux", "windows"]
    evoflux_version: str


class RegisteredInstallation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str
    heartbeat_interval_seconds: int = Field(ge=30, le=300)


class RegisteredProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    display_name: str | None = None
    description: str | None = None
    logo_url: str | None = None


class RegisteredMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str
    primary_role: Literal["admin", "contribute", "user"]
    sub_roles: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)


class RegistrationPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    collection_level: Literal["L0", "L1", "L2"]
    telemetry: dict[str, bool] = Field(default_factory=dict)
    privacy_notice_version: str


class RegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    installation: RegisteredInstallation
    project: RegisteredProject
    member: RegisteredMember
    policy: RegistrationPolicy


class HeartbeatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    server_time: datetime
    heartbeat_interval_seconds: int = Field(ge=30, le=300)
    connection_state: Literal["active"]


class ResourceVersionNotice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version_id: str
    version: str
    status: ResourceVersionStatus
    release_channel: ReleaseChannel
    changelog: str | None = None
    published_at: datetime | None = None
    deprecation_reason: str | None = None


class ResourceChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    resource_id: str
    version_id: str | None = None
    kind: GovernedResourceKind
    slug: str
    version: str | None = None
    description: str | None = None
    changelog: str | None = None
    version_history: list[ResourceVersionNotice] = Field(default_factory=list)
    release_channel: ReleaseChannel | None = None
    sha256: str | None = None
    size: int = Field(default=0, ge=0, le=500 * 1024 * 1024)
    minimum_evoflux_version: str | None = None
    trust_required: bool = False
    tombstone: bool = False


class ResourceChangePage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[2]
    project_id: str
    next_cursor: str
    has_more: bool
    changes: list[ResourceChange] = Field(default_factory=list)


class EffectiveResourceVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    resource_id: str
    version_id: str
    kind: GovernedResourceKind
    slug: str
    version: str
    description: str | None = None
    changelog: str | None = None
    version_history: list[ResourceVersionNotice] = Field(default_factory=list)
    release_channel: ReleaseChannel
    payload: dict[str, Any]
    sha256: str
    size: int = Field(ge=0, le=500 * 1024 * 1024)
    artifact_key: str | None = None
    minimum_evoflux_version: str | None = None


class ManagedResourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    resource_id: str
    version_id: str | None = None
    version: str | None = None
    applied_version_id: str | None = None
    applied_version: str | None = None
    description: str | None = None
    changelog: str | None = None
    version_history: list[ResourceVersionNotice] = Field(default_factory=list)
    release_channel: ReleaseChannel | None = None
    kind: GovernedResourceKind
    slug: str
    modes: list[ResourceTargetMode] = Field(
        default_factory=lambda: list(DEFAULT_RESOURCE_TARGET_MODES)
    )
    content_sha256: str | None = None
    # Digest of the immutable artifact that was actually applied. Older V2
    # state files omit this field; inventory must then omit its digest rather
    # than pairing a desired-version digest with an older applied version.
    applied_content_sha256: str | None = None
    content_size: int = Field(default=0, ge=0, le=500 * 1024 * 1024)
    minimum_evoflux_version: str | None = None
    local_content_sha256: str | None = None
    # Agent names a multi-Agent resource wrote, so a later version that drops a
    # member can still find the file it left behind. A single slug cannot
    # describe that set, and older state files simply have none.
    local_agent_targets: list[str] = Field(default_factory=list)
    # Capabilities the applied release asks for. Stored as authored facts; what
    # currently resolves is observed at report time, because a plugin MCP server
    # may simply not have started yet when the files land.
    declared_skills: list[str] = Field(default_factory=list)
    declared_mcp: list[str] = Field(default_factory=list)
    plugin_installation_id: str | None = None
    previous_plugin_installation_id: str | None = None
    observed_state: ObservedResourceState = "pending"
    error_category: str | None = None
    message: str | None = None
    trust_required: bool = False
    trust_review: dict[str, Any] | None = None
    observed_at: datetime


class ManagedResourceProvider(BaseModel):
    """User-facing provenance for a locally materialized managed resource."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    resource_id: str
    modes: list[ResourceTargetMode] = Field(
        default_factory=lambda: list(DEFAULT_RESOURCE_TARGET_MODES)
    )
    version_id: str | None = None
    version: str | None = None
    applied_version_id: str | None = None
    applied_version: str | None = None
    description: str | None = None
    changelog: str | None = None
    version_history: list[ResourceVersionNotice] = Field(default_factory=list)
    update_available: bool = False
    update_required: bool = False
    version_gap: ResourceVersionGap | None = None
    current_version_deprecation_reason: str | None = None
    release_channel: ReleaseChannel | None = None
    observed_state: ObservedResourceState


class ManagedResourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    project_id: str | None = None
    committed_cursor: str | None = None
    resources: list[ManagedResourceRecord] = Field(default_factory=list)


class ResourceInventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    desired_version_id: str | None = None
    applied_version_id: str | None = None
    release_channel: ReleaseChannel | None = None
    content_sha256: str | None = None
    plugin_installation_id: str | None = None
    observed_state: ObservedResourceState
    error_category: str | None = None
    observed_at: datetime


class ResourceInventoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str
    items: list[ResourceInventoryItem] = Field(default_factory=list, max_length=500)


class TelemetryDeliverySummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    installation_id: str
    window_days: int = Field(ge=1)
    window_start: datetime = Field(validation_alias="from")
    window_end: datetime = Field(validation_alias="to")
    events: int = Field(ge=0)
    requests: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    estimated_cost_usd_micros: int = Field(ge=0)
    unpriced_model_calls: int = Field(ge=0)
    attributed_events: int = Field(ge=0)
    attributed_requests: int = Field(ge=0)
    attributed_model_calls: int = Field(ge=0)
    attributed_tool_calls: int = Field(ge=0)
    attributed_estimated_cost_usd_micros: int = Field(ge=0)


class TelemetryBatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    summary: TelemetryDeliverySummary | None = None
