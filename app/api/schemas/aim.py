"""Response schemas for /team/projects/{id}/aim/* — read-only summary/units/
runs endpoints for an AIM migration project, per
``documents/research/aim-framework.md`` §3.8(e).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
    created_at: datetime
    report: dict | None = None


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
