from pathlib import Path

from app.services.aim.kb_store import write_cutover_checklist, write_unit
from app.services.aim.models import CutoverChecklist
from app.services.aim.readiness import evaluate_pipeline, evaluate_transition


def test_transition_rejects_phase_skip(tmp_path: Path):
    write_unit(tmp_path, "core", "PAY", kind="program", phase="inventory")

    result = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "converted",
        workflow_name="aim-convert-unit",
    )

    assert not result.allowed
    assert any("inventory -> converted" in blocker for blocker in result.blockers)


def test_understand_requires_document_and_owning_workflow(tmp_path: Path):
    write_unit(tmp_path, "core", "PAY", kind="program", phase="inventory")

    missing_doc = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "understood",
        workflow_name="aim-understand",
    )
    wrong_workflow = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "understood",
        workflow_name="aim-convert-unit",
    )

    assert not missing_doc.allowed
    assert "unit documentation body is empty" in missing_doc.blockers
    assert not wrong_workflow.allowed
    assert any("aim-understand" in blocker for blocker in wrong_workflow.blockers)


def test_understand_requires_ready_dependencies(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        depends_on=["shared/DATE"],
        body="Documented payroll behavior.",
    )
    write_unit(tmp_path, "shared", "DATE", kind="utility", phase="inventory")

    result = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "understood",
        workflow_name="aim-understand",
    )

    assert not result.allowed
    assert any("shared/DATE" in blocker for blocker in result.blockers)


def test_design_requires_mapping(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented payroll behavior.",
    )

    missing = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "designed",
        workflow_name="aim-design-unit",
    )
    mapping = tmp_path / "mapping" / "core" / "PAY.md"
    mapping.parent.mkdir(parents=True)
    mapping.write_text("# Target mapping\n")
    ready = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "designed",
        workflow_name="aim-design-unit",
    )

    assert not missing.allowed
    assert "target mapping is missing" in missing.blockers
    assert ready.allowed


def test_convert_requires_target_paths(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="designed",
        body="Documented payroll behavior.",
    )

    result = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "converted",
        workflow_name="aim-convert-unit",
    )

    assert not result.allowed
    assert "target_paths is empty" in result.blockers
    assert "passing target verification evidence is missing" in result.blockers


def test_equivalent_requires_pass_from_same_attempt(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.java"],
    )

    missing = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "equivalent",
        workflow_name="aim-test-compare",
        compare_pass=False,
    )
    ready = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "equivalent",
        workflow_name="aim-test-compare",
        compare_pass=True,
    )

    assert not missing.allowed
    assert "passing compare evidence is missing" in missing.blockers
    assert ready.allowed


def test_cutover_requires_entire_wave_ready(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        wave=1,
    )
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="converted",
        wave=1,
        target_paths=["src/Tax.java"],
    )

    result = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "cutover",
        workflow_name="aim-cutover-check",
    )

    assert not result.allowed
    assert any("core/TAX" in blocker for blocker in result.blockers)


def test_understand_pipeline_blocks_until_dependencies_are_understood(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        depends_on=["shared/DATE"],
    )
    write_unit(tmp_path, "shared", "DATE", kind="utility", phase="inventory")

    result = evaluate_pipeline(tmp_path, "aim-understand", unit="core/PAY")

    assert not result.allowed
    assert any("shared/DATE" in blocker for blocker in result.blockers)


def test_convert_wave_pipeline_requires_designed_units(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        wave=2,
    )

    result = evaluate_pipeline(tmp_path, "aim-convert-wave", wave=2)

    assert not result.allowed
    assert "wave 2 has no designed units" in result.blockers


def test_rulebook_capability_blocks_unavailable_pipeline(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: cobol-java21, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 2\n"
    )
    (tmp_path / "rulebook").mkdir()
    (tmp_path / "rulebook" / "rulebook.yaml").write_text(
        "id: cobol-java21\n"
        "version: '0.1'\n"
        "capabilities:\n"
        "  design: unavailable\n"
    )
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented behavior.",
    )

    result = evaluate_pipeline(tmp_path, "aim-design-unit", unit="core/PAY")

    assert not result.allowed
    assert "rulebook capability design is unavailable" in result.blockers


def test_legacy_state_schema_blocks_lifecycle_pipeline(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: java8-java21, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 1\n"
    )
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
    )

    result = evaluate_pipeline(tmp_path, "aim-understand", unit="core/PAY")

    assert not result.allowed
    assert (
        "legacy state schema must be reconciled before lifecycle work"
        in result.blockers
    )


def test_compare_pipeline_requires_valid_golden_case(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.java"],
    )

    result = evaluate_pipeline(
        tmp_path,
        "aim-test-compare",
        unit="core/PAY",
        case_set="smoke",
    )

    assert not result.allowed
    assert any("golden case" in blocker for blocker in result.blockers)


def test_cutover_pipeline_blocks_incomplete_wave(tmp_path: Path):
    write_unit(tmp_path, "core", "PAY", kind="program", phase="equivalent", wave=1)
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="converted",
        wave=1,
        target_paths=["src/Tax.java"],
    )

    result = evaluate_pipeline(tmp_path, "aim-cutover-check", wave=1)

    assert not result.allowed
    assert any("core/TAX" in blocker for blocker in result.blockers)


def test_cutover_pipeline_requires_operational_checklist(tmp_path: Path):
    write_unit(tmp_path, "core", "PAY", kind="program", phase="equivalent", wave=1)

    missing = evaluate_pipeline(tmp_path, "aim-cutover-check", wave=1)
    write_cutover_checklist(
        tmp_path,
        CutoverChecklist(
            wave=1,
            deployment_ready=True,
            data_reconciled=True,
            rollback_ready=True,
            monitoring_ready=True,
            approved_by="release-manager",
        ),
    )
    ready = evaluate_pipeline(tmp_path, "aim-cutover-check", wave=1)

    assert not missing.allowed
    assert any("cutover checklist" in blocker for blocker in missing.blockers)
    assert ready.allowed
