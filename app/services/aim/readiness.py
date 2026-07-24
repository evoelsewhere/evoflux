"""Authoritative readiness policy for AIM unit phase transitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.aim import kb_store
from app.services.aim.models import UnitFrontmatter, VALID_PHASES, next_unit_phase

_PHASE_RANK = {phase: index for index, phase in enumerate(VALID_PHASES)}

_TRANSITION_WORKFLOWS: dict[str, frozenset[str]] = {
    "understood": frozenset({"aim-understand"}),
    "designed": frozenset({"aim-design-unit"}),
    "converted": frozenset({"aim-convert-unit", "aim-convert-wave"}),
    "equivalent": frozenset({"aim-test-compare"}),
    "cutover": frozenset({"aim-cutover-check"}),
}


@dataclass(frozen=True, slots=True)
class TransitionReadiness:
    unit: str
    current_phase: str
    target_phase: str
    required_workflows: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "current_phase": self.current_phase,
            "target_phase": self.target_phase,
            "allowed": self.allowed,
            "required_workflows": list(self.required_workflows),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class PipelineReadiness:
    pipeline: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    selected_units: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.blockers

    @property
    def status(self) -> str:
        return "ready" if self.allowed else "blocked"

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "status": self.status,
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "selected_units": list(self.selected_units),
            "selected_count": len(self.selected_units),
        }


def resolve_mapping_path(kb_root: Path, module: str, name: str) -> Path | None:
    candidates = (
        kb_root / "mapping" / module / f"{name}.md",
        kb_root / "mapping" / f"{module}-{name}.md",
        kb_root / "mapping" / f"{name}.md",
    )
    return next(
        (path for path in candidates if path.is_file() and path.stat().st_size > 0),
        None,
    )


def _mapping_exists(kb_root: Path, module: str, name: str) -> bool:
    return resolve_mapping_path(kb_root, module, name) is not None


def _dependency_blockers(kb_root: Path, dependencies: list[str]) -> list[str]:
    blockers: list[str] = []
    for dependency in dependencies:
        if "/" not in dependency:
            blockers.append(f"dependency {dependency!r} is not a module/name key")
            continue
        module, name = dependency.split("/", 1)
        result = kb_store.read_unit(kb_root, module, name)
        if result is None:
            blockers.append(f"dependency {dependency} is missing from the KB")
            continue
        frontmatter, body = result
        if _PHASE_RANK.get(frontmatter.phase, -1) < _PHASE_RANK["understood"]:
            blockers.append(
                f"dependency {dependency} is {frontmatter.phase}, not understood"
            )
        elif not body.strip():
            blockers.append(f"dependency {dependency} documentation body is empty")
    return blockers


def _dependency_phase_blockers(
    kb_root: Path, dependencies: list[str], required_phase: str
) -> list[str]:
    blockers: list[str] = []
    required_rank = _PHASE_RANK[required_phase]
    for dependency in dependencies:
        if "/" not in dependency:
            blockers.append(f"dependency {dependency!r} is not a module/name key")
            continue
        module, name = dependency.split("/", 1)
        result = kb_store.read_unit(kb_root, module, name)
        if result is None:
            blockers.append(f"dependency {dependency} is missing from the KB")
            continue
        dependency_phase = result[0].phase
        if _PHASE_RANK.get(dependency_phase, -1) < required_rank:
            blockers.append(
                f"dependency {dependency} is {dependency_phase}, not {required_phase}"
            )
    return blockers


def _conversion_wave_order(
    kb_root: Path, wave_units: list[tuple[str, str, UnitFrontmatter]]
) -> tuple[list[str], list[str]]:
    selected = {
        f"{module}/{name}": frontmatter for module, name, frontmatter in wave_units
    }
    ordered: list[str] = []
    blockers: list[str] = []
    visited: set[str] = set()
    active: list[str] = []

    def visit(unit_key: str) -> None:
        if unit_key in active:
            cycle_start = active.index(unit_key)
            cycle = active[cycle_start:] + [unit_key]
            blocker = "conversion dependency cycle: " + " -> ".join(cycle)
            if blocker not in blockers:
                blockers.append(blocker)
            return
        if unit_key in visited:
            return
        active.append(unit_key)
        frontmatter = selected[unit_key]
        for dependency in frontmatter.depends_on:
            if dependency in selected:
                visit(dependency)
            else:
                blockers.extend(
                    _dependency_phase_blockers(kb_root, [dependency], "converted")
                )
        active.pop()
        visited.add(unit_key)
        ordered.append(unit_key)

    for unit_key in selected:
        visit(unit_key)
    return ordered, list(dict.fromkeys(blockers))


def _cutover_wave_order(
    kb_root: Path, wave_units: list[tuple[str, str, UnitFrontmatter]]
) -> tuple[list[str], list[str]]:
    all_wave = {
        f"{module}/{name}": frontmatter for module, name, frontmatter in wave_units
    }
    remaining = {
        unit_key: frontmatter
        for unit_key, frontmatter in all_wave.items()
        if frontmatter.phase == "equivalent"
    }
    ordered: list[str] = []
    blockers: list[str] = []
    visited: set[str] = set()
    active: list[str] = []

    def visit(unit_key: str) -> None:
        if unit_key in active:
            cycle_start = active.index(unit_key)
            cycle = active[cycle_start:] + [unit_key]
            blocker = "cutover dependency cycle: " + " -> ".join(cycle)
            if blocker not in blockers:
                blockers.append(blocker)
            return
        if unit_key in visited:
            return
        active.append(unit_key)
        frontmatter = remaining[unit_key]
        for dependency in frontmatter.depends_on:
            if dependency in remaining:
                visit(dependency)
            elif dependency in all_wave:
                dependency_phase = all_wave[dependency].phase
                if dependency_phase != "cutover":
                    blockers.append(
                        f"dependency {dependency} is {dependency_phase}, not cutover"
                    )
            else:
                blockers.extend(
                    _dependency_phase_blockers(kb_root, [dependency], "cutover")
                )
        active.pop()
        visited.add(unit_key)
        ordered.append(unit_key)

    for unit_key in remaining:
        visit(unit_key)
    return ordered, list(dict.fromkeys(blockers))


def _understand_dependency_closure(
    kb_root: Path, unit: str
) -> tuple[list[str], list[str]]:
    """Return unresolved dependencies before ``unit`` in topological order."""
    ordered: list[str] = []
    blockers: list[str] = []
    visited: set[str] = set()
    active: list[str] = []

    def visit(unit_key: str) -> None:
        if unit_key in active:
            cycle_start = active.index(unit_key)
            cycle = active[cycle_start:] + [unit_key]
            blocker = "dependency cycle: " + " -> ".join(cycle)
            if blocker not in blockers:
                blockers.append(blocker)
            return
        if unit_key in visited:
            return
        if "/" not in unit_key:
            blockers.append(f"dependency {unit_key!r} is not a module/name key")
            return

        module, name = unit_key.split("/", 1)
        result = kb_store.read_unit(kb_root, module, name)
        if result is None:
            blockers.append(f"dependency {unit_key} is missing from the KB")
            return
        frontmatter, body = result
        phase_rank = _PHASE_RANK.get(frontmatter.phase, -1)
        if phase_rank >= _PHASE_RANK["understood"]:
            if not body.strip():
                blockers.append(f"dependency {unit_key} documentation body is empty")
            visited.add(unit_key)
            return
        if frontmatter.phase != "inventory":
            blockers.append(
                f"dependency {unit_key} has unsupported phase {frontmatter.phase!r}"
            )
            return

        active.append(unit_key)
        for dependency in frontmatter.depends_on:
            visit(dependency)
        active.pop()
        visited.add(unit_key)
        ordered.append(unit_key)

    visit(unit)
    return ordered, blockers


def _unit_result(kb_root: Path, unit: str | None):
    if not unit or "/" not in unit:
        return None
    module, name = unit.split("/", 1)
    return module, name, kb_store.read_unit(kb_root, module, name)


def evaluate_pipeline(
    kb_root: Path,
    pipeline: str,
    *,
    unit: str | None = None,
    wave: int | None = None,
    case_set: str | None = None,
) -> PipelineReadiness:
    """Evaluate whether a builtin AIM pipeline may be started now."""
    blockers: list[str] = []
    warnings: list[str] = []
    selected: list[str] = []
    units = kb_store.list_units(kb_root)

    if pipeline != "aim-assess" and (kb_root / "aim.yaml").is_file():
        manifest_state = kb_store.read_manifest(kb_root)
        if manifest_state.state_schema < 2:
            blockers.append(
                "legacy state schema must be reconciled before lifecycle work"
            )

    capability_by_pipeline = {
        "aim-assess": "inventory",
        "aim-understand": "understand",
        "aim-design-unit": "design",
        "aim-convert-unit": "convert",
        "aim-convert-wave": "convert",
        "aim-capture-golden": "compare",
        "aim-capture-golden-contract": "compare",
        "aim-test-compare": "compare",
        "aim-cutover-check": "cutover",
    }
    capability = capability_by_pipeline.get(pipeline)
    if capability and (kb_root / "aim.yaml").is_file():
        from app.services.aim.rulebook import validate_rulebook_identity

        try:
            pack_manifest = validate_rulebook_identity(kb_root).model_dump()
        except (FileNotFoundError, ValueError):
            pack_manifest = {}
        capabilities = pack_manifest.get("capabilities")
        maturity = (
            capabilities.get(capability) if isinstance(capabilities, dict) else None
        )
        if maturity != "ready":
            blockers.append(
                f"rulebook capability {capability} is {maturity or 'undeclared'}"
            )

    if pipeline == "aim-assess":
        if units:
            warnings.append(f"assessment will refresh {len(units)} existing units")
    elif pipeline in {
        "aim-understand",
        "aim-design-unit",
        "aim-convert-unit",
        "aim-capture-golden",
        "aim-capture-golden-contract",
        "aim-test-compare",
    }:
        resolved = _unit_result(kb_root, unit)
        if resolved is None:
            blockers.append("unit must be a module/name key")
        else:
            module, name, result = resolved
            unit_key = f"{module}/{name}"
            if result is None:
                blockers.append(f"unit {unit_key} does not exist in the KB")
            else:
                frontmatter, body = result
                if pipeline == "aim-understand":
                    if frontmatter.phase != "inventory":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not inventory"
                        )
                    else:
                        closure, closure_blockers = _understand_dependency_closure(
                            kb_root, unit_key
                        )
                        selected.extend(closure)
                        blockers.extend(closure_blockers)
                elif pipeline == "aim-design-unit":
                    selected.append(unit_key)
                    if frontmatter.phase != "understood":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not understood"
                        )
                    if not body.strip():
                        blockers.append("unit documentation body is empty")
                    conventions = kb_root / "target-conventions.md"
                    if not conventions.is_file():
                        blockers.append("target-conventions.md is missing")
                    else:
                        convention_text = conventions.read_text(
                            encoding="utf-8"
                        ).strip()
                        if not convention_text:
                            blockers.append("target-conventions.md is empty")
                        elif "baseline pending" in convention_text.lower():
                            blockers.append("target-conventions.md baseline is pending")
                elif pipeline == "aim-convert-unit":
                    selected.append(unit_key)
                    if frontmatter.phase != "designed":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not designed"
                        )
                    blockers.extend(
                        _dependency_phase_blockers(
                            kb_root, frontmatter.depends_on, "converted"
                        )
                    )
                    if not _mapping_exists(kb_root, module, name):
                        blockers.append("target mapping is missing")
                    from app.services.aim.verification import (
                        VerificationError,
                        resolve_verification_command,
                    )

                    try:
                        resolve_verification_command(kb_root, unit_key)
                    except VerificationError as exc:
                        blockers.append(str(exc))
                elif pipeline in {
                    "aim-capture-golden",
                    "aim-capture-golden-contract",
                }:
                    selected.append(unit_key)
                    if (
                        _PHASE_RANK.get(frontmatter.phase, -1)
                        < _PHASE_RANK["understood"]
                    ):
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not understood"
                        )
                    selected_case_set = case_set or "smoke"
                    case_dir = (
                        kb_root
                        / "golden"
                        / "units"
                        / module
                        / name
                        / "cases"
                        / selected_case_set
                    )
                    contract_issues: list[str] = []
                    if not (case_dir / "input").is_dir():
                        contract_issues.append(
                            f"golden case {selected_case_set!r} has no input directory"
                        )
                    if not (case_dir / "legacy.command").is_file():
                        contract_issues.append(
                            f"golden case {selected_case_set!r} has no legacy.command"
                        )
                    if not (case_dir / "target.command").is_file():
                        contract_issues.append(
                            f"golden case {selected_case_set!r} has no target.command"
                        )
                    from app.services.aim.golden import (
                        GoldenCaseError,
                        load_golden_case_meta,
                    )

                    try:
                        load_golden_case_meta(case_dir)
                    except GoldenCaseError as exc:
                        contract_issues.append(str(exc))
                    if pipeline == "aim-capture-golden-contract":
                        blockers.extend(contract_issues)
                    else:
                        warnings.extend(
                            f"case contract pending: {issue}"
                            for issue in contract_issues
                        )
                    from app.services.aim.runners import (
                        RunnerExecutionError,
                        resolve_legacy_runner,
                    )

                    try:
                        resolve_legacy_runner(kb_root)
                    except RunnerExecutionError as exc:
                        blockers.append(str(exc))
                else:
                    selected.append(unit_key)
                    if frontmatter.phase != "converted":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not converted"
                        )
                    selected_case_set = case_set or "smoke"
                    case_dir = (
                        kb_root
                        / "golden"
                        / "units"
                        / module
                        / name
                        / "cases"
                        / selected_case_set
                    )
                    if not (case_dir / "input").is_dir():
                        blockers.append(
                            f"golden case {selected_case_set!r} has no input directory"
                        )
                    if not (case_dir / "target.command").is_file():
                        blockers.append(
                            f"golden case {selected_case_set!r} has no target.command"
                        )
                    expected_dir = case_dir / "expected"
                    if not expected_dir.is_dir() or not any(
                        path.is_file() for path in expected_dir.rglob("*")
                    ):
                        blockers.append(
                            f"golden case {selected_case_set!r} has no expected output"
                        )
                    else:
                        from app.services.aim.golden import (
                            GoldenCaseError,
                            load_golden_case_meta,
                        )

                        try:
                            load_golden_case_meta(case_dir)
                        except GoldenCaseError as exc:
                            blockers.append(str(exc))
                    from app.services.aim.runners import (
                        RunnerExecutionError,
                        resolve_target_runner,
                    )

                    try:
                        resolve_target_runner(kb_root)
                    except RunnerExecutionError as exc:
                        blockers.append(str(exc))
    elif pipeline == "aim-convert-wave":
        if wave is None:
            blockers.append("wave is required")
        else:
            wave_units = [
                (module, name, frontmatter)
                for module, name, frontmatter, _ in units
                if frontmatter.wave == wave and frontmatter.phase == "designed"
            ]
            if not wave_units:
                blockers.append(f"wave {wave} has no designed units")
            ordered_units, dependency_blockers = _conversion_wave_order(
                kb_root, wave_units
            )
            selected.extend(ordered_units)
            blockers.extend(dependency_blockers)
            for module, name, frontmatter in wave_units:
                if not _mapping_exists(kb_root, module, name):
                    blockers.append(f"unit {module}/{name} target mapping is missing")
                from app.services.aim.verification import (
                    VerificationError,
                    resolve_verification_command,
                )

                try:
                    resolve_verification_command(kb_root, f"{module}/{name}")
                except VerificationError as exc:
                    blockers.append(f"unit {module}/{name}: {exc}")
    elif pipeline == "aim-cutover-check":
        if wave is None:
            blockers.append("wave is required")
        else:
            wave_units = [
                (module, name, frontmatter)
                for module, name, frontmatter, _ in units
                if frontmatter.wave == wave
            ]
            if not wave_units:
                blockers.append(f"wave {wave} has no units")
            for module, name, frontmatter in wave_units:
                if frontmatter.phase not in {"equivalent", "cutover"}:
                    blockers.append(
                        f"wave {wave} unit {module}/{name} is {frontmatter.phase}, "
                        "not equivalent"
                    )
            ordered_units, dependency_blockers = _cutover_wave_order(
                kb_root, wave_units
            )
            selected.extend(ordered_units)
            blockers.extend(dependency_blockers)
            if (
                wave_units
                and not ordered_units
                and all(
                    frontmatter.phase == "cutover" for _, _, frontmatter in wave_units
                )
            ):
                blockers.append(f"wave {wave} is already cut over")
            checklist = kb_store.read_cutover_checklist(kb_root, wave)
            if checklist is None:
                blockers.append(f"wave {wave} cutover checklist is missing")
            else:
                blockers.extend(checklist.blockers())
    else:
        warnings.append(
            "custom workflow has no declared AIM readiness policy; runtime "
            "tool permissions still apply"
        )

    return PipelineReadiness(
        pipeline=pipeline,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        selected_units=tuple(selected),
    )


def evaluate_transition(
    kb_root: Path,
    module: str,
    name: str,
    target_phase: str,
    *,
    workflow_name: str | None,
    understanding_verified: bool = False,
    compare_pass: bool = False,
    conversion_verified: bool = False,
) -> TransitionReadiness:
    """Evaluate one requested unit transition without mutating state."""
    unit_key = f"{module}/{name}"
    result = kb_store.read_unit(kb_root, module, name)
    if result is None:
        return TransitionReadiness(
            unit=unit_key,
            current_phase="missing",
            target_phase=target_phase,
            required_workflows=(),
            blockers=("unit does not exist in the KB",),
        )

    frontmatter, body = result
    current_phase = frontmatter.phase
    required = tuple(sorted(_TRANSITION_WORKFLOWS.get(target_phase, ())))
    blockers: list[str] = []

    expected_phase = next_unit_phase(current_phase)
    if target_phase != expected_phase:
        blockers.append(
            f"illegal phase transition {current_phase} -> {target_phase}; "
            f"expected {expected_phase or 'no further phase'}"
        )

    if required and workflow_name not in required:
        owners = " or ".join(required)
        blockers.append(f"transition to {target_phase} must run through {owners}")

    if target_phase == "understood":
        if not body.strip():
            blockers.append("unit documentation body is empty")
        if not understanding_verified:
            blockers.append("same-attempt understanding evidence is missing")
        blockers.extend(_dependency_blockers(kb_root, frontmatter.depends_on))
    elif target_phase == "designed":
        if not _mapping_exists(kb_root, module, name):
            blockers.append("target mapping is missing")
        from app.services.aim.verification import (
            VerificationError,
            resolve_verification_command,
        )

        try:
            resolve_verification_command(kb_root, unit_key)
        except VerificationError as exc:
            blockers.append(str(exc))
    elif target_phase == "converted":
        blockers.extend(
            _dependency_phase_blockers(kb_root, frontmatter.depends_on, "converted")
        )
        if not frontmatter.target_paths:
            blockers.append("target_paths is empty")
        if not conversion_verified:
            blockers.append("passing target verification evidence is missing")
    elif target_phase == "equivalent":
        if not compare_pass:
            blockers.append("passing compare evidence is missing")
    elif target_phase == "cutover":
        blockers.extend(
            _dependency_phase_blockers(kb_root, frontmatter.depends_on, "cutover")
        )
        if frontmatter.wave is None:
            blockers.append("unit has no wave assignment")
        else:
            wave_units = [
                (u_module, u_name, unit)
                for u_module, u_name, unit, _ in kb_store.list_units(kb_root)
                if unit.wave == frontmatter.wave
            ]
            if not wave_units:
                blockers.append(f"wave {frontmatter.wave} has no units")
            for u_module, u_name, unit in wave_units:
                if unit.phase not in {"equivalent", "cutover"}:
                    blockers.append(
                        f"wave {frontmatter.wave} unit {u_module}/{u_name} is "
                        f"{unit.phase}, not equivalent"
                    )
            checklist = kb_store.read_cutover_checklist(kb_root, frontmatter.wave)
            if checklist is None:
                blockers.append(f"wave {frontmatter.wave} cutover checklist is missing")
            else:
                blockers.extend(checklist.blockers())

    return TransitionReadiness(
        unit=unit_key,
        current_phase=current_phase,
        target_phase=target_phase,
        required_workflows=required,
        blockers=tuple(blockers),
    )


def next_action_readiness(
    kb_root: Path,
    module: str,
    name: str,
    *,
    compare_pass: bool = False,
) -> TransitionReadiness | None:
    """Readiness for the unit's next legal transition, for API/UI use."""
    result = kb_store.read_unit(kb_root, module, name)
    if result is None:
        return None
    target_phase = next_unit_phase(result[0].phase)
    if target_phase is None:
        return None
    workflows = _TRANSITION_WORKFLOWS.get(target_phase, frozenset())
    workflow_name = sorted(workflows)[0] if workflows else None
    return evaluate_transition(
        kb_root,
        module,
        name,
        target_phase,
        workflow_name=workflow_name,
        compare_pass=compare_pass,
    )
