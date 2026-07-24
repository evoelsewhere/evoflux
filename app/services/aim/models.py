"""Pydantic schemas for AIM's file-based state: ``aim.yaml``, per-unit
frontmatter, and canonicalizer profiles. These mirror the shapes documented
in ``documents/research/aim-framework.md`` §3.5/§3.7/§3.8.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

VALID_PHASES: tuple[str, ...] = (
    "inventory",
    "understood",
    "designed",
    "converted",
    "equivalent",
    "cutover",
)

#: Project-level phase vocabulary (``aim.yaml``'s ``phase`` field). Distinct
#: from the per-unit :data:`VALID_PHASES` — a project moves through pipeline
#: stages, a unit through its own lifecycle. Kept in sync with the wizard's
#: ``seed/aim-kb-template/aim.yaml`` comment.
VALID_PROJECT_PHASES: tuple[str, ...] = (
    "assess",
    "understand",
    "design",
    "convert",
    "test",
    "cutover",
)

#: Human-readable labels for the six unit phases — the single source of truth
#: the ``/aim/meta`` endpoint serves so the frontend stops re-hardcoding them.
UNIT_PHASE_LABELS: dict[str, str] = {
    "inventory": "Inventory",
    "understood": "Understood",
    "designed": "Designed",
    "converted": "Converted",
    "equivalent": "Equivalent",
    "cutover": "Cutover",
}

#: Which pipeline advances a unit out of each phase — drives the Overview
#: board's per-unit "run next" hint. ``None`` = terminal (nothing to run).
UNIT_PHASE_NEXT_PIPELINE: dict[str, str | None] = {
    "inventory": "aim-understand",
    "understood": "aim-design-unit",
    "designed": "aim-convert-unit",
    "converted": "aim-test-compare",
    "equivalent": "aim-cutover-check",
    "cutover": None,
}

#: Ordering used by :func:`next_unit_phase` and transition checks. Index in
#: this tuple is the unit's progress; a higher index is "further along".
_UNIT_PHASE_INDEX: dict[str, int] = {phase: i for i, phase in enumerate(VALID_PHASES)}


def is_valid_unit_phase(phase: str) -> bool:
    """Whether *phase* is one of the six canonical unit phases."""
    return phase in _UNIT_PHASE_INDEX


def is_valid_project_phase(phase: str) -> bool:
    """Whether *phase* is one of the six canonical project phases."""
    return phase in VALID_PROJECT_PHASES


def next_unit_phase(phase: str) -> str | None:
    """The phase immediately after *phase*, or ``None`` at the end / for an
    unknown phase."""
    idx = _UNIT_PHASE_INDEX.get(phase)
    if idx is None or idx + 1 >= len(VALID_PHASES):
        return None
    return VALID_PHASES[idx + 1]


class AimRulebookRef(BaseModel):
    id: str
    version: str


class AimRoles(BaseModel):
    source: list[str] = Field(default_factory=list)
    target: list[str] = Field(default_factory=list)


class AimManifest(BaseModel):
    """``aim.yaml`` at the root of a KB repo — the shareable project config.

    Repos in ``roles`` are identified by remote URL or logical name, never a
    local ``workspace_id`` — those differ per contributor's machine.
    """

    rulebook: AimRulebookRef
    roles: AimRoles = Field(default_factory=AimRoles)
    golden_dir: str = "golden"
    compare_default_profile: str = "default"
    phase: str = "assess"
    state_schema: int = Field(default=1, ge=1)


class UnitFrontmatter(BaseModel):
    """Frontmatter of a ``modules/<module>/<unit>.md`` KB doc.

    This — not the ``aim_units`` DB row — is the system of record for a
    unit's state; :mod:`app.services.aim.reindex` derives the DB row from
    this.
    """

    kind: str
    phase: str = "inventory"
    wave: int | None = None
    assignee: str | None = None
    source_paths: list[str] = Field(default_factory=list)
    target_paths: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    complexity: dict = Field(default_factory=dict)
    revision: int = Field(default=0, ge=0)
    last_transition_id: str | None = None


class GoldenCaseMeta(BaseModel):
    """Trust metadata for one golden case set.

    A deterministic diff is only meaningful when the expected output has a
    known origin. Synthesized fixtures additionally need an explicit SME
    sign-off before AIM may use them to certify equivalence.
    """

    provenance: Literal["captured", "prod_log_replay", "synthesized"]
    canonicalizer_profile: str | None = None
    source_revision: str | None = None
    environment_fingerprint: str | None = None
    capture_command: str | None = None
    sme_sign_off: str | None = None

    @model_validator(mode="after")
    def _require_synthesized_sign_off(self) -> "GoldenCaseMeta":
        if self.provenance == "synthesized" and not self.sme_sign_off:
            raise ValueError("synthesized golden cases require sme_sign_off")
        return self


class AimRunMeta(BaseModel):
    id: UUID
    unit: str
    kind: Literal["compare", "convert", "test"]
    verdict: Literal["pass", "fail", "acceptable_diff", "error"]
    case_set: str | None = None
    stats: dict = Field(default_factory=dict)
    report_path: str | None = None
    session_id: UUID | None = None
    workflow_execution_id: str | None = None
    created_at: datetime


class AimLinkMeta(BaseModel):
    id: UUID
    from_ref: str
    to_ref: str
    kind: str
    note: str | None = None
    created_at: datetime


class CutoverChecklist(BaseModel):
    wave: int = Field(ge=0)
    deployment_ready: bool = False
    data_reconciled: bool = False
    rollback_ready: bool = False
    monitoring_ready: bool = False
    approved_by: str | None = None
    notes: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        for field_name, label in (
            ("deployment_ready", "deployment readiness"),
            ("data_reconciled", "data reconciliation"),
            ("rollback_ready", "rollback readiness"),
            ("monitoring_ready", "monitoring readiness"),
        ):
            if not getattr(self, field_name):
                blockers.append(f"cutover checklist: {label} is not confirmed")
        if not self.approved_by or not self.approved_by.strip():
            blockers.append("cutover checklist: approved_by is required")
        return blockers


class CanonicalMaskRule(BaseModel):
    pattern: str
    replace: str


class CanonicalFixedWidthField(BaseModel):
    field: str
    width: int
    pad: str = "right"


class CanonicalProfile(BaseModel):
    """A ``canonicalizers/<id>.yaml`` profile, consumed by
    :mod:`app.services.aim.compare`.
    """

    id: str
    description: str = ""
    mode: Literal["text", "binary"] = "text"
    encoding_default: str = "utf-8"
    #: Codepage tried when a file fails to decode as ``encoding_default`` —
    #: e.g. ``cp037`` (EBCDIC) or ``windows-1252`` for legacy output whose
    #: encoding differs from the modern target's. Empty = no fallback.
    encoding_legacy_fallback: str = ""
    mask: list[CanonicalMaskRule] = Field(default_factory=list)
    whitespace: str = "normalize"  # "normalize" | "exact"
    sort_before_diff_paths: list[str] = Field(default_factory=list)
    #: Relative-path globs to drop from the compare entirely (volatile logs,
    #: spool files) — neither a diff nor a missing/extra file is reported.
    ignore: list[str] = Field(default_factory=list)
    decimal_tolerance: float = 0.0
    trim_trailing_zeros: bool = True
    fixed_width_fields: list[CanonicalFixedWidthField] = Field(default_factory=list)

    @classmethod
    def from_yaml_dict(cls, data: dict) -> "CanonicalProfile":
        encoding = data.get("encoding") or {}
        number_format = data.get("number_format") or {}
        sort_before_diff = data.get("sort_before_diff") or {}
        fixed_width = data.get("fixed_width") or {}
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            mode=data.get("mode", "text"),
            encoding_default=encoding.get("default", "utf-8"),
            encoding_legacy_fallback=encoding.get("legacy_fallback", "") or "",
            mask=[CanonicalMaskRule(**m) for m in data.get("mask", []) or []],
            whitespace=data.get("whitespace", "normalize"),
            sort_before_diff_paths=sort_before_diff.get("paths", []) or [],
            ignore=data.get("ignore", []) or [],
            decimal_tolerance=float(number_format.get("decimal_tolerance", 0.0)),
            trim_trailing_zeros=bool(number_format.get("trim_trailing_zeros", True)),
            fixed_width_fields=[
                CanonicalFixedWidthField(**f)
                for f in fixed_width.get("fields", []) or []
            ],
        )
