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
    # Run options are persisted by PATCH /runs/{id}/options. They must be
    # serialized here too: the panel initializes its toggles from this payload,
    # so omitting them made every saved value read back as false.
    compact_before_run: bool = False
    auto_pilot: bool = False
    # True while no accepted specification has set the tier, so the stored
    # value is still only the creation-time default.
    risk_tier_provisional: bool = False
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


class EasdTraceNodeOut(BaseModel):
    id: str
    kind: Literal[
        "run",
        "specification",
        "plan",
        "criterion",
        "mission_contract",
        "mission_attempt",
        "evidence",
        "deviation",
        "convergence",
    ]
    label: str
    status: str | None
    timestamp: datetime | None
    entity_id: str | None
    data: dict[str, Any]


class EasdTraceEdgeOut(BaseModel):
    id: str
    kind: Literal[
        "contains",
        "defines",
        "compiled_to",
        "owns",
        "depends_on",
        "executes",
        "produced",
        "supports",
        "affects",
        "converged_as",
    ]
    source: str
    target: str
    criterion_ids: list[str]


class EasdTraceEventOut(BaseModel):
    id: str
    sequence: int
    event: str
    actor: str | None
    created_at: datetime | None
    from_status: str | None
    to_status: str | None
    entity_refs: list[str]
    data: dict[str, Any]


class EasdTraceGapOut(EasdActionBlockerOut):
    action_id: EasdActionId


class EasdTraceDiagnosticOut(BaseModel):
    code: str
    message: str


class EasdRunTraceResponse(BaseModel):
    version: Literal[1]
    run_id: UUID
    store_generation: int | None
    nodes: list[EasdTraceNodeOut]
    edges: list[EasdTraceEdgeOut]
    events: list[EasdTraceEventOut]
    gaps: list[EasdTraceGapOut]
    diagnostics: list[EasdTraceDiagnosticOut]


EasdRecoveryActionId = Literal[
    "retry_specification",
    "redraft_specification",
    "retry_planning",
    "replan",
    "retry_implementation",
    "retry_review",
    "retry_verification",
]


class EasdRecoveryActionOut(BaseModel):
    id: EasdRecoveryActionId
    label: str
    summary: str
    from_status: EasdRunStatus
    to_status: EasdRunStatus
    prompt_phase: Literal[
        "authoring", "planning", "implementation", "review", "verification"
    ]
    reuses: list[str]
    preserves: list[str]


class EasdRecoveryPreviewResponse(BaseModel):
    run_id: UUID
    store_generation: int | None
    actions: list[EasdRecoveryActionOut]
    unavailable_reason: str | None


class EasdRecoveryExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: EasdRecoveryActionId
    session_id: UUID
    expected_generation: int | None
    idempotency_key: UUID


class EasdRecoveryResultOut(EasdRecoveryActionOut):
    recorded_at: datetime
    session_id: UUID


class EasdRecoveryExecuteResponse(BaseModel):
    run: EasdRunOut
    recovery: EasdRecoveryResultOut


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


class EasdPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal[True]


class EasdPublicationResponse(BaseModel):
    eligible: bool
    published: bool
    created: bool | None = None
    path: str | None
    record: dict[str, Any] | None


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
    runtime_directory: str
    runtime_path: str
    runtime_owner_path: str
    runtime_shared_across_worktrees: bool
    legacy_run_count: int
    legacy_generated_file_count: int
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


class EasdRuntimeMigrationRunOut(BaseModel):
    run_id: UUID
    name: str
    source: str
    target: str
    file_count: int
    bytes: int


class EasdRuntimeMigrationRepositoryOut(BaseModel):
    path: str
    name: str
    display_name: str | None
    runtime_owner_path: str
    legacy_run_count: int
    runs: list[EasdRuntimeMigrationRunOut]
    legacy_generated_file_count: int
    generated_files: list[str]
    generated_bytes: int
    moved_run_count: int | None = None
    removed_generated_file_count: int | None = None


class EasdRuntimeMigrationPreviewResponse(BaseModel):
    workspace: str
    project_id: UUID | None
    legacy_run_count: int
    file_count: int
    bytes: int
    legacy_generated_file_count: int
    generated_bytes: int
    repositories: list[EasdRuntimeMigrationRepositoryOut]


class EasdRuntimeMigrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=4096)
    project_id: UUID | None = None
    repository_paths: list[str] | None = Field(default=None, max_length=100)
    confirm: Literal[True]


class EasdRuntimeMigrationResponse(EasdRuntimeMigrationPreviewResponse):
    moved_run_count: int
    removed_generated_file_count: int


class EasdRebindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    force: bool = False


class EasdRebindResponse(BaseModel):
    run_id: UUID
    old_session_id: UUID | None
    new_session_id: UUID
    status: str


class EasdRunOptionsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compact_before_run: bool | None = None
    auto_pilot: bool | None = None


class EasdRunOptionsUpdateResponse(BaseModel):
    run_id: UUID
    compact_before_run: bool
    auto_pilot: bool


__all__ = [name for name in globals() if name.startswith("Easd")]
