"""Build a queryable AIM traceability and evidence coverage view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.aim import AimLink, AimRun, AimUnit
from app.services.aim.business_rules import (
    BusinessRuleError,
    business_rule_review_ready,
    list_business_rules,
)
from app.services.aim.models import VALID_PHASES
from app.services.aim.readiness import resolve_mapping_path

_PHASE_RANK = {phase: index for index, phase in enumerate(VALID_PHASES)}


@dataclass(frozen=True, slots=True)
class TraceabilityRule:
    id: str
    title: str
    status: str
    path: str
    source_ref: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "path": self.path,
            "source_ref": self.source_ref,
        }


def _link_matches_unit(link: AimLink, unit: AimUnit, unit_key: str) -> bool:
    references = {
        unit_key,
        str(unit.id),
        f"unit:{unit_key}",
        f"unit:{unit.id}",
    }
    return link.from_ref in references or link.to_ref in references


def build_traceability(
    kb_root: Path,
    units: list[AimUnit],
    runs: list[AimRun],
    links: list[AimLink],
) -> dict:
    runs_by_unit: dict[object, list[AimRun]] = {}
    for run in runs:
        runs_by_unit.setdefault(run.unit_id, []).append(run)

    rows: list[dict] = []
    total_rules = 0
    confirmed_rules = 0
    mapped_units = 0
    reviewed_units = 0
    evidenced_units = 0
    total_gaps = 0

    for unit in sorted(units, key=lambda item: (item.module, item.name)):
        unit_key = f"{unit.module}/{unit.name}"
        rule_error: str | None = None
        try:
            rules = list_business_rules(kb_root, unit_key)
        except (BusinessRuleError, OSError, UnicodeDecodeError) as exc:
            rules = []
            rule_error = str(exc)
        rule_items = [
            TraceabilityRule(
                id=rule.id,
                title=rule.title,
                status=rule.status,
                path=rule.path.relative_to(kb_root).as_posix(),
                source_ref=rule.source_ref,
            )
            for rule in rules
        ]
        total_rules += len(rule_items)
        confirmed_rules += sum(rule.status == "confirmed" for rule in rules)

        review_ready, review_blocker = business_rule_review_ready(kb_root, unit_key)
        if review_ready:
            reviewed_units += 1
        mapping = resolve_mapping_path(kb_root, unit.module, unit.name)
        if mapping is not None:
            mapped_units += 1

        unit_runs = sorted(
            runs_by_unit.get(unit.id, []),
            key=lambda item: item.created_at,
            reverse=True,
        )
        passing_compare = next(
            (
                run
                for run in unit_runs
                if run.kind == "compare" and run.verdict == "pass"
            ),
            None,
        )
        if passing_compare is not None:
            evidenced_units += 1

        phase_rank = _PHASE_RANK.get(unit.phase, -1)
        gaps: list[str] = []
        if not unit.kb_doc_path or not (kb_root / unit.kb_doc_path).is_file():
            gaps.append("Unit documentation is missing")
        if rule_error:
            gaps.append(rule_error)
        elif phase_rank >= _PHASE_RANK["understood"] and not review_ready:
            gaps.append(review_blocker)
        if phase_rank >= _PHASE_RANK["designed"] and mapping is None:
            gaps.append("Target mapping is missing")
        if phase_rank >= _PHASE_RANK["equivalent"] and passing_compare is None:
            gaps.append("Passing compare evidence is missing")

        unit_links = [
            link for link in links if _link_matches_unit(link, unit, unit_key)
        ]
        total_gaps += len(gaps)
        rows.append(
            {
                "id": str(unit.id),
                "unit": unit_key,
                "kind": unit.kind,
                "phase": unit.phase,
                "wave": unit.wave,
                "depends_on": list(unit.depends_on),
                "target_paths": list(unit.target_paths),
                "doc_path": unit.kb_doc_path,
                "mapping_path": (
                    mapping.relative_to(kb_root).as_posix() if mapping else None
                ),
                "rules_reviewed": review_ready,
                "rules": [rule.to_dict() for rule in rule_items],
                "run_count": len(unit_runs),
                "passing_run_id": str(passing_compare.id) if passing_compare else None,
                "latest_verdict": unit_runs[0].verdict if unit_runs else None,
                "links": [
                    {
                        "id": str(link.id),
                        "from_ref": link.from_ref,
                        "to_ref": link.to_ref,
                        "kind": link.kind,
                        "note": link.note,
                    }
                    for link in unit_links
                ],
                "gaps": gaps,
            }
        )

    return {
        "summary": {
            "total_units": len(units),
            "reviewed_units": reviewed_units,
            "mapped_units": mapped_units,
            "evidenced_units": evidenced_units,
            "total_rules": total_rules,
            "confirmed_rules": confirmed_rules,
            "explicit_links": len(links),
            "total_gaps": total_gaps,
        },
        "units": rows,
    }
