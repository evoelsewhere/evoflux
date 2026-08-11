from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResourceKind = Literal["agent", "skill", "mcp", "plugin"]
GovernedResourceKind = Literal["agent", "skill", "plugin"]
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
    "project_scope_mismatch",
    "error",
    "removed",
]
DriftCategory = Literal[
    "missing",
    "modified",
    "unexpected",
    "wrong_revision",
    "dependency",
    "policy",
]

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")
_HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_matches(expected: str, value: Any) -> bool:
    match = _HASH_RE.fullmatch(expected)
    return bool(match and canonical_hash(value) == match.group(1).lower())


class ResourceDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResourceKind
    slug: str
    revision: str | None = None


class ManifestResource(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: ResourceKind
    slug: str
    revision: str = "1"
    hash: str = ""
    payload: dict[str, Any]
    dependencies: list[ResourceDependency] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_resource(self) -> "ManifestResource":
        if not _SLUG_RE.fullmatch(self.slug) or any(
            part in {"", ".", ".."} for part in self.slug.split("/")
        ):
            raise ValueError(f"Unsafe resource slug: {self.slug!r}.")
        if self.kind != "agent" and "/" in self.slug:
            raise ValueError(f"{self.kind} resource slugs cannot contain '/'.")
        if self.hash and not hash_matches(self.hash, self.payload):
            raise ValueError(f"Payload hash mismatch for {self.kind}/{self.slug}.")
        return self


class ManifestPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_local_resources: bool = True


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1, "1", "v1"] = 1
    revision: str
    hash: str = ""
    generated_at: datetime | None = None
    resources: list[ManifestResource] = Field(default_factory=list)
    policy: ManifestPolicy = Field(default_factory=ManifestPolicy)

    @model_validator(mode="after")
    def _validate_manifest(self) -> "Manifest":
        keys: set[tuple[str, str]] = set()
        revisions: dict[tuple[str, str], str] = {}
        for resource in self.resources:
            key = (resource.kind, resource.slug)
            if key in keys:
                raise ValueError(f"Duplicate manifest resource {key[0]}/{key[1]}.")
            keys.add(key)
            revisions[key] = resource.revision
        for resource in self.resources:
            for dependency in resource.dependencies:
                key = (dependency.kind, dependency.slug)
                if key not in keys:
                    raise ValueError(
                        f"Missing dependency {key[0]}/{key[1]} "
                        f"for {resource.kind}/{resource.slug}."
                    )
                if (
                    dependency.revision is not None
                    and revisions[key] != dependency.revision
                ):
                    raise ValueError(
                        f"Wrong dependency revision for {key[0]}/{key[1]}."
                    )
        if self.hash:
            material = self.model_dump(mode="json", exclude={"hash"})
            if not hash_matches(self.hash, material):
                raise ValueError("Manifest hash mismatch.")
        return self


class DriftRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResourceKind
    slug: str
    category: DriftCategory
    expected_revision: str | None = None
    actual_hash: str | None = None
    message: str | None = None


class ResourceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResourceKind
    slug: str
    revision: str | None = None
    state: Literal["applied", "in_sync", "drifted", "blocked", "error", "removed"]
    drift: list[DriftCategory] = Field(default_factory=list)
    message: str | None = None


class ReconcileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_revision: str
    state: Literal["in_sync", "applied", "drifted", "blocked", "error"]
    resources: list[ResourceResult] = Field(default_factory=list)
    maintenance_required: bool = False
    error: str | None = None


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_key: str
    display_name: str
    platform: Literal["macos", "linux", "windows"]
    evoflux_version: str
    workspace_association: str | None = None


class RegisteredInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    heartbeat_interval_seconds: int = Field(ge=30, le=300)


class RegisteredProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    display_name: str | None = None
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
    model_config = ConfigDict(extra="forbid")

    installation: RegisteredInstallation
    project: RegisteredProject
    member: RegisteredMember
    policy: RegistrationPolicy


class HeartbeatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_time: datetime
    heartbeat_interval_seconds: int = Field(ge=30, le=300)
    connection_state: Literal["active"]


class ResourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    resource_id: str
    version_id: str | None = None
    kind: GovernedResourceKind
    slug: str
    version: str | None = None
    release_channel: ReleaseChannel | None = None
    sha256: str | None = None
    size: int = Field(default=0, ge=0, le=500 * 1024 * 1024)
    minimum_evoflux_version: str | None = None
    trust_required: bool = False
    tombstone: bool = False


class ResourceChangePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    project_id: str
    next_cursor: str
    has_more: bool
    changes: list[ResourceChange] = Field(default_factory=list)


class EffectiveResourceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    resource_id: str
    version_id: str
    kind: GovernedResourceKind
    slug: str
    version: str
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
    release_channel: ReleaseChannel | None = None
    kind: GovernedResourceKind
    slug: str
    content_sha256: str | None = None
    local_content_sha256: str | None = None
    plugin_installation_id: str | None = None
    previous_plugin_installation_id: str | None = None
    observed_state: ObservedResourceState = "pending"
    error_category: str | None = None
    message: str | None = None
    trust_required: bool = False
    trust_review: dict[str, Any] | None = None
    observed_at: datetime


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
