from pathlib import Path
from uuid import uuid4

import pytest

from app.services.aim import kb_store
from app.services.aim.kb_store import write_cutover_checklist, write_unit
from app.services.aim.business_rules import confirm_no_business_rules
from app.services.aim.golden import stamp_expected_integrity
from app.services.aim.models import CutoverChecklist
from app.services.aim.readiness import (
    evaluate_pipeline,
    evaluate_pipeline_options,
    evaluate_transition,
)


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
        understanding_verified=True,
    )
    wrong_workflow = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "understood",
        workflow_name="aim-convert-unit",
        understanding_verified=True,
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
        understanding_verified=True,
    )

    assert not result.allowed
    assert any("shared/DATE" in blocker for blocker in result.blockers)


def test_understand_transition_requires_same_attempt_evidence(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        body="Documented behavior.",
    )

    result = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "understood",
        workflow_name="aim-understand",
    )

    assert not result.allowed
    assert "same-attempt understanding evidence is missing" in result.blockers


def test_design_requires_mapping_and_verification_command(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented payroll behavior.",
    )
    (tmp_path / "target-conventions.md").write_text("# Approved conventions\n")
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))

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
    missing_command = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "designed",
        workflow_name="aim-design-unit",
    )
    mapping.with_suffix(".verify.command").write_text("true\n")
    ready = evaluate_transition(
        tmp_path,
        "core",
        "PAY",
        "designed",
        workflow_name="aim-design-unit",
    )

    assert not missing.allowed
    assert "target mapping is missing" in missing.blockers
    assert not missing_command.allowed
    assert any(
        "verification command is missing" in blocker
        for blocker in missing_command.blockers
    )
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
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))

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


def test_understand_pipeline_expands_unresolved_dependencies(tmp_path: Path):
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

    assert result.allowed
    assert result.selected_units == ("shared/DATE", "core/PAY")
    assert result.primary_unit == "core/PAY"
    assert result.included_dependencies == ("shared/DATE",)


def test_understand_pipeline_skips_already_understood_dependencies(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        depends_on=["shared/DATE"],
    )
    write_unit(
        tmp_path,
        "shared",
        "DATE",
        kind="utility",
        phase="understood",
        body="Documented date behavior.",
    )

    result = evaluate_pipeline(tmp_path, "aim-understand", unit="core/PAY")

    assert result.allowed
    assert result.selected_units == ("core/PAY",)
    assert result.included_dependencies == ()


def test_understand_pipeline_excludes_same_wave_siblings(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        wave=3,
    )
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="inventory",
        wave=3,
    )

    result = evaluate_pipeline(tmp_path, "aim-understand", unit="core/PAY")

    assert result.allowed
    assert result.selected_units == ("core/PAY",)


def test_understand_options_only_include_unblocked_unclaimed_units(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        wave=3,
        depends_on=["shared/DATE"],
    )
    write_unit(
        tmp_path,
        "core",
        "TAX",
        kind="program",
        phase="inventory",
        wave=3,
    )
    write_unit(
        tmp_path,
        "shared",
        "DATE",
        kind="utility",
        phase="inventory",
        wave=1,
    )

    options = evaluate_pipeline_options(
        tmp_path,
        "aim-understand",
        claimed_units=frozenset({"core/TAX"}),
    )

    assert options.units == ("core/PAY", "shared/DATE")
    assert options.waves == ()


def test_pipeline_options_scans_unit_inventory_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    for name in ("PAY", "TAX", "DATE"):
        write_unit(
            tmp_path,
            "core",
            name,
            kind="program",
            phase="inventory",
            body="Documented behavior.",
        )

    original = kb_store.list_units
    calls = 0

    def counted(kb_root: Path):
        nonlocal calls
        calls += 1
        return original(kb_root)

    monkeypatch.setattr(kb_store, "list_units", counted)

    options = evaluate_pipeline_options(tmp_path, "aim-understand")

    assert options.units == ("core/DATE", "core/PAY", "core/TAX")
    assert calls == 1


def test_blocked_understand_does_not_select_unit(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented behavior.",
    )

    result = evaluate_pipeline(tmp_path, "aim-understand", unit="core/PAY")

    assert not result.allowed
    assert result.selected_units == ()


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


def _write_mapping_contract(tmp_path: Path, unit: str) -> None:
    module, name = unit.split("/", 1)
    mapping = tmp_path / "mapping" / module / f"{name}.md"
    mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_text("# Target mapping\n")
    mapping.with_suffix(".verify.command").write_text("true\n")


def test_convert_unit_requires_converted_dependencies(tmp_path: Path):
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

    result = evaluate_pipeline(tmp_path, "aim-convert-unit", unit="core/PAY")

    assert not result.allowed
    assert "dependency shared/DATE is designed, not converted" in result.blockers


def test_convert_wave_orders_same_wave_dependencies(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="designed",
        wave=0,
        depends_on=["shared/DATE"],
    )
    write_unit(
        tmp_path,
        "shared",
        "DATE",
        kind="utility",
        phase="designed",
        wave=0,
    )
    _write_mapping_contract(tmp_path, "core/PAY")
    _write_mapping_contract(tmp_path, "shared/DATE")

    result = evaluate_pipeline(tmp_path, "aim-convert-wave", wave=0)

    assert result.allowed
    assert result.selected_units == ("shared/DATE", "core/PAY")


def test_rulebook_capability_blocks_unavailable_pipeline(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: cobol-java21, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 2\n"
    )
    (tmp_path / "rulebook").mkdir()
    (tmp_path / "rulebook" / "rulebook.yaml").write_text(
        "id: cobol-java21\nversion: '0.1'\ncapabilities:\n  design: unavailable\n"
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


def test_design_pipeline_requires_finalized_target_conventions(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented behavior.",
    )

    missing = evaluate_pipeline(tmp_path, "aim-design-unit", unit="core/PAY")
    (tmp_path / "target-conventions.md").write_text("Status: baseline pending\n")
    pending = evaluate_pipeline(tmp_path, "aim-design-unit", unit="core/PAY")
    (tmp_path / "target-conventions.md").write_text("# Approved target conventions\n")
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))
    ready = evaluate_pipeline(tmp_path, "aim-design-unit", unit="core/PAY")

    assert "target-conventions.md is missing" in missing.blockers
    assert "target-conventions.md baseline is pending" in pending.blockers
    assert ready.allowed


def _write_capture_rulebook(tmp_path: Path) -> None:
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: capture-test, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 2\n"
    )
    (tmp_path / "rulebook").mkdir()
    (tmp_path / "rulebook/runners").mkdir()
    (tmp_path / "rulebook/runners/run_legacy.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: capture-test\nversion: '0.1'\n"
        "capabilities: {compare: ready}\n"
        "runners: {legacy: runners/run_legacy.sh}\n"
    )


def test_capture_golden_prepares_missing_case_contract(tmp_path: Path):
    _write_capture_rulebook(tmp_path)
    write_unit(tmp_path, "core", "PAY", kind="program", phase="understood")
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))

    result = evaluate_pipeline(
        tmp_path, "aim-capture-golden", unit="core/PAY", case_set="smoke"
    )

    assert result.allowed
    assert any("legacy.command" in warning for warning in result.warnings)
    assert any("target.command" in warning for warning in result.warnings)
    assert any("golden metadata" in warning for warning in result.warnings)


def test_capture_golden_contract_requires_all_case_files(tmp_path: Path):
    _write_capture_rulebook(tmp_path)
    write_unit(tmp_path, "core", "PAY", kind="program", phase="understood")
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))

    missing = evaluate_pipeline(
        tmp_path,
        "aim-capture-golden-contract",
        unit="core/PAY",
        case_set="smoke",
    )
    case_dir = tmp_path / "golden/units/core/PAY/cases/smoke"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "legacy.command").write_text("true\n")
    (case_dir / "target.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: test-source-revision\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )
    ready = evaluate_pipeline(
        tmp_path,
        "aim-capture-golden-contract",
        unit="core/PAY",
        case_set="smoke",
    )

    assert not missing.allowed
    assert any("input directory" in blocker for blocker in missing.blockers)
    assert any("legacy.command" in blocker for blocker in missing.blockers)
    assert any("target.command" in blocker for blocker in missing.blockers)
    assert ready.allowed


def test_capture_contract_requires_explicit_overwrite_for_existing_baseline(
    tmp_path: Path,
):
    _write_capture_rulebook(tmp_path)
    write_unit(tmp_path, "core", "PAY", kind="program", phase="understood")
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))
    case_dir = tmp_path / "golden/units/core/PAY/cases/smoke"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "expected").mkdir()
    (case_dir / "expected/result.txt").write_text("trusted\n")
    (case_dir / "legacy.command").write_text("true\n")
    (case_dir / "target.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: test-source-revision\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )
    stamp_expected_integrity(case_dir)

    blocked = evaluate_pipeline(
        tmp_path,
        "aim-capture-golden-contract",
        unit="core/PAY",
        case_set="smoke",
        overwrite=False,
    )
    ready = evaluate_pipeline(
        tmp_path,
        "aim-capture-golden-contract",
        unit="core/PAY",
        case_set="smoke",
        overwrite=True,
    )

    assert not blocked.allowed
    assert any("enable overwrite" in blocker for blocker in blocked.blockers)
    assert ready.allowed
    assert "existing trusted baseline will be replaced" in ready.warnings


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


def test_compare_pipeline_requires_target_command(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: compare-test, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 2\n"
    )
    (tmp_path / "rulebook/runners").mkdir(parents=True)
    (tmp_path / "rulebook/runners/run_target.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "rulebook/canonicalizers").mkdir()
    (tmp_path / "rulebook/canonicalizers/default.yaml").write_text("id: default\n")
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: compare-test\nversion: '0.1'\n"
        "capabilities: {compare: ready}\n"
        "runners: {target: runners/run_target.sh}\n"
    )
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.rs"],
    )
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))
    case_dir = tmp_path / "golden/units/core/PAY/cases/smoke"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "expected").mkdir()
    (case_dir / "expected/result.txt").write_text("ok\n")
    (case_dir / "legacy.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: test-source-revision\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )
    missing = evaluate_pipeline(
        tmp_path, "aim-test-compare", unit="core/PAY", case_set="smoke"
    )
    (case_dir / "target.command").write_text("true\n")
    stamp_expected_integrity(case_dir)
    ready = evaluate_pipeline(
        tmp_path, "aim-test-compare", unit="core/PAY", case_set="smoke"
    )

    assert not missing.allowed
    assert any("target.command" in blocker for blocker in missing.blockers)
    assert ready.allowed


def test_compare_pipeline_requires_available_canonicalizer(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        "rulebook: {id: compare-test, version: '0.1'}\n"
        "roles: {source: [], target: []}\n"
        "state_schema: 2\n"
        "compare_default_profile: missing\n"
    )
    (tmp_path / "rulebook/runners").mkdir(parents=True)
    (tmp_path / "rulebook/runners/run_target.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: compare-test\nversion: '0.1'\n"
        "capabilities: {compare: ready}\n"
        "runners: {target: runners/run_target.sh}\n"
    )
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.rs"],
    )
    confirm_no_business_rules(tmp_path, "core/PAY", str(uuid4()))
    case_dir = tmp_path / "golden/units/core/PAY/cases/smoke"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "expected").mkdir()
    (case_dir / "expected/result.txt").write_text("ok\n")
    (case_dir / "legacy.command").write_text("true\n")
    (case_dir / "target.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: missing\n"
        "source_revision: test-source-revision\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )
    stamp_expected_integrity(case_dir)

    result = evaluate_pipeline(
        tmp_path, "aim-test-compare", unit="core/PAY", case_set="smoke"
    )

    assert not result.allowed
    assert "canonicalizer profile 'missing' is missing" in result.blockers


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


def test_cutover_pipeline_requires_external_dependencies_cutover(tmp_path: Path):
    write_unit(tmp_path, "shared", "DATE", kind="utility", phase="equivalent", wave=0)
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        wave=1,
        depends_on=["shared/DATE"],
    )
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

    result = evaluate_pipeline(tmp_path, "aim-cutover-check", wave=1)

    assert not result.allowed
    assert "dependency shared/DATE is equivalent, not cutover" in result.blockers


def test_cutover_pipeline_orders_same_wave_dependencies(tmp_path: Path):
    write_unit(tmp_path, "shared", "DATE", kind="utility", phase="equivalent", wave=1)
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        wave=1,
        depends_on=["shared/DATE"],
    )
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

    result = evaluate_pipeline(tmp_path, "aim-cutover-check", wave=1)

    assert result.allowed
    assert result.selected_units == ("shared/DATE", "core/PAY")
