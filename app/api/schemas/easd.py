"""Public Evo Agent Specs (EASD) API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.trace_contracts import (
    TraceEvidenceKind as EasdEvidenceKind,
    TraceEvidenceResult as EasdEvidenceResult,
    TraceSpecification as EasdSpecification,
)
from app.services.easd_generation_service import (
    EasdClarificationAnswer,
    EasdGenerationIntent,
    EasdGenerationResult,
    GenerationTarget,
)
from app.services.trace_contracts import (
    TraceConstraint,
    TraceCriterion,
    TraceDeliveryFlow,
    TraceImpactTarget,
    TracePlan as EasdPlan,
    TraceRiskTier,
)


class EasdAuthoringSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=240)
    path: str = Field(min_length=1, max_length=4096)
    kind: Literal[
        "instructions",
        "documentation",
        "source",
        "test",
        "configuration",
        "repository_map",
    ]
    sha256: str = Field(min_length=64, max_length=64)
    truncated: bool = False
    used_for: list[Literal["scope", "proof"]] = Field(default_factory=list)


class EasdAuthoringUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: int | None = Field(default=None, ge=0, le=2_000_000_000)
    output: int | None = Field(default=None, ge=0, le=2_000_000_000)
    cache: int | None = Field(default=None, ge=0, le=2_000_000_000)
    thoughts: int | None = Field(default=None, ge=0, le=2_000_000_000)
    tool_use: int | None = Field(default=None, ge=0, le=2_000_000_000)
    cost: dict[str, float] = Field(default_factory=dict, max_length=20)

    @field_validator("cost")
    @classmethod
    def _bounded_cost_keys(cls, value: dict[str, float]) -> dict[str, float]:
        if any(len(key) > 80 or amount < 0 for key, amount in value.items()):
            raise ValueError(
                "usage cost keys and values must be bounded and non-negative"
            )
        return value


class EasdAuthoringGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_id: UUID
    generated_at: datetime
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=240)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=8_000)
    context_fingerprint: str = Field(min_length=64, max_length=64)
    base_fingerprint: str = Field(min_length=64, max_length=64)
    applied_sections: list[Literal["scope", "proof"]] = Field(
        min_length=1, max_length=2
    )
    edited_sections: list[Literal["scope", "proof"]] = Field(default_factory=list)
    sources: list[EasdAuthoringSource] = Field(default_factory=list, max_length=100)
    usage: EasdAuthoringUsage | None = None


class EasdAuthoringMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generations: list[EasdAuthoringGeneration] = Field(min_length=1, max_length=20)


class EasdRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    project_id: UUID | None = None
    session_id: UUID | None = None
    intent: EasdGenerationIntent | None = None
    specification: EasdSpecification | None = None
    authoring: EasdAuthoringMetadata | None = None

    @model_validator(mode="after")
    def _one_authoring_source(self) -> "EasdRunCreateRequest":
        if (self.intent is None) == (self.specification is None):
            raise ValueError("Provide exactly one of intent or specification")
        if self.authoring is not None and self.specification is None:
            raise ValueError("authoring metadata requires a specification")
        return self


class EasdGenerationDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals: list[str] = Field(default_factory=list, max_length=100)
    non_goals: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    impact_targets: list[TraceImpactTarget] = Field(
        default_factory=list, max_length=200
    )
    constraints: list[TraceConstraint] = Field(default_factory=list, max_length=100)
    risk_tier: TraceRiskTier = "standard"
    delivery_flow: TraceDeliveryFlow = Field(default_factory=TraceDeliveryFlow)
    criteria: list[TraceCriterion] = Field(default_factory=list, max_length=100)
    verification_commands: list[str] = Field(default_factory=list, max_length=50)


class EasdGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    project_id: UUID | None = None
    session_id: UUID
    target: GenerationTarget = "both"
    intent: EasdGenerationIntent
    current_draft: EasdGenerationDraftInput = Field(
        default_factory=EasdGenerationDraftInput
    )
    clarifications: list[EasdClarificationAnswer] = Field(
        default_factory=list, max_length=10
    )


class EasdGenerateResponse(EasdGenerationResult):
    pass


class EasdRevisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: EasdSpecification
    authoring: EasdAuthoringMetadata | None = None


class EasdPlanRevisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: EasdPlan


class EasdRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class EasdRevisionAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_hash: str = Field(min_length=64, max_length=64)


class EasdEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_hash: str = Field(min_length=64, max_length=64)
    criterion_ids: list[str] = Field(min_length=1, max_length=100)
    producer: str = Field(min_length=1, max_length=120)
    kind: Literal["review", "manual", "waiver"]
    result: EasdEvidenceResult
    summary: str = Field(min_length=1, max_length=12000)
    delegation_task_id: UUID | None = None
    revision: str | None = Field(default=None, max_length=120)
    artifact_hash: str | None = Field(default=None, max_length=128)
    payload: dict = Field(default_factory=dict)
    source_key: str | None = Field(default=None, max_length=255)


class EasdDeviationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=12000)
    blocking: bool = True
    criterion_id: str | None = Field(default=None, max_length=100)
    delegation_task_id: UUID | None = None
    proposed_change: dict = Field(default_factory=dict)


class EasdDeviationResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected", "resolved"]
    resolution: str = Field(min_length=1, max_length=12000)
    resolved_spec_hash: str | None = Field(default=None, min_length=64, max_length=64)


EasdRunStatus = Literal[
    "intent",
    "authoring",
    "draft",
    "accepted",
    "planning",
    "plan_review",
    "planned",
    "active",
    "reviewing",
    "verifying",
    "converged",
    "failed",
    "cancelled",
]


class EasdRunOut(BaseModel):
    id: UUID
    project_id: UUID | None
    workspace: str
    session_id: UUID | None
    title: str
    intent: dict | None
    status: EasdRunStatus
    risk_tier: Literal["trivial", "standard", "cross_layer", "critical"]
    active_spec_revision_id: UUID | None
    active_plan_revision_id: UUID | None
    convergence_report: dict | None
    converged_at: datetime | None
    created_at: datetime
    updated_at: datetime
    repository_document_hash: str | None = None
    store_generation: int | None = None


class EasdSpecRevisionOut(BaseModel):
    id: UUID
    run_id: UUID
    version: int
    status: Literal["draft", "accepted", "superseded"]
    spec: dict
    authoring: dict | None
    content_hash: str
    created_at: datetime
    accepted_at: datetime | None


class EasdPlanRevisionOut(BaseModel):
    id: UUID
    run_id: UUID
    version: int
    status: Literal["draft", "accepted", "superseded"]
    spec_hash: str
    plan: EasdPlan
    authoring: dict | None
    content_hash: str
    created_at: datetime
    accepted_at: datetime | None


class EasdMissionOut(BaseModel):
    id: UUID
    trace_run_id: UUID | None
    lead_session_id: UUID
    delegator: str
    recipient: str
    status: str
    spec: dict
    dependencies: list[str]
    attempt: int
    deadline_at: datetime | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    result: dict | None
    last_rejection: dict | None
    created_at: datetime
    updated_at: datetime


class EasdEvidenceOut(BaseModel):
    id: UUID
    run_id: UUID
    delegation_task_id: UUID | None
    spec_hash: str
    criterion_ids: list[str]
    producer: str
    kind: EasdEvidenceKind
    result: EasdEvidenceResult
    summary: str
    revision: str | None
    artifact_hash: str | None
    payload: dict
    source_key: str | None
    created_at: datetime


class EasdDeviationOut(BaseModel):
    id: UUID
    run_id: UUID
    spec_hash: str
    criterion_id: str | None
    delegation_task_id: UUID | None
    status: Literal["open", "approved", "rejected", "resolved"]
    blocking: bool
    description: str
    proposed_change: dict
    resolution: str | None
    resolved_spec_hash: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class EasdCriterionStateOut(BaseModel):
    id: str
    statement: str
    required: bool
    status: Literal["uncovered", "in_progress", "passed", "failed", "waived"]
    evidence_policy: dict
    evidence_ids: list[UUID]
    mission_ids: list[UUID]


class EasdActionBlockerOut(BaseModel):
    code: str
    message: str
    criterion_id: str | None = None
    mission_id: str | None = None
    deviation_id: str | None = None
    status: str | None = None
    commands: list[str] | None = None


EasdActionId = Literal[
    "draft_specification",
    "retry_specification",
    "approve_specification",
    "start_planning",
    "retry_planning",
    "approve_plan",
    "start_implementation",
    "start_review",
    "start_verification",
    "converge",
]


class EasdRunActionOut(BaseModel):
    id: EasdActionId
    label: str
    state: Literal["available", "blocked"]
    blockers: list[EasdActionBlockerOut]


class EasdActionRailOut(BaseModel):
    phase: EasdRunStatus
    primary_action: EasdActionId | None
    actions: list[EasdRunActionOut]


class EasdRunListResponse(BaseModel):
    runs: list[EasdRunOut]


class EasdRunDetailResponse(BaseModel):
    run: EasdRunOut
    revisions: list[EasdSpecRevisionOut]
    active_spec: EasdSpecRevisionOut | None
    plan_revisions: list[EasdPlanRevisionOut]
    active_plan: EasdPlanRevisionOut | None
    criteria: list[EasdCriterionStateOut]
    missions: list[EasdMissionOut]
    evidence: list[EasdEvidenceOut]
    deviations: list[EasdDeviationOut]
    convergence: dict | None
    action_rail: EasdActionRailOut


class EasdConvergenceResponse(BaseModel):
    report: dict[str, Any]


class EasdInitializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    project_id: UUID | None = None
    repository_paths: list[str] | None = Field(default=None, max_length=100)
    data_directory: str | None = Field(default=None, min_length=1, max_length=4096)
    overwrite: bool = False


class EasdRepositorySetupOut(BaseModel):
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
    issue: str | None


class EasdSetupResponse(BaseModel):
    scope: Literal["workspace", "project"]
    workspace: str
    project_id: UUID | None
    ready: bool
    repository_count: int
    installed_count: int
    repositories: list[EasdRepositorySetupOut]


__all__ = [name for name in globals() if name.startswith("Easd")]
