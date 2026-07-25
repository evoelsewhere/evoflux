from pathlib import Path
from uuid import uuid4

from app.models.aim import AimLink, AimRun, AimUnit
from app.services.aim.kb_store import write_unit
from app.services.aim.traceability import build_traceability


def test_traceability_reports_phase_aware_coverage_and_links(tmp_path: Path):
    unit_id = uuid4()
    project_id = uuid4()
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        wave=1,
        body="Documented behavior.",
    )
    unit = AimUnit(
        id=unit_id,
        project_id=project_id,
        module="core",
        name="PAY",
        kind="program",
        phase="equivalent",
        wave=1,
        kb_doc_path="modules/core/PAY.md",
    )
    link = AimLink(
        project_id=project_id,
        from_ref="rule:BR-CORE-001",
        to_ref="unit:core/PAY",
        kind="applies_to",
    )

    result = build_traceability(tmp_path, [unit], [], [link])

    assert result["summary"]["total_units"] == 1
    assert result["summary"]["explicit_links"] == 1
    assert result["summary"]["total_gaps"] == 3
    assert result["units"][0]["links"][0]["kind"] == "applies_to"
    assert result["units"][0]["gaps"] == [
        "business rules for core/PAY have not been reviewed",
        "Target mapping is missing",
        "Passing compare evidence is missing",
    ]


def test_traceability_recognizes_mapping_and_passing_compare(tmp_path: Path):
    unit_id = uuid4()
    project_id = uuid4()
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        body="Documented behavior.",
    )
    mapping = tmp_path / "mapping" / "core" / "PAY.md"
    mapping.parent.mkdir(parents=True)
    mapping.write_text("# Mapping\n", encoding="utf-8")
    unit = AimUnit(
        id=unit_id,
        project_id=project_id,
        module="core",
        name="PAY",
        kind="program",
        phase="equivalent",
        kb_doc_path="modules/core/PAY.md",
    )
    run = AimRun(
        unit_id=unit_id,
        kind="compare",
        verdict="pass",
    )

    result = build_traceability(tmp_path, [unit], [run], [])

    assert result["summary"]["mapped_units"] == 1
    assert result["summary"]["evidenced_units"] == 1
    assert result["units"][0]["mapping_path"] == "mapping/core/PAY.md"
    assert "Target mapping is missing" not in result["units"][0]["gaps"]
    assert "Passing compare evidence is missing" not in result["units"][0]["gaps"]
