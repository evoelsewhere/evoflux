from pathlib import Path

from app.services.aim.kb_store import write_unit
from app.services.aim.suggestions import (
    build_suggestion_plan,
    read_suggestion_snapshot,
    write_suggestion_snapshot,
)


def _action(plan, action_id: str):
    return next(action for action in plan.actions if action.id == action_id)


def _write_mapping_contract(kb_root: Path, unit: str) -> None:
    module, name = unit.split("/", 1)
    mapping = kb_root / "mapping" / module / f"{name}.md"
    mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_text("# Target mapping\n", encoding="utf-8")
    mapping.with_suffix(".verify.command").write_text("true\n", encoding="utf-8")


def test_plan_discloses_understand_closure_without_same_wave_sibling(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        wave=2,
        depends_on=["shared/DATE"],
    )
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="inventory",
        wave=2,
    )
    write_unit(
        tmp_path,
        "shared",
        "DATE",
        kind="utility",
        phase="inventory",
        wave=0,
    )

    plan = build_suggestion_plan(tmp_path)
    action = _action(plan, "aim-understand:core/PAY")
    dependency = _action(plan, "aim-understand:shared/DATE")

    assert action.lane == "up_next"
    assert action.scope_units == ("shared/DATE", "core/PAY")
    assert "core/TAX" not in action.scope_units
    assert dependency.lane == "ready"
    assert "aim-understand:shared/DATE" in action.blockers[0]


def test_plan_inserts_rule_review_before_design(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented behavior.",
    )

    plan = build_suggestion_plan(tmp_path)
    action = _action(plan, "aim-review-rules:core/PAY")

    assert action.pipeline == "aim-review-rules"
    assert action.lane == "ready"


def test_plan_suggests_golden_capture_when_compare_baseline_is_missing(
    tmp_path: Path,
):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.java"],
        body="Documented behavior.",
    )

    plan = build_suggestion_plan(tmp_path)
    action = _action(plan, "aim-capture-golden:core/PAY")

    assert action.pipeline == "aim-capture-golden"
    assert "baseline" in action.reason


def test_plan_marks_dependency_only_conversion_blocker_as_up_next(tmp_path: Path):
    write_unit(tmp_path, "shared", "DATE", kind="utility", phase="designed")
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="designed",
        depends_on=["shared/DATE"],
    )
    _write_mapping_contract(tmp_path, "core/PAY")

    plan = build_suggestion_plan(tmp_path)
    action = _action(plan, "aim-convert-unit:core/PAY")

    assert action.lane == "up_next"
    assert action.blockers == ("dependency shared/DATE is designed, not converted",)


def test_plan_groups_cutover_by_wave_and_requires_operator_input(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        wave=4,
    )
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="equivalent",
        wave=4,
    )

    plan = build_suggestion_plan(tmp_path)
    action = _action(plan, "aim-cutover-check:wave:4")

    assert action.scope_units == ("core/PAY", "core/TAX")
    assert action.lane == "needs_input"
    assert "cutover checklist is missing" in action.blockers[0]


def test_snapshot_fingerprint_detects_lifecycle_change(tmp_path: Path):
    write_unit(tmp_path, "core", "PAY", kind="program", phase="inventory")
    original = build_suggestion_plan(tmp_path)

    path = write_suggestion_snapshot(tmp_path, original, generated_by="test")
    snapshot = read_suggestion_snapshot(tmp_path)
    write_unit(
        tmp_path,
        "core",
        "PAY",
        phase="understood",
        body="Documented behavior.",
    )
    current = build_suggestion_plan(tmp_path)

    assert path.is_file()
    assert snapshot is not None
    assert snapshot["fingerprint"] == original.fingerprint
    assert current.fingerprint != original.fingerprint
