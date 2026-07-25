"""Deterministic next-work planning for AIM migration projects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

from app.services.aim import kb_store
from app.services.aim.business_rules import business_rule_review_ready
from app.services.aim.readiness import PipelineReadiness, evaluate_pipeline

SuggestionLane = Literal["ready", "active", "up_next", "needs_input"]

_PIPELINE_TITLES = {
    "aim-understand": "Understand dependency closure",
    "aim-review-rules": "Review business rules",
    "aim-design-unit": "Design target mapping",
    "aim-convert-unit": "Convert unit",
    "aim-capture-golden": "Capture golden baseline",
    "aim-test-compare": "Compare target behavior",
    "aim-cutover-check": "Check wave cutover",
}

_PIPELINE_ORDER = {
    "aim-understand": 0,
    "aim-review-rules": 1,
    "aim-design-unit": 2,
    "aim-capture-golden": 3,
    "aim-convert-unit": 4,
    "aim-test-compare": 5,
    "aim-cutover-check": 6,
}


@dataclass(frozen=True, slots=True)
class SuggestionAction:
    id: str
    lane: SuggestionLane
    pipeline: str
    title: str
    reason: str
    unit: str | None = None
    wave: int | None = None
    phase: str | None = None
    scope_units: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "lane": self.lane,
            "pipeline": self.pipeline,
            "title": self.title,
            "reason": self.reason,
            "unit": self.unit,
            "wave": self.wave,
            "phase": self.phase,
            "scope_units": list(self.scope_units),
            "depends_on": list(self.depends_on),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SuggestionPlan:
    fingerprint: str
    actions: tuple[SuggestionAction, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            lane: sum(action.lane == lane for action in self.actions)
            for lane in ("ready", "active", "up_next", "needs_input")
        }

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "counts": self.counts,
            "actions": [action.to_dict() for action in self.actions],
        }


def _progress_blocker(blocker: str) -> bool:
    text = blocker.lower()
    if "missing" in text or "cycle" in text or "empty" in text:
        return False
    return text.startswith("dependency ") or (
        text.startswith("wave ") and " unit " in text and "not equivalent" in text
    )


def _lane_for(
    readiness: PipelineReadiness,
    scope_units: tuple[str, ...],
    claimed_units: frozenset[str],
) -> SuggestionLane:
    if claimed_units.intersection(scope_units):
        return "active"
    if readiness.allowed:
        return "ready"
    if readiness.blockers and all(
        _progress_blocker(item) for item in readiness.blockers
    ):
        return "up_next"
    return "needs_input"


def _unit_action(
    kb_root: Path,
    unit_key: str,
    *,
    phase: str,
    wave: int | None,
    depends_on: list[str],
    claimed_units: frozenset[str],
) -> SuggestionAction | None:
    reason: str
    if phase == "inventory":
        pipeline = "aim-understand"
        reason = "Document unresolved dependencies first, then the selected unit."
    elif phase == "understood":
        rules_ready, _ = business_rule_review_ready(kb_root, unit_key)
        if rules_ready:
            pipeline = "aim-design-unit"
            reason = (
                "Understanding and rule review are complete; define the target mapping."
            )
        else:
            pipeline = "aim-review-rules"
            reason = "Confirm extracted business rules before target design."
    elif phase == "designed":
        pipeline = "aim-convert-unit"
        reason = "Implement the approved mapping after converted dependencies."
    elif phase == "converted":
        compare = evaluate_pipeline(
            kb_root, "aim-test-compare", unit=unit_key, case_set="smoke"
        )
        baseline_pending = any(
            "golden case" in blocker.lower() or "expected output" in blocker.lower()
            for blocker in compare.blockers
        )
        if baseline_pending:
            pipeline = "aim-capture-golden"
            reason = "Prepare and approve a trusted legacy baseline before comparison."
        else:
            pipeline = "aim-test-compare"
            reason = "Compare converted behavior against the trusted baseline."
    elif phase in {"equivalent", "cutover"}:
        return None
    else:
        return None

    readiness = evaluate_pipeline(
        kb_root,
        pipeline,
        unit=unit_key,
        wave=wave,
        case_set="smoke",
    )
    scope_units = readiness.selected_units or (unit_key,)
    lane = _lane_for(readiness, scope_units, claimed_units)
    if lane == "active":
        reason = "This action scope overlaps an active workflow claim."
    elif pipeline == "aim-understand" and len(scope_units) > 1:
        reason = (
            f"One run documents {len(scope_units)} units in dependency order; "
            "the full scope is shown before approval."
        )
    return SuggestionAction(
        id=f"{pipeline}:{unit_key}",
        lane=lane,
        pipeline=pipeline,
        title=_PIPELINE_TITLES[pipeline],
        reason=reason,
        unit=unit_key,
        wave=wave,
        phase=phase,
        scope_units=tuple(scope_units),
        depends_on=tuple(depends_on),
        blockers=readiness.blockers,
        warnings=readiness.warnings,
    )


def build_suggestion_plan(
    kb_root: Path,
    *,
    claimed_units: frozenset[str] = frozenset(),
) -> SuggestionPlan:
    """Build current recommended actions from KB state and readiness policy."""
    units = kb_store.list_units(kb_root)
    actions: list[SuggestionAction] = []
    equivalent_waves: set[int] = set()

    for module, name, frontmatter, _body in units:
        unit_key = f"{module}/{name}"
        action = _unit_action(
            kb_root,
            unit_key,
            phase=frontmatter.phase,
            wave=frontmatter.wave,
            depends_on=frontmatter.depends_on,
            claimed_units=claimed_units,
        )
        if action is not None:
            actions.append(action)
        if frontmatter.phase == "equivalent" and frontmatter.wave is not None:
            equivalent_waves.add(frontmatter.wave)

    for wave in sorted(equivalent_waves):
        wave_units = tuple(
            f"{module}/{name}"
            for module, name, frontmatter, _body in units
            if frontmatter.wave == wave
        )
        readiness = evaluate_pipeline(kb_root, "aim-cutover-check", wave=wave)
        lane = _lane_for(readiness, wave_units, claimed_units)
        actions.append(
            SuggestionAction(
                id=f"aim-cutover-check:wave:{wave}",
                lane=lane,
                pipeline="aim-cutover-check",
                title=_PIPELINE_TITLES["aim-cutover-check"],
                reason=(
                    "All units and the operational checklist must be ready before cutover."
                ),
                wave=wave,
                phase="equivalent",
                scope_units=wave_units,
                blockers=readiness.blockers,
                warnings=readiness.warnings,
            )
        )

    ready_actions = sorted(
        (action for action in actions if action.lane == "ready"),
        key=lambda action: (
            _PIPELINE_ORDER.get(action.pipeline, 99),
            len(action.scope_units),
            action.wave if action.wave is not None else 1_000_000,
            action.unit or "",
        ),
    )
    recommended_scopes: list[tuple[SuggestionAction, set[str]]] = []
    replacements: dict[str, SuggestionAction] = {}
    for action in ready_actions:
        scope = set(action.scope_units)
        overlapping = next(
            (
                recommended
                for recommended, recommended_scope in recommended_scopes
                if scope.intersection(recommended_scope)
            ),
            None,
        )
        if overlapping is None:
            recommended_scopes.append((action, scope))
            continue
        replacements[action.id] = replace(
            action,
            lane="up_next",
            reason=(
                f"Run {overlapping.unit or f'wave {overlapping.wave}'} first; "
                "its recommended scope overlaps this action. Refresh the plan "
                "after that run to remove completed dependencies."
            ),
            blockers=(
                f"recommended after {overlapping.id} because their scopes overlap",
            ),
        )
    actions = [replacements.get(action.id, action) for action in actions]

    lane_order = {"ready": 0, "active": 1, "up_next": 2, "needs_input": 3}
    actions.sort(
        key=lambda action: (
            lane_order[action.lane],
            action.wave if action.wave is not None else 1_000_000,
            len(action.scope_units),
            _PIPELINE_ORDER.get(action.pipeline, 99),
            action.unit or "",
        )
    )
    payload = [action.to_dict() for action in actions]
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SuggestionPlan(fingerprint=fingerprint, actions=tuple(actions))


def suggestion_snapshot_path(kb_root: Path) -> Path:
    return kb_root / "planning" / "workflow-suggestions.yaml"


def read_suggestion_snapshot(kb_root: Path) -> dict | None:
    path = suggestion_snapshot_path(kb_root)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else None


def write_suggestion_snapshot(
    kb_root: Path,
    plan: SuggestionPlan,
    *,
    generated_by: str,
) -> Path:
    path = suggestion_snapshot_path(kb_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": generated_by,
        **plan.to_dict(),
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path
