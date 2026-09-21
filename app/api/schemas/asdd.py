"""Public Agent Spec-Driven (ASDD) API contracts.

Every payload here is derived from files in the repository, and none of them
carries a hash, a revision id or a session id. A client identifies a change by
its slug and nothing else, which is what lets two panels, two chats and a
command line all talk about the same change without coordinating.
"""

from __future__ import annotations

from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.asdd_lifecycle import RISK_TIERS, STATUSES

AsddStatus = Literal[
    "drafting",
    "proposed",
    "specifying",
    "specified",
    "designing",
    "designed",
    "tasking",
    "tasked",
    "implementing",
    "verifying",
    "ready",
    "archived",
]

AsddRisk = Literal["trivial", "standard", "cross_layer", "critical"]

AsddArtifact = Literal["proposal", "specs", "design", "tasks"]

# The Literals above exist so FastAPI can publish the values; the lifecycle
# module owns them. Fail at import rather than let a status the service can
# produce become one the API cannot represent.
if set(STATUSES) != set(get_args(AsddStatus)) or set(RISK_TIERS) != set(
    get_args(AsddRisk)
):  # pragma: no cover - import-time contract check
    raise RuntimeError("ASDD API literals drifted from app.services.asdd_lifecycle")


# --- setup ---------------------------------------------------------------


class AsddInitializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    project_id: UUID | None = None
    repository_paths: list[str] | None = Field(default=None, max_length=100)
    data_directory: str | None = Field(default=None, min_length=1, max_length=4096)
    overwrite: bool = False


class AsddRepositorySetupOut(BaseModel):
    path: str
    name: str
    display_name: str | None
    status: Literal[
        "not_initialized",
        "upgrade_required",
        "ready",
        "invalid",
    ] = Field(validation_alias="state")
    installed: bool
    manifest_path: str
    data_directory: str
    data_path: str
    rules_path: str
    skills_path: str
    skill_names: list[str]
    missing_skills: list[str]
    missing_catalogue_files: list[str]
    issue: str | None


class AsddSetupResponse(BaseModel):
    scope: Literal["workspace", "project"]
    workspace: str
    project_id: UUID | None
    #: Whether *this* workspace can be worked in. A catalogue belongs to one
    #: repository, so a session whose own repository is installed is usable even
    #: when a sibling in the same project is not.
    workspace_ready: bool
    #: Whether every repository in scope is installed. Drives the progress
    #: readout and the bulk install button, not access to the catalogue.
    ready: bool
    repository_count: int
    installed_count: int
    repositories: list[AsddRepositorySetupOut]


# --- changes -------------------------------------------------------------


class AsddBlocker(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str


class AsddAction(BaseModel):
    id: str
    label: str
    state: Literal["available", "blocked"]
    blockers: list[AsddBlocker] = Field(default_factory=list)


class AsddHold(BaseModel):
    """Where an agent stopped and what it wants a person to decide."""

    gate: str | None = None
    reason: str | None = None
    raised: str | None = None


class AsddActionRail(BaseModel):
    status: str
    primary_action: str | None
    actions: list[AsddAction]
    required_approvals: list[str]
    problems: list[AsddBlocker]
    autopilot: bool = False
    hold: AsddHold | None = None
    #: Gates this risk tier keeps for a person even with autopilot on.
    human_only_gates: list[str] = Field(default_factory=list)


class AsddChangeOut(BaseModel):
    """One change, as its folder describes it.

    `status` and `risk` are plain strings on the way out, not the Literals
    above. A hand-edited `status` is legitimate in this method — the file is the
    source of truth and the product's job is to *report* a contradiction rather
    than rewrite it — and enforcing the Literal here turned an unrecognised
    value into a `500` that blanked the whole list, not just the change that
    carried it. `declared_status_problems` reports it instead. The request
    models keep the Literals, because input the product itself writes should be
    refused when it is wrong.
    """

    change_id: str
    repository: str
    title: str
    status: str
    risk: str
    capabilities: list[str]
    delta_capabilities: list[str]
    #: What a person signed. Written only by the approve endpoint.
    approvals: dict[str, str | None]
    #: What autopilot cleared. Kept apart so the two are never confused.
    auto_approvals: dict[str, str | None] = Field(default_factory=dict)
    autopilot: bool = False
    hold: AsddHold | None = None
    tasks_total: int
    tasks_done: int
    evidence_count: int
    review_recorded: bool
    created: str | None
    path: str


class AsddCapabilityDeltaOut(BaseModel):
    capability: str
    added: list[str]
    modified: list[str]
    removed: list[str]
    problems: list[str]
    body: str


class AsddEvidenceOut(BaseModel):
    id: str
    kind: str
    result: str
    requirement: str | None
    recorded: str | None
    summary: str


class AsddChangeDetailResponse(BaseModel):
    change: AsddChangeOut
    rail: AsddActionRail
    proposal: str
    design: str | None
    tasks: str | None
    deltas: list[AsddCapabilityDeltaOut]
    evidence: list[AsddEvidenceOut]


class AsddRepositoryListingOut(BaseModel):
    """What one repository in scope contributes to the listing.

    The flat `capabilities` and `archived` below are the union across the
    scope, which is what a count or a filter wants. A spec and an archived
    change, though, live in one working tree — reading them needs to know
    which, and that is what this carries.
    """

    path: str
    capabilities: list[str]
    archived: list[str]


class AsddChangeListResponse(BaseModel):
    workspace: str
    project_id: UUID | None
    changes: list[AsddChangeOut]
    archived: list[str]
    capabilities: list[str]
    repositories: list[AsddRepositoryListingOut] = []


class AsddChangeCreateRequest(BaseModel):
    """What the requester knows before anything has been analysed.

    A title, the problem, and what should be true when it is done. Everything
    else — the slug, the capabilities, the risk tier — is what the propose
    phase is for, so it is optional here and derived there. Asking someone to
    tier a change before it has been read is asking them to guess at whether it
    owes a design.

    `problem` and `outcome` are not stored beside the change: they are written
    into `proposal.md` under `## Why` and `## What Changes`. The file is what
    the next phase reads, and a request field the server kept somewhere else
    would be a second description of the change, and the first to go stale.
    """

    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    title: str = Field(min_length=1, max_length=240)
    problem: str = Field(default="", max_length=4000)
    outcome: str = Field(default="", max_length=4000)
    change_id: str | None = Field(default=None, min_length=3, max_length=80)
    risk: AsddRisk | None = None
    capabilities: list[str] = Field(default_factory=list, max_length=20)


class AsddApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    note: str | None = Field(default=None, max_length=2000)


class AsddAutopilotRequest(BaseModel):
    """Turn autopilot on or off for one change.

    Says nothing about who is running it or where: autopilot is a property of
    the change, written into its `proposal.md`, so any chat that opens the
    change afterwards inherits it.
    """

    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    enabled: bool


class AsddActionRequest(BaseModel):
    """Ask for the instruction that carries out one phase.

    Deliberately says nothing about where the work runs. The server checks the
    phase is runnable and returns the prompt; the client sends it to whichever
    Coding chat the user has open. No chat owns a change, so any chat can run
    any phase, and closing one strands nothing.
    """

    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)


class AsddChangeActionResponse(BaseModel):
    change: AsddChangeOut
    rail: AsddActionRail
    prompt: str
    skill: str


class AsddArchiveResponse(BaseModel):
    change_id: str
    archived_as: str
    capabilities_updated: list[str]


class AsddEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    evidence_id: str = Field(min_length=3, max_length=80)
    kind: Literal["machine", "review", "manual"]
    result: Literal["passed", "failed", "inconclusive"]
    summary: str = Field(min_length=1, max_length=4000)
    requirement: str | None = Field(default=None, max_length=240)
    body: str = Field(default="", max_length=64000)


# --- specs ---------------------------------------------------------------


class AsddRequirementOut(BaseModel):
    name: str
    statement: str
    scenarios: list[dict[str, Any]]


class AsddSpecOut(BaseModel):
    capability: str
    purpose: str
    requirements: list[AsddRequirementOut]
    path: str
    body: str


class AsddSpecListResponse(BaseModel):
    workspace: str
    capabilities: list[str]


__all__ = [
    "AsddAction",
    "AsddActionRail",
    "AsddActionRequest",
    "AsddApproveRequest",
    "AsddArchiveResponse",
    "AsddArtifact",
    "AsddAutopilotRequest",
    "AsddBlocker",
    "AsddCapabilityDeltaOut",
    "AsddChangeActionResponse",
    "AsddChangeCreateRequest",
    "AsddChangeDetailResponse",
    "AsddChangeListResponse",
    "AsddChangeOut",
    "AsddEvidenceCreateRequest",
    "AsddEvidenceOut",
    "AsddHold",
    "AsddInitializeRequest",
    "AsddRepositorySetupOut",
    "AsddRequirementOut",
    "AsddRisk",
    "AsddSetupResponse",
    "AsddSpecListResponse",
    "AsddSpecOut",
    "AsddStatus",
]
