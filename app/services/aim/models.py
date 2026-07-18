"""Pydantic schemas for AIM's file-based state: ``aim.yaml``, per-unit
frontmatter, and canonicalizer profiles. These mirror the shapes documented
in ``documents/research/aim-framework.md`` §3.5/§3.7/§3.8.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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
    "understood": "aim-convert-unit",
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
            encoding_default=encoding.get("default", "utf-8"),
            encoding_legacy_fallback=encoding.get("legacy_fallback", "") or "",
            mask=[CanonicalMaskRule(**m) for m in data.get("mask", []) or []],
            whitespace=data.get("whitespace", "normalize"),
            sort_before_diff_paths=sort_before_diff.get("paths", []) or [],
            ignore=data.get("ignore", []) or [],
            decimal_tolerance=float(number_format.get("decimal_tolerance", 0.0)),
            trim_trailing_zeros=bool(number_format.get("trim_trailing_zeros", True)),
            fixed_width_fields=[
                CanonicalFixedWidthField(**f) for f in fixed_width.get("fields", []) or []
            ],
        )
