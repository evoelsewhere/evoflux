"""Schemas for AIM migration projects: read-only summary/units/runs
endpoints (``documents/research/aim-framework.md`` §3.8(e)) and the
create/join wizard endpoints (§3.12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AimMetaResponse(BaseModel):
    """Backend-authoritative AIM vocabulary — the single source of truth the
    frontend reads instead of re-hardcoding phase lists/labels/eligibility."""

    unit_phases: list[str]
    project_phases: list[str]
    phase_labels: dict[str, str]
    phase_next_pipeline: dict[str, str | None]


class AimUnitActionOut(BaseModel):
    pipeline: str
    target_phase: str
    allowed: bool
    blockers: list[str]
    warnings: list[str]


class AimUnitClaimOut(BaseModel):
    workflow_execution_id: UUID
    workflow_name: str
    session_id: UUID | None
    lease_expires_at: datetime


class AimUnitOut(BaseModel):
    id: UUID
    module: str
    name: str
    kind: str
    phase: str
    wave: int | None
    assignee: str | None
    depends_on: list[str]
    complexity: dict
    revision: int
    last_transition_id: str | None
    state_verified: bool = False
    state_error: str | None = None
    next_action: AimUnitActionOut | None = None
    claim: AimUnitClaimOut | None = None
    kb_doc_path: str | None
    updated_at: datetime


class AimRunOut(BaseModel):
    id: UUID
    unit_id: UUID
    kind: str
    verdict: str
    case_set: str | None
    stats: dict
    report_path: str | None
    session_id: UUID | None = None
    workflow_execution_id: str | None = None
    created_at: datetime
    report: dict | None = None


class AimRunListItem(BaseModel):
    """One row of the project-wide run history (Runs & Reports table) —
    the run plus its unit's display name, no report payload."""

    id: UUID
    unit_id: UUID
    unit: str
    kind: str
    verdict: str
    case_set: str | None
    report_path: str | None
    session_id: UUID | None = None
    workflow_execution_id: str | None = None
    created_at: datetime


class AimReindexResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    invalid: int = 0
    errors: list[str] = Field(default_factory=list)
    runs_created: int = 0
    runs_updated: int = 0
    links_created: int = 0
    links_updated: int = 0


class AimReadinessClaimDependency(BaseModel):
    workflow_execution_id: UUID
    workflow_name: str
    execution_status: str
    session_id: UUID | None
    lease_expires_at: datetime
    units: list[str]


class AimReadinessResponse(BaseModel):
    pipeline: str
    status: Literal["ready", "blocked"]
    allowed: bool
    blockers: list[str]
    warnings: list[str]
    selected_units: list[str]
    selected_count: int
    primary_unit: str | None = None
    included_dependencies: list[str] = Field(default_factory=list)
    claim_dependencies: list[AimReadinessClaimDependency] = Field(default_factory=list)


class AimReadinessOptionsResponse(BaseModel):
    pipeline: str
    units: list[str]
    waves: list[int]


class AimSuggestionActionOut(BaseModel):
    id: str
    lane: Literal["ready", "active", "up_next", "needs_input"]
    pipeline: str
    title: str
    reason: str
    unit: str | None = None
    wave: int | None = None
    phase: str | None = None
    scope_units: list[str]
    depends_on: list[str]
    blockers: list[str]
    warnings: list[str]


class AimSuggestionPlanOut(BaseModel):
    enabled: bool
    stale: bool
    generated_at: datetime | None = None
    generated_by: str | None = None
    fingerprint: str
    counts: dict[str, int]
    actions: list[AimSuggestionActionOut]


class AimKbDocumentOut(BaseModel):
    path: str
    content: str
    revision: str
    size: int
    mtime: float
    writable: bool


class AimKbDocumentUpdate(BaseModel):
    content: str
    expected_revision: str = Field(min_length=64, max_length=64)


class AimKbDocumentCreate(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = ""


class AimKbSearchResultOut(BaseModel):
    path: str
    line: int
    excerpt: str
    matches: int


class AimKbSearchResponse(BaseModel):
    query: str
    results: list[AimKbSearchResultOut]
    truncated: bool


class AimTraceabilityLinkOut(BaseModel):
    id: str
    from_ref: str
    to_ref: str
    kind: str
    note: str | None = None


class AimTraceabilityRuleOut(BaseModel):
    id: str
    title: str
    status: str
    path: str
    source_ref: str | None = None


class AimTraceabilityUnitOut(BaseModel):
    id: str
    unit: str
    kind: str
    phase: str
    wave: int | None
    depends_on: list[str]
    target_paths: list[str]
    doc_path: str | None
    mapping_path: str | None
    rules_reviewed: bool
    rules: list[AimTraceabilityRuleOut]
    run_count: int
    passing_run_id: str | None
    latest_verdict: str | None
    links: list[AimTraceabilityLinkOut]
    gaps: list[str]


class AimTraceabilitySummaryOut(BaseModel):
    total_units: int
    reviewed_units: int
    mapped_units: int
    evidenced_units: int
    total_rules: int
    confirmed_rules: int
    explicit_links: int
    total_gaps: int


class AimTraceabilityResponse(BaseModel):
    summary: AimTraceabilitySummaryOut
    units: list[AimTraceabilityUnitOut]


class AimHealthCheckOut(BaseModel):
    id: str
    label: str
    status: Literal["pass", "warn", "fail"]
    message: str


class AimProjectHealthOut(BaseModel):
    status: Literal["ready", "degraded", "blocked"]
    checks: list[AimHealthCheckOut]
    failed_count: int
    warning_count: int


class AimStateReconcileRequest(BaseModel):
    confirmation: Literal["accept-current-state"]


class AimStateReconcileResponse(BaseModel):
    reconciliation_id: str
    reconciled: int
    state_schema: int


class AimCutoverChecklistOut(BaseModel):
    wave: int
    deployment_ready: bool
    data_reconciled: bool
    rollback_ready: bool
    monitoring_ready: bool
    approved_by: str | None
    notes: str
    updated_at: datetime


class AimCutoverChecklistUpdate(BaseModel):
    deployment_ready: bool
    data_reconciled: bool
    rollback_ready: bool
    monitoring_ready: bool
    approved_by: str | None = None
    notes: str = ""


class AimApprovalOut(BaseModel):
    execution_id: UUID
    session_id: UUID
    session_title: str | None
    workflow: str
    request_id: str
    question: str
    options: list[str]


class AimPhaseCounts(BaseModel):
    inventory: int = 0
    understood: int = 0
    designed: int = 0
    converted: int = 0
    equivalent: int = 0
    cutover: int = 0


class AimProjectSummaryOut(BaseModel):
    project_id: UUID
    total_units: int
    phase_counts: AimPhaseCounts
    equivalent_pct: float
    latest_run_at: datetime | None


# ── Setup wizard: create / preview / join ───────────────────────────────────


class AimProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_paths: list[str] = Field(min_length=1)
    target_path: str
    kb_path: str


class AimManifestPreviewResponse(BaseModel):
    rulebook_id: str
    rulebook_version: str
    source_identities: list[str]
    target_identities: list[str]
    phase: str


class AimProjectJoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kb_path: str
    source_paths: list[str] = Field(min_length=1)
    target_path: str


class AimRulebookFile(BaseModel):
    path: str
    content: str


class AimRulebookResponse(BaseModel):
    """Read-only view of the project's local rulebook (Rulebook screen) —
    the parsed manifest plus every small text artifact in that directory."""

    id: str
    manifest: dict
    files: list[AimRulebookFile]


class AimLayoutDetectionResponse(BaseModel):
    """Result of detecting the AIM folder convention on one root folder
    (``<name>/{aim_source_base/*, aim_<name>_document, aim_target_source}``
    — see app/services/aim/layout.py)."""

    root: str
    project_name: str
    source_paths: list[str]
    kb_path: str
    target_path: str
    has_manifest: bool
    source_identity_map: dict[str, str | None] = {}
    target_identity_map: dict[str, str | None] = {}
    warnings: list[str] = []
