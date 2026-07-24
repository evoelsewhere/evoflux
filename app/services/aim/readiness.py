"""Authoritative readiness policy for AIM unit phase transitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.aim import kb_store
from app.services.aim.models import VALID_PHASES, next_unit_phase

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
                selected.append(unit_key)
                if pipeline == "aim-understand":
                    if frontmatter.phase != "inventory":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not inventory"
                        )
                    blockers.extend(
                        _dependency_blockers(kb_root, frontmatter.depends_on)
                    )
                elif pipeline == "aim-design-unit":
                    if frontmatter.phase != "understood":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not understood"
                        )
                    if not body.strip():
                        blockers.append("unit documentation body is empty")
                    conventions = kb_root / "target-conventions.md"
                    if (
                        not conventions.is_file()
                        or not conventions.read_text(encoding="utf-8").strip()
                    ):
                        warnings.append("target-conventions.md is empty or missing")
                elif pipeline == "aim-convert-unit":
                    if frontmatter.phase != "designed":
                        blockers.append(
                            f"unit {unit_key} is {frontmatter.phase}, not designed"
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
                else:
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
            selected.extend(f"{module}/{name}" for module, name, _ in wave_units)
            if not wave_units:
                blockers.append(f"wave {wave} has no designed units")
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
                for dependency in frontmatter.depends_on:
                    dependency_result = _unit_result(kb_root, dependency)
                    if dependency_result is None or dependency_result[2] is None:
                        blockers.append(
                            f"unit {module}/{name} dependency {dependency} is missing"
                        )
                        continue
                    dependency_phase = dependency_result[2][0].phase
                    if _PHASE_RANK.get(dependency_phase, -1) < _PHASE_RANK["converted"]:
                        blockers.append(
                            f"unit {module}/{name} dependency {dependency} is "
                            f"{dependency_phase}, not converted"
                        )
    elif pipeline == "aim-cutover-check":
        if wave is None:
            blockers.append("wave is required")
        else:
            wave_units = [
                (module, name, frontmatter)
                for module, name, frontmatter, _ in units
                if frontmatter.wave == wave
            ]
            selected.extend(f"{module}/{name}" for module, name, _ in wave_units)
            if not wave_units:
                blockers.append(f"wave {wave} has no units")
            for module, name, frontmatter in wave_units:
                if frontmatter.phase not in {"equivalent", "cutover"}:
                    blockers.append(
                        f"wave {wave} unit {module}/{name} is {frontmatter.phase}, "
                        "not equivalent"
                    )
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
        blockers.extend(_dependency_blockers(kb_root, frontmatter.depends_on))
    elif target_phase == "designed":
        if not _mapping_exists(kb_root, module, name):
            blockers.append("target mapping is missing")
    elif target_phase == "converted":
        if not frontmatter.target_paths:
            blockers.append("target_paths is empty")
        if not conversion_verified:
            blockers.append("passing target verification evidence is missing")
    elif target_phase == "equivalent":
        if not compare_pass:
            blockers.append("passing compare evidence is missing")
    elif target_phase == "cutover":
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
