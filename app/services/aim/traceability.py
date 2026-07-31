"""Build a queryable AIM traceability and evidence coverage view."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from app.agent.tools.builtin.skill import _parse_frontmatter
from app.models.aim import AimLink, AimRun, AimUnit
from app.services.aim import kb_store
from app.services.aim.business_rules import (
    BusinessRuleError,
    business_rule_review_ready,
    list_business_rules,
)
from app.services.aim.models import (
    UNIT_PHASE_NEXT_PIPELINE,
    VALID_PHASES,
    UnitFrontmatter,
    next_unit_phase,
)
from app.services.aim.readiness import evaluate_pipeline, resolve_mapping_path
from app.services.aim.verification import (
    VerificationError,
    resolve_verification_command,
)

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


@dataclass(frozen=True, slots=True)
class TraceabilityIssue:
    code: str
    severity: Literal["blocker", "warning", "info"]
    message: str
    related_units: tuple[str, ...] = ()
    path: str | None = None
    pipeline: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "related_units": list(self.related_units),
            "path": self.path,
            "pipeline": self.pipeline,
        }


@dataclass(frozen=True, slots=True)
class TraceabilityNextAction:
    pipeline: str
    target_phase: str
    allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    scope_units: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "target_phase": self.target_phase,
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "scope_units": list(self.scope_units),
        }


def _link_matches_unit(link: AimLink, unit: AimUnit, unit_key: str) -> bool:
    references = {
        unit_key,
        str(unit.id),
        f"unit:{unit_key}",
        f"unit:{unit.id}",
    }
    return link.from_ref in references or link.to_ref in references


def _dependency_cycles(graph: dict[str, list[str]]) -> dict[str, list[tuple[str, ...]]]:
    cycles: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    visited: set[str] = set()
    active: list[str] = []
    seen: set[tuple[str, ...]] = set()

    def visit(unit_key: str) -> None:
        if unit_key in active:
            start = active.index(unit_key)
            cycle = tuple(active[start:] + [unit_key])
            canonical = tuple(sorted(cycle[:-1]))
            if canonical not in seen:
                seen.add(canonical)
                for member in cycle[:-1]:
                    cycles[member].append(cycle)
            return
        if unit_key in visited or unit_key not in graph:
            return
        active.append(unit_key)
        for dependency in graph[unit_key]:
            visit(dependency)
        active.pop()
        visited.add(unit_key)

    for key in graph:
        visit(key)
    return cycles


def _transitive_dependents(
    unit_key: str, reverse_graph: dict[str, set[str]]
) -> set[str]:
    discovered: set[str] = set()
    pending = list(reverse_graph.get(unit_key, ()))
    while pending:
        current = pending.pop()
        if current in discovered:
            continue
        discovered.add(current)
        pending.extend(reverse_graph.get(current, ()))
    return discovered


def _next_action(
    kb_root: Path,
    unit_key: str,
    phase: str,
    wave: int | None,
    *,
    rules_reviewed: bool,
    claimed_units: frozenset[str],
) -> TraceabilityNextAction | None:
    pipeline = UNIT_PHASE_NEXT_PIPELINE.get(phase)
    target_phase = next_unit_phase(phase)
    if phase == "understood" and not rules_reviewed:
        pipeline = "aim-review-rules"
        target_phase = "understood"
    if pipeline is None or target_phase is None:
        return None
    readiness = evaluate_pipeline(
        kb_root,
        pipeline,
        unit=unit_key,
        wave=wave,
        case_set="smoke",
    )
    scope_units = readiness.selected_units or (unit_key,)
    claim_blockers = (
        ("Action scope intersects an active workflow claim",)
        if claimed_units.intersection(scope_units)
        else ()
    )
    return TraceabilityNextAction(
        pipeline=pipeline,
        target_phase=target_phase,
        allowed=readiness.allowed and not claim_blockers,
        blockers=(*readiness.blockers, *claim_blockers),
        warnings=readiness.warnings,
        scope_units=scope_units,
    )


def _issue_sort_key(issue: TraceabilityIssue) -> tuple[int, str, str]:
    priority = {"blocker": 0, "warning": 1, "info": 2}
    return priority[issue.severity], issue.code, issue.message


def _known_ref_exists(
    reference: str,
    *,
    unit_refs: set[str],
    rule_refs: set[str],
    run_refs: set[str],
) -> bool:
    if ":" not in reference:
        return True
    prefix, value = reference.split(":", 1)
    if prefix == "unit":
        return value in unit_refs
    if prefix == "rule":
        return value in rule_refs
    if prefix == "run":
        return value in run_refs
    return True


def build_traceability(
    kb_root: Path,
    units: list[AimUnit],
    runs: list[AimRun],
    links: list[AimLink],
    *,
    target_root: Path | None = None,
    claimed_units: frozenset[str] = frozenset(),
) -> dict:
    runs_by_unit: dict[object, list[AimRun]] = {}
    for run in runs:
        runs_by_unit.setdefault(run.unit_id, []).append(run)

    units_by_key = {f"{unit.module}/{unit.name}": unit for unit in units}
    states: dict[str, tuple[UnitFrontmatter, str] | None] = {}
    state_errors: dict[str, str] = {}
    for unit_key, unit in units_by_key.items():
        try:
            states[unit_key] = kb_store.read_unit(kb_root, unit.module, unit.name)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            states[unit_key] = None
            state_errors[unit_key] = str(exc)

    graph: dict[str, list[str]] = {}
    for unit_key, unit in units_by_key.items():
        state = states[unit_key]
        graph[unit_key] = (
            list(state[0].depends_on) if state is not None else list(unit.depends_on)
        )
    reverse_graph: dict[str, set[str]] = defaultdict(set)
    for unit_key, dependencies in graph.items():
        for dependency in dependencies:
            reverse_graph[dependency].add(unit_key)
    cycles = _dependency_cycles(graph)

    project_issues: list[TraceabilityIssue] = []
    rule_refs: set[str] = set()
    rules_root = kb_root / "business-rules"
    if rules_root.is_dir():
        for path in sorted(rules_root.glob("*.md")):
            rule_refs.add(path.stem)
            try:
                metadata, _body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
                project_issues.append(
                    TraceabilityIssue(
                        code="orphan_rule_invalid",
                        severity="blocker",
                        message=f"Business rule {path.stem} is invalid: {exc}",
                        path=path.relative_to(kb_root).as_posix(),
                    )
                )
                continue
            assigned_unit = metadata.get("unit")
            if not isinstance(assigned_unit, str) or assigned_unit not in units_by_key:
                project_issues.append(
                    TraceabilityIssue(
                        code="orphan_rule_unit",
                        severity="warning",
                        message=(
                            f"Business rule {path.stem} references missing unit "
                            f"{assigned_unit!r}"
                        ),
                        path=path.relative_to(kb_root).as_posix(),
                    )
                )

    unit_refs = set(units_by_key) | {str(unit.id) for unit in units}
    run_refs = {str(run.id) for run in runs}
    dangling_link_issues: dict[str, list[TraceabilityIssue]] = defaultdict(list)
    for link in links:
        missing_refs = [
            reference
            for reference in (link.from_ref, link.to_ref)
            if not _known_ref_exists(
                reference,
                unit_refs=unit_refs,
                rule_refs=rule_refs,
                run_refs=run_refs,
            )
        ]
        if not missing_refs:
            continue
        issue = TraceabilityIssue(
            code="dangling_trace_link",
            severity="warning",
            message=(
                f"Traceability link {link.kind} references missing "
                + ", ".join(missing_refs)
            ),
            path=f"state/links/{link.id}.yaml",
        )
        matched = False
        for unit_key, unit in units_by_key.items():
            if _link_matches_unit(link, unit, unit_key):
                dangling_link_issues[unit_key].append(issue)
                matched = True
        if not matched:
            project_issues.append(issue)

    target_owners: dict[str, list[str]] = defaultdict(list)
    for unit_key, unit in units_by_key.items():
        state = states[unit_key]
        paths = state[0].target_paths if state is not None else unit.target_paths
        for raw_path in paths:
            normalized = Path(raw_path).as_posix()
            target_owners[normalized].append(unit_key)
    target_collisions = {
        path: owners for path, owners in target_owners.items() if len(owners) > 1
    }

    rows: list[dict] = []
    total_rules = 0
    confirmed_rules = 0
    mapped_units = 0
    reviewed_units = 0
    evidenced_units = 0
    issue_counts: Counter[str] = Counter()
    at_risk_units = 0
    ready_actions = 0

    for unit in sorted(units, key=lambda item: (item.module, item.name)):
        unit_key = f"{unit.module}/{unit.name}"
        state = states[unit_key]
        frontmatter, body = state if state is not None else (None, "")
        effective_phase = frontmatter.phase if frontmatter is not None else unit.phase
        effective_wave = frontmatter.wave if frontmatter is not None else unit.wave
        effective_dependencies = (
            list(frontmatter.depends_on)
            if frontmatter is not None
            else list(unit.depends_on)
        )
        effective_target_paths = (
            list(frontmatter.target_paths)
            if frontmatter is not None
            else list(unit.target_paths)
        )
        phase_rank = _PHASE_RANK.get(effective_phase, -1)
        issues: list[TraceabilityIssue] = []
        issues.extend(dangling_link_issues.get(unit_key, ()))

        if state is None:
            issues.append(
                TraceabilityIssue(
                    code="unit_document_unavailable",
                    severity="blocker",
                    message=state_errors.get(unit_key, "Unit documentation is missing"),
                    path=unit.kb_doc_path,
                )
            )
        elif frontmatter is not None:
            drift: list[str] = []
            if unit.phase != frontmatter.phase:
                drift.append(f"phase {unit.phase} → {frontmatter.phase}")
            if unit.wave != frontmatter.wave:
                drift.append(f"wave {unit.wave} → {frontmatter.wave}")
            if sorted(unit.depends_on) != sorted(frontmatter.depends_on):
                drift.append("dependencies differ")
            if sorted(unit.target_paths) != sorted(frontmatter.target_paths):
                drift.append("target paths differ")
            if drift:
                issues.append(
                    TraceabilityIssue(
                        code="index_out_of_sync",
                        severity="warning",
                        message="Local index differs from KB: " + ", ".join(drift),
                        path=unit.kb_doc_path,
                    )
                )
            if phase_rank >= _PHASE_RANK["understood"] and not body.strip():
                issues.append(
                    TraceabilityIssue(
                        code="unit_document_empty",
                        severity="blocker",
                        message="Unit documentation body is empty",
                        path=unit.kb_doc_path,
                    )
                )

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
        compare_runs = [run for run in unit_runs if run.kind == "compare"]
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

        if rule_error:
            issues.append(
                TraceabilityIssue(
                    code="rule_document_invalid",
                    severity="blocker",
                    message=rule_error,
                    path="business-rules",
                )
            )
        elif phase_rank >= _PHASE_RANK["understood"] and not review_ready:
            issues.append(
                TraceabilityIssue(
                    code="rule_review_missing",
                    severity="blocker",
                    message=review_blocker,
                    pipeline="aim-review-rules",
                )
            )
        candidate_rules = [rule for rule in rules if rule.status == "candidate"]
        if candidate_rules:
            issues.append(
                TraceabilityIssue(
                    code="rule_candidates_pending",
                    severity="warning",
                    message=f"{len(candidate_rules)} business rule(s) remain candidates",
                    path=candidate_rules[0].path.relative_to(kb_root).as_posix(),
                    pipeline="aim-review-rules",
                )
            )
        missing_rule_sources = [rule for rule in rules if not rule.source_ref]
        if missing_rule_sources:
            issues.append(
                TraceabilityIssue(
                    code="rule_source_missing",
                    severity="warning",
                    message=(
                        f"{len(missing_rule_sources)} business rule(s) lack source citations"
                    ),
                    path=missing_rule_sources[0].path.relative_to(kb_root).as_posix(),
                )
            )
        if phase_rank >= _PHASE_RANK["designed"] and mapping is None:
            issues.append(
                TraceabilityIssue(
                    code="mapping_missing",
                    severity="blocker",
                    message="Target mapping is missing",
                    pipeline="aim-design-unit",
                )
            )
        elif phase_rank >= _PHASE_RANK["designed"]:
            try:
                resolve_verification_command(kb_root, unit_key)
            except VerificationError as exc:
                issues.append(
                    TraceabilityIssue(
                        code="verification_contract_missing",
                        severity="blocker",
                        message=str(exc),
                        path=(
                            mapping.relative_to(kb_root).as_posix()
                            if mapping is not None
                            else None
                        ),
                        pipeline="aim-convert-unit",
                    )
                )
        if phase_rank >= _PHASE_RANK["converted"] and not effective_target_paths:
            issues.append(
                TraceabilityIssue(
                    code="target_artifacts_missing",
                    severity="blocker",
                    message="Converted unit has no recorded target paths",
                    pipeline="aim-convert-unit",
                )
            )
        for target_path in effective_target_paths:
            owners = target_collisions.get(Path(target_path).as_posix())
            if owners:
                issues.append(
                    TraceabilityIssue(
                        code="target_path_collision",
                        severity="blocker",
                        message=(
                            f"Target path {target_path} is owned by "
                            + ", ".join(owners)
                        ),
                        related_units=tuple(
                            owner for owner in owners if owner != unit_key
                        ),
                    )
                )
            target = Path(target_path)
            if target.is_absolute() or ".." in target.parts:
                issues.append(
                    TraceabilityIssue(
                        code="target_path_invalid",
                        severity="blocker",
                        message=f"Target path {target_path} is not repository-relative",
                    )
                )
            elif target_root is not None and not (target_root / target).exists():
                issues.append(
                    TraceabilityIssue(
                        code="target_artifact_not_found",
                        severity=(
                            "blocker"
                            if phase_rank >= _PHASE_RANK["converted"]
                            else "warning"
                        ),
                        message=f"Target artifact {target_path} does not exist locally",
                    )
                )
        latest_compare = compare_runs[0] if compare_runs else None
        if latest_compare is not None and latest_compare.verdict in {"fail", "error"}:
            issues.append(
                TraceabilityIssue(
                    code="compare_failed",
                    severity="blocker",
                    message=f"Latest compare run is {latest_compare.verdict}",
                    related_units=(unit_key,),
                    pipeline="aim-test-compare",
                )
            )
        elif latest_compare is not None and latest_compare.verdict == "acceptable_diff":
            issues.append(
                TraceabilityIssue(
                    code="compare_acceptable_diff",
                    severity="warning",
                    message="Latest compare run has an acceptable difference",
                    related_units=(unit_key,),
                    pipeline="aim-test-compare",
                )
            )
        if phase_rank >= _PHASE_RANK["converted"] and not compare_runs:
            issues.append(
                TraceabilityIssue(
                    code="compare_not_started",
                    severity="warning",
                    message="No compare run is recorded for a converted unit",
                    pipeline="aim-test-compare",
                )
            )
        if phase_rank >= _PHASE_RANK["equivalent"] and passing_compare is None:
            issues.append(
                TraceabilityIssue(
                    code="compare_pass_missing",
                    severity="blocker",
                    message="Passing compare evidence is missing",
                    pipeline="aim-test-compare",
                )
            )
        if passing_compare is not None:
            evidence_time = passing_compare.created_at.timestamp()
            stale_paths: list[str] = []
            if mapping is not None and mapping.stat().st_mtime > evidence_time:
                stale_paths.append(mapping.relative_to(kb_root).as_posix())
            if target_root is not None:
                for target_path in effective_target_paths:
                    target = target_root / target_path
                    if target.exists() and target.stat().st_mtime > evidence_time:
                        stale_paths.append(f"target:{target_path}")
            if stale_paths:
                issues.append(
                    TraceabilityIssue(
                        code="compare_evidence_stale",
                        severity="warning",
                        message=(
                            "Passing compare predates changed artifacts: "
                            + ", ".join(stale_paths)
                        ),
                        related_units=(unit_key,),
                        pipeline="aim-test-compare",
                    )
                )

        for dependency in effective_dependencies:
            dependency_unit = units_by_key.get(dependency)
            if dependency_unit is None:
                issues.append(
                    TraceabilityIssue(
                        code="dependency_missing",
                        severity="blocker",
                        message=f"Dependency {dependency} is missing from the project inventory",
                        related_units=(dependency,),
                    )
                )
                continue
            dependency_state = states.get(dependency)
            dependency_phase = (
                dependency_state[0].phase
                if dependency_state is not None
                else dependency_unit.phase
            )
            dependency_wave = (
                dependency_state[0].wave
                if dependency_state is not None
                else dependency_unit.wave
            )
            required_phase = "cutover" if effective_phase == "cutover" else "converted"
            if (
                phase_rank >= _PHASE_RANK["converted"]
                and _PHASE_RANK.get(dependency_phase, -1) < _PHASE_RANK[required_phase]
            ):
                issues.append(
                    TraceabilityIssue(
                        code="dependency_phase_lag",
                        severity="blocker",
                        message=(
                            f"Dependency {dependency} is {dependency_phase}, "
                            f"not {required_phase}"
                        ),
                        related_units=(dependency,),
                    )
                )
            if (
                effective_wave is not None
                and dependency_wave is not None
                and effective_wave < dependency_wave
            ):
                issues.append(
                    TraceabilityIssue(
                        code="dependency_wave_inversion",
                        severity="warning",
                        message=(
                            f"Dependency {dependency} is scheduled in later wave "
                            f"{dependency_wave}"
                        ),
                        related_units=(dependency,),
                    )
                )
        for cycle in cycles.get(unit_key, []):
            issues.append(
                TraceabilityIssue(
                    code="dependency_cycle",
                    severity="blocker",
                    message="Dependency cycle: " + " → ".join(cycle),
                    related_units=cycle[:-1],
                )
            )

        unit_links = [
            link for link in links if _link_matches_unit(link, unit, unit_key)
        ]
        if phase_rank >= _PHASE_RANK["understood"] and not unit_links:
            issues.append(
                TraceabilityIssue(
                    code="explicit_links_missing",
                    severity="info",
                    message="No explicit traceability links are recorded for this unit",
                )
            )

        action = _next_action(
            kb_root,
            unit_key,
            effective_phase,
            effective_wave,
            rules_reviewed=review_ready,
            claimed_units=claimed_units,
        )
        if action is not None and action.allowed:
            ready_actions += 1
        issues.sort(key=_issue_sort_key)
        issue_counts.update(issue.severity for issue in issues)
        if any(issue.severity in {"blocker", "warning"} for issue in issues):
            at_risk_units += 1
        transitive_dependents = _transitive_dependents(unit_key, reverse_graph)
        rows.append(
            {
                "id": str(unit.id),
                "unit": unit_key,
                "kind": unit.kind,
                "phase": effective_phase,
                "indexed_phase": unit.phase,
                "wave": effective_wave,
                "depends_on": effective_dependencies,
                "target_paths": effective_target_paths,
                "doc_path": (
                    f"modules/{unit.module}/{unit.name}.md"
                    if state is not None
                    else unit.kb_doc_path
                ),
                "mapping_path": (
                    mapping.relative_to(kb_root).as_posix() if mapping else None
                ),
                "rules_reviewed": review_ready,
                "rules": [rule.to_dict() for rule in rule_items],
                "run_count": len(unit_runs),
                "passing_run_id": str(passing_compare.id) if passing_compare else None,
                "latest_verdict": unit_runs[0].verdict if unit_runs else None,
                "dependent_units": sorted(reverse_graph.get(unit_key, set())),
                "impact_count": len(transitive_dependents),
                "next_action": action.to_dict() if action is not None else None,
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
                "issues": [issue.to_dict() for issue in issues],
                "gaps": [
                    issue.message
                    for issue in issues
                    if issue.severity in {"blocker", "warning"}
                ],
            }
        )

    project_issues.sort(key=_issue_sort_key)
    issue_counts.update(issue.severity for issue in project_issues)
    return {
        "summary": {
            "total_units": len(units),
            "reviewed_units": reviewed_units,
            "mapped_units": mapped_units,
            "evidenced_units": evidenced_units,
            "total_rules": total_rules,
            "confirmed_rules": confirmed_rules,
            "explicit_links": len(links),
            "total_gaps": issue_counts["blocker"] + issue_counts["warning"],
            "blocker_count": issue_counts["blocker"],
            "warning_count": issue_counts["warning"],
            "info_count": issue_counts["info"],
            "at_risk_units": at_risk_units,
            "ready_actions": ready_actions,
            "project_issue_count": len(project_issues),
        },
        "project_issues": [issue.to_dict() for issue in project_issues],
        "units": rows,
    }
