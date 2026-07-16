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
    mask: list[CanonicalMaskRule] = Field(default_factory=list)
    whitespace: str = "normalize"  # "normalize" | "exact"
    sort_before_diff_paths: list[str] = Field(default_factory=list)
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
            mask=[CanonicalMaskRule(**m) for m in data.get("mask", []) or []],
            whitespace=data.get("whitespace", "normalize"),
            sort_before_diff_paths=sort_before_diff.get("paths", []) or [],
            decimal_tolerance=float(number_format.get("decimal_tolerance", 0.0)),
            trim_trailing_zeros=bool(number_format.get("trim_trailing_zeros", True)),
            fixed_width_fields=[
                CanonicalFixedWidthField(**f) for f in fixed_width.get("fields", []) or []
            ],
        )
