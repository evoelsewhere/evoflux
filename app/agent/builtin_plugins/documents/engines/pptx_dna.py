"""Runtime contract for project-local PowerPoint slide DNA."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pptx"
    / "templates"
    / "powerpoint-slide-dna.json"
)


@lru_cache(maxsize=1)
def _baseline() -> dict[str, Any]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def _baseline_ids(key: str) -> set[str]:
    values = _baseline()[key]
    if isinstance(values, dict):
        return {str(value) for value in values}
    return {str(value["id"]) for value in values}


def fidelity_dimension_weights() -> dict[str, float]:
    """Return the immutable built-in fidelity scorecard weights in order."""

    return {
        str(item["id"]): float(item["weight"])
        for item in _baseline()["fidelity_scorecard"]["dimensions"]
    }


class SlideDnaCanvas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=640, le=3840)
    height: int = Field(ge=360, le=2160)
    unit: Literal["px"] = "px"
    aspect_ratio: str = Field(min_length=1, max_length=40)
    safe_area_px: dict[str, int]

    @field_validator("safe_area_px")
    @classmethod
    def validate_safe_area(cls, value: dict[str, int]) -> dict[str, int]:
        required = {"left", "right", "top", "bottom"}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError("safe_area_px is missing: " + ", ".join(missing))
        if any(not isinstance(item, int) or item < 0 for item in value.values()):
            raise ValueError("safe_area_px values must be non-negative integers")
        return value


class SlideDnaRasterTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["normalized-rgb-rmse-similarity-v1"]
    per_slide_similarity_min: float = Field(ge=0.9, le=1.0)
    deck_median_similarity_min: float = Field(ge=0.95, le=1.0)
    manual_review_below_threshold: bool


class SlideDnaFidelityTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_score: float = Field(ge=90, le=100)
    raster_targets: SlideDnaRasterTargets
    hard_failures: list[str] = Field(min_length=1)
    render_surfaces: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def matches_baseline(self) -> SlideDnaFidelityTarget:
        baseline = _baseline()["fidelity_scorecard"]
        missing_failures = sorted(
            set(baseline["hard_failures"]) - set(self.hard_failures)
        )
        if missing_failures:
            raise ValueError(
                "fidelity_target.hard_failures is missing baseline failures: "
                + ", ".join(missing_failures)
            )
        baseline_surfaces = _baseline_ids("render_surfaces")
        missing_surfaces = sorted(baseline_surfaces - set(self.render_surfaces))
        if missing_surfaces:
            raise ValueError(
                "fidelity_target.render_surfaces is missing baseline surfaces: "
                + ", ".join(missing_surfaces)
            )
        unknown_surfaces = sorted(set(self.render_surfaces) - baseline_surfaces)
        if unknown_surfaces:
            raise ValueError(
                "fidelity_target.render_surfaces contains unknown surfaces: "
                + ", ".join(unknown_surfaces)
            )
        return self


class SlideDnaDeck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    communication_job: dict[str, Any]
    visual_signature: dict[str, Any]
    canvas: SlideDnaCanvas
    layout_family: list[str] = Field(min_length=1)
    representation_policy: dict[str, str] = Field(min_length=1)
    fidelity_target: SlideDnaFidelityTarget
    known_gaps: list[str]

    @field_validator("communication_job", "visual_signature")
    @classmethod
    def non_empty_contract(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("deck contract sections must not be empty")
        return value

    @field_validator("representation_policy")
    @classmethod
    def baseline_statuses(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = _baseline_ids("capability_statuses")
        invalid = sorted({status for status in value.values() if status not in allowed})
        if invalid:
            raise ValueError(
                "representation_policy contains non-baseline statuses: "
                + ", ".join(invalid)
            )
        return value


class SlideDnaPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    narrative_role: str = Field(min_length=1, max_length=160)
    takeaway: str = Field(min_length=1, max_length=1000)
    archetype: str = Field(min_length=1, max_length=80)
    dominant_object: str = Field(min_length=1, max_length=160)
    reading_order: list[str] = Field(min_length=1)
    density: Literal["standard", "dense"]
    editable_intent: list[str]
    flattened_intent: list[str]
    source_ids: list[str]
    risk_flags: list[str]

    @field_validator("archetype")
    @classmethod
    def baseline_archetype(cls, value: str) -> str:
        if value not in _baseline_ids("slide_archetypes"):
            raise ValueError(f"unknown baseline slide archetype: {value}")
        return value


class PowerPointSlideDna(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    format: Literal["pptx"]
    baseline_id: Literal["powerpoint-office-like-baseline"]
    id: str = Field(min_length=1, max_length=160)
    deck: SlideDnaDeck
    tokens: dict[str, Any]
    slides: list[SlideDnaPlan] = Field(min_length=1)

    @field_validator("tokens")
    @classmethod
    def required_token_groups(cls, value: dict[str, Any]) -> dict[str, Any]:
        required = set(_baseline()["visual_system_contract"]["required_token_groups"])
        missing = sorted(required - set(value))
        if missing:
            raise ValueError("tokens is missing baseline groups: " + ", ".join(missing))
        empty = sorted(key for key in required if value.get(key) in (None, {}, []))
        if empty:
            raise ValueError("tokens has empty baseline groups: " + ", ".join(empty))
        return value

    @model_validator(mode="after")
    def unique_slides(self) -> PowerPointSlideDna:
        ids = [slide.id for slide in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("slide DNA ids must be unique")
        return self


class SlideDnaQaDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    status: Literal["verified", "unverified", "failed"]
    awarded_points: float = Field(ge=0)
    evidence: list[str] = Field(default_factory=list)
    observed_gap: str = Field(default="", max_length=2000)
    disposition: Literal["fixed", "flattened", "preserved", "unsupported", "unverified"]

    @model_validator(mode="after")
    def matches_baseline_dimension(self) -> SlideDnaQaDimension:
        weights = fidelity_dimension_weights()
        if self.id not in weights:
            raise ValueError(f"unknown fidelity dimension: {self.id}")
        if self.awarded_points > weights[self.id]:
            raise ValueError(
                f"fidelity dimension {self.id} exceeds its "
                f"{weights[self.id]:g}-point weight"
            )
        if self.status != "verified" and self.awarded_points != 0:
            raise ValueError(
                f"fidelity dimension {self.id} may award points only when verified"
            )
        if self.status == "verified" and not self.evidence:
            raise ValueError(f"verified fidelity dimension {self.id} requires evidence")
        return self


class SlideDnaQaLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    dimensions: list[SlideDnaQaDimension]

    @model_validator(mode="after")
    def contains_exact_baseline_dimensions(self) -> SlideDnaQaLedger:
        expected = list(fidelity_dimension_weights())
        actual = [dimension.id for dimension in self.dimensions]
        duplicates = sorted({value for value in actual if actual.count(value) > 1})
        if duplicates:
            raise ValueError(
                "QA ledger contains duplicate fidelity dimensions: "
                + ", ".join(duplicates)
            )
        missing = sorted(set(expected) - set(actual))
        if missing:
            raise ValueError(
                "QA ledger is missing fidelity dimensions: " + ", ".join(missing)
            )
        if len(actual) != len(expected):
            raise ValueError("QA ledger must contain exactly the baseline dimensions")
        return self


def load_slide_dna(path: Path) -> PowerPointSlideDna:
    return PowerPointSlideDna.model_validate_json(path.read_text(encoding="utf-8"))


def load_slide_dna_qa_ledger(path: Path) -> SlideDnaQaLedger:
    return SlideDnaQaLedger.model_validate_json(path.read_text(encoding="utf-8"))


def slide_dna_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_slide_dna_for_project(
    dna: PowerPointSlideDna,
    *,
    slide_ids: list[str],
    width: int,
    height: int,
) -> None:
    dna_ids = [slide.id for slide in dna.slides]
    if dna_ids != slide_ids:
        raise ValueError(
            "slide DNA ids must match project slide ids one-to-one and in order"
        )
    if (dna.deck.canvas.width, dna.deck.canvas.height) != (width, height):
        raise ValueError(
            f"slide DNA canvas must match project canvas ({width}x{height})"
        )


def representation_ledger(dna: PowerPointSlideDna) -> dict[str, Any]:
    return {
        "policy": dict(dna.deck.representation_policy),
        "slides": [
            {
                "slide_id": slide.id,
                "archetype": slide.archetype,
                "editable_intent": list(slide.editable_intent),
                "flattened_intent": list(slide.flattened_intent),
                "risk_flags": list(slide.risk_flags),
            }
            for slide in dna.slides
        ],
    }


def slide_dna_catalog() -> dict[str, Any]:
    baseline = _baseline()
    return {
        "required": True,
        "project_field": "dna_path",
        "project_local": True,
        "baseline_id": baseline["id"],
        "baseline_schema_version": baseline["schema_version"],
        "minimum_target_score": baseline["fidelity_scorecard"]["target_score"],
        "archetypes": sorted(_baseline_ids("slide_archetypes")),
        "capability_statuses": sorted(_baseline_ids("capability_statuses")),
        "render_surfaces": [item["id"] for item in baseline["render_surfaces"]],
        "schema": PowerPointSlideDna.model_json_schema(),
    }


__all__ = [
    "PowerPointSlideDna",
    "SlideDnaQaLedger",
    "fidelity_dimension_weights",
    "load_slide_dna",
    "load_slide_dna_qa_ledger",
    "representation_ledger",
    "slide_dna_catalog",
    "slide_dna_digest",
    "validate_slide_dna_for_project",
]
