"""Schemas for AIM migration projects: read-only summary/units/runs
endpoints (``documents/research/aim-framework.md`` §3.8(e)) and the
create/join wizard endpoints (§3.12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
    rulebook_id: str = Field(min_length=1)
    rulebook_version: str = "0.1"
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
    """Read-only view of the project's rulebook pack (Rulebook screen) —
    the parsed manifest plus every small text artifact in the pack."""

    id: str
    #: 'project' when resolved from the KB repo's own rulebook/ override,
    #: 'builtin' when it's one of the shared packs shipped with EvoFlux.
    source: Literal["project", "builtin"]
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
