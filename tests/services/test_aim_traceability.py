from datetime import datetime, timedelta, timezone
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
    assert result["summary"]["total_gaps"] == 6
    assert result["units"][0]["links"][0]["kind"] == "applies_to"
    assert {issue["code"] for issue in result["units"][0]["issues"]} == {
        "rule_review_missing",
        "mapping_missing",
        "target_artifacts_missing",
        "compare_not_started",
        "compare_pass_missing",
        "dangling_trace_link",
    }


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


def test_traceability_detects_dependency_cycle_phase_and_wave_integrity(
    tmp_path: Path,
):
    project_id = uuid4()
    a_id = uuid4()
    b_id = uuid4()
    write_unit(
        tmp_path,
        "core",
        "A",
        kind="program",
        phase="converted",
        wave=0,
        depends_on=["core/B"],
        target_paths=["src/A.rs"],
        body="Documented A.",
    )
    write_unit(
        tmp_path,
        "core",
        "B",
        kind="program",
        phase="designed",
        wave=1,
        depends_on=["core/A"],
        body="Documented B.",
    )
    mapping = tmp_path / "mapping" / "core"
    mapping.mkdir(parents=True)
    (mapping / "A.md").write_text("# A mapping\n", encoding="utf-8")
    (mapping / "A.verify.command").write_text("true\n", encoding="utf-8")

    units = [
        AimUnit(
            id=a_id,
            project_id=project_id,
            module="core",
            name="A",
            kind="program",
            phase="converted",
            wave=0,
            depends_on=["core/B"],
            target_paths=["src/A.rs"],
            kb_doc_path="modules/core/A.md",
        ),
        AimUnit(
            id=b_id,
            project_id=project_id,
            module="core",
            name="B",
            kind="program",
            phase="designed",
            wave=1,
            depends_on=["core/A"],
            kb_doc_path="modules/core/B.md",
        ),
    ]

    result = build_traceability(tmp_path, units, [], [])
    a = next(row for row in result["units"] if row["unit"] == "core/A")
    b = next(row for row in result["units"] if row["unit"] == "core/B")

    assert {issue["code"] for issue in a["issues"]} >= {
        "dependency_cycle",
        "dependency_phase_lag",
        "dependency_wave_inversion",
    }
    assert "core/B" in a["issues"][0]["related_units"] or any(
        "core/B" in issue["related_units"] for issue in a["issues"]
    )
    assert any(issue["code"] == "dependency_cycle" for issue in b["issues"])


def test_traceability_detects_index_drift_rule_citations_and_impact(tmp_path: Path):
    project_id = uuid4()
    base_id = uuid4()
    app_id = uuid4()
    write_unit(
        tmp_path,
        "core",
        "BASE",
        kind="utility",
        phase="inventory",
        body="Base documentation.",
    )
    write_unit(
        tmp_path,
        "core",
        "APP",
        kind="program",
        phase="inventory",
        depends_on=["core/BASE"],
        body="Application documentation.",
    )
    rule_path = tmp_path / "business-rules" / "BR-CORE-0001.md"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text(
        "---\nstatus: candidate\nunit: core/BASE\n---\n\n# Uncited rule\n",
        encoding="utf-8",
    )
    units = [
        AimUnit(
            id=base_id,
            project_id=project_id,
            module="core",
            name="BASE",
            kind="utility",
            phase="understood",
            kb_doc_path="modules/core/BASE.md",
        ),
        AimUnit(
            id=app_id,
            project_id=project_id,
            module="core",
            name="APP",
            kind="program",
            phase="inventory",
            depends_on=["core/BASE"],
            kb_doc_path="modules/core/APP.md",
        ),
    ]

    result = build_traceability(tmp_path, units, [], [])
    base = next(row for row in result["units"] if row["unit"] == "core/BASE")

    assert base["indexed_phase"] == "understood"
    assert base["phase"] == "inventory"
    assert base["dependent_units"] == ["core/APP"]
    assert base["impact_count"] == 1
    assert base["next_action"] == {
        "pipeline": "aim-understand",
        "target_phase": "understood",
        "allowed": True,
        "blockers": [],
        "warnings": [],
        "scope_units": ["core/BASE"],
    }
    assert {issue["code"] for issue in base["issues"]} >= {
        "index_out_of_sync",
        "rule_candidates_pending",
        "rule_source_missing",
    }


def test_traceability_detects_project_orphans_and_target_collisions(tmp_path: Path):
    project_id = uuid4()
    target_root = tmp_path / "target"
    target_root.mkdir()
    units: list[AimUnit] = []
    for name in ("A", "B"):
        unit_id = uuid4()
        write_unit(
            tmp_path,
            "core",
            name,
            kind="program",
            phase="converted",
            target_paths=["src/shared.rs"],
            body=f"Documented {name}.",
        )
        units.append(
            AimUnit(
                id=unit_id,
                project_id=project_id,
                module="core",
                name=name,
                kind="program",
                phase="converted",
                target_paths=["src/shared.rs"],
                kb_doc_path=f"modules/core/{name}.md",
            )
        )
    rules = tmp_path / "business-rules"
    rules.mkdir()
    (rules / "BR-ORPHAN-0001.md").write_text(
        "---\nstatus: candidate\nunit: missing/UNIT\nsource_ref: src/a.c:1\n---\n\n# Orphan\n",
        encoding="utf-8",
    )
    dangling = AimLink(
        project_id=project_id,
        from_ref="rule:BR-MISSING-0001",
        to_ref="run:00000000-0000-0000-0000-000000000000",
        kind="tested_by",
    )

    result = build_traceability(
        tmp_path,
        units,
        [],
        [dangling],
        target_root=target_root,
    )

    project_codes = {issue["code"] for issue in result["project_issues"]}
    assert project_codes == {"orphan_rule_unit", "dangling_trace_link"}
    for row in result["units"]:
        codes = {issue["code"] for issue in row["issues"]}
        assert "target_path_collision" in codes
        assert "target_artifact_not_found" in codes
    assert result["summary"]["project_issue_count"] == 2


def test_traceability_detects_stale_passing_compare(tmp_path: Path):
    project_id = uuid4()
    unit_id = uuid4()
    target_root = tmp_path / "target"
    target_file = target_root / "src" / "pay.rs"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("new target\n", encoding="utf-8")
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="equivalent",
        target_paths=["src/pay.rs"],
        body="Documented behavior.",
    )
    mapping = tmp_path / "mapping" / "core" / "PAY.md"
    mapping.parent.mkdir(parents=True)
    mapping.write_text("# Newer mapping\n", encoding="utf-8")
    mapping.with_suffix(".verify.command").write_text("true\n", encoding="utf-8")
    unit = AimUnit(
        id=unit_id,
        project_id=project_id,
        module="core",
        name="PAY",
        kind="program",
        phase="equivalent",
        target_paths=["src/pay.rs"],
        kb_doc_path="modules/core/PAY.md",
    )
    old_pass = AimRun(
        unit_id=unit_id,
        kind="compare",
        verdict="pass",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    result = build_traceability(
        tmp_path,
        [unit],
        [old_pass],
        [],
        target_root=target_root,
    )
    row = result["units"][0]

    stale = next(
        issue for issue in row["issues"] if issue["code"] == "compare_evidence_stale"
    )
    assert stale["severity"] == "warning"
    assert "mapping/core/PAY.md" in stale["message"]
    assert "target:src/pay.rs" in stale["message"]


def test_traceability_next_action_is_blocked_by_active_claim(tmp_path: Path):
    project_id = uuid4()
    unit_id = uuid4()
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        body="Documented behavior.",
    )
    unit = AimUnit(
        id=unit_id,
        project_id=project_id,
        module="core",
        name="PAY",
        kind="program",
        phase="inventory",
        kb_doc_path="modules/core/PAY.md",
    )

    result = build_traceability(
        tmp_path,
        [unit],
        [],
        [],
        claimed_units=frozenset({"core/PAY"}),
    )
    action = result["units"][0]["next_action"]

    assert action["allowed"] is False
    assert "active workflow claim" in action["blockers"][-1]
    assert result["summary"]["ready_actions"] == 0
