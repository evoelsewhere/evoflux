from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.agent.builtin_prompts import tier_tools
from app.agent.loader import _default_tool_registry
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.aim import aim_compare, aim_units
from app.core import db as db_module
from app.models.aim import AimLink, AimRun, AimUnit
from app.models.chat import CodingProject, CodingProjectWorkspace
from app.services.coding_workspace_service import upsert_coding_workspace


@pytest.fixture
def sandbox_workspace(tmp_path):
    config = SandboxConfig(workspace=str(tmp_path))
    token = set_sandbox(config)
    yield tmp_path
    _sandbox_ctx.reset(token)


async def _make_aim_project(workspace_path: Path) -> CodingProject:
    async with db_module.async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(workspace_path), kind="repo")
        project = CodingProject(
            name="test-aim-project",
            kind="aim",
            settings={"aim": {"roles": {"kb": str(ws.id)}}},
        )
        db.add(project)
        await db.flush()
        db.add(CodingProjectWorkspace(project_id=project.id, workspace_id=ws.id))
        await db.commit()
        await db.refresh(project)
        return project


def _write_kb_skeleton(root: Path) -> None:
    (root / "aim.yaml").write_text(
        "rulebook:\n  id: default\n  version: '0.1'\n"
        "roles:\n  source: []\n  target: []\n"
        "golden_dir: golden\ncompare_default_profile: default\nphase: assess\n"
    )


# ---------------------------------------------------------------------------
# Tier gating — the most important regression: aim tools must not leak into
# forge/coding sessions.
# ---------------------------------------------------------------------------


def test_aim_tools_excluded_from_forge_and_coding_tiers():
    registry = _default_tool_registry()
    forge_names = tier_tools(registry, mode="forge", role="member")
    coding_names = tier_tools(registry, mode="coding", role="member")
    assert "aim_units" not in forge_names
    assert "aim_compare" not in forge_names
    assert "aim_units" not in coding_names
    assert "aim_compare" not in coding_names


def test_aim_tools_included_in_aim_tier():
    registry = _default_tool_registry()
    aim_names = tier_tools(registry, mode="aim", role="member")
    assert "aim_units" in aim_names
    assert "aim_compare" in aim_names


# ---------------------------------------------------------------------------
# aim_units — fallback path (no CodingProject resolved): sandbox root is
# treated as the KB directly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_phase_and_get_without_a_project(sandbox_workspace):
    result = await aim_units(
        action="set_phase",
        unit="core-batch/PAYROLL01",
        kind="program",
        phase="inventory",
        source_paths=["src/PAYROLL01.cbl"],
    )
    assert "no AIM project resolved" in result

    got = await aim_units(action="get", unit="core-batch/PAYROLL01")
    data = json.loads(got)
    assert data["kind"] == "program"
    assert data["phase"] == "inventory"

    doc = sandbox_workspace / "modules" / "core-batch" / "PAYROLL01.md"
    assert doc.exists()


@pytest.mark.asyncio
async def test_set_phase_accepts_json_encoded_list_and_dict_args(sandbox_workspace):
    """Regression: smaller models send list/dict args as JSON strings
    (observed live: aim-lead stuck retrying set_phase with
    target_paths='["…"]'). The validated arun() path must coerce them."""
    result = await aim_units.arun(
        action="set_phase",
        unit="core-batch/STRARGS",
        kind="program",
        phase="converted",
        target_paths='["app/src/main/java/com/example/Addamt.java"]',
        depends_on='["core-batch/DATEUTIL"]',
        complexity='{"score": "low"}',
    )
    assert "STRARGS" in result

    got = await aim_units(action="get", unit="core-batch/STRARGS")
    data = json.loads(got)
    assert data["target_paths"] == ["app/src/main/java/com/example/Addamt.java"]
    assert data["depends_on"] == ["core-batch/DATEUTIL"]
    assert data["complexity"] == {"score": "low"}

    # A string that isn't JSON still fails validation loudly.
    from app.agent.errors import ToolArgumentError

    with pytest.raises(ToolArgumentError):
        await aim_units.arun(
            action="set_phase",
            unit="core-batch/STRARGS",
            target_paths="not-a-list",
        )


@pytest.mark.asyncio
async def test_get_missing_unit_returns_message(sandbox_workspace):
    result = await aim_units(action="get", unit="core-batch/NOPE")
    assert "No unit doc found" in result


@pytest.mark.asyncio
async def test_list_and_phase_filter(sandbox_workspace):
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    await aim_units(action="set_phase", unit="m/B", kind="program", phase="understood")

    all_units = await aim_units(action="list")
    assert "m/A" in all_units and "m/B" in all_units

    filtered = await aim_units(action="list", phase_filter="understood")
    assert "m/B" in filtered
    assert "m/A" not in filtered


@pytest.mark.asyncio
async def test_set_project_phase_updates_manifest(sandbox_workspace):
    _write_kb_skeleton(sandbox_workspace)
    result = await aim_units(action="set_project_phase", phase="understand")
    assert "Project phase set to 'understand'" in result
    assert "phase: understand" in (sandbox_workspace / "aim.yaml").read_text()


@pytest.mark.asyncio
async def test_record_run_without_project_reports_clearly(sandbox_workspace):
    result = await aim_units(
        action="record_run", unit="m/A", run_kind="test", verdict="pass"
    )
    assert "no AIM project resolved" in result


@pytest.mark.asyncio
async def test_add_link_without_project_reports_clearly(sandbox_workspace):
    result = await aim_units(
        action="add_link",
        from_ref="rule:BR-M-0001",
        to_ref="unit:m/A",
        link_kind="implements",
    )
    assert "Cannot add a link" in result


# ---------------------------------------------------------------------------
# aim_units — resolved project path: DB index gets synced.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_phase_syncs_db_index_when_project_resolved(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)

    result = await aim_units(
        action="set_phase", unit="core-batch/PAYROLL01", kind="program", phase="inventory"
    )
    assert "no AIM project resolved" not in result

    async with db_module.async_session_factory() as db:
        rows = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).all()
    assert len(rows) == 1
    assert rows[0].module == "core-batch"
    assert rows[0].name == "PAYROLL01"
    assert rows[0].phase == "inventory"


@pytest.mark.asyncio
async def test_record_run_creates_aim_run_row(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="converted")

    result = await aim_units(
        action="record_run",
        unit="m/A",
        run_kind="test",
        verdict="pass",
        case_set="smoke",
        stats={"cases": 3},
    )
    assert "Recorded test run" in result

    async with db_module.async_session_factory() as db:
        unit_row = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).one()
        runs = (await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))).all()
    assert len(runs) == 1
    assert runs[0].verdict == "pass"
    assert runs[0].stats == {"cases": 3}


@pytest.mark.asyncio
async def test_record_run_for_unindexed_unit_fails_clearly(sandbox_workspace):
    await _make_aim_project(sandbox_workspace)
    result = await aim_units(
        action="record_run", unit="m/NEVER_INDEXED", run_kind="test", verdict="pass"
    )
    assert "not indexed yet" in result


@pytest.mark.asyncio
async def test_add_link_creates_aim_link_row(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    result = await aim_units(
        action="add_link",
        from_ref="rule:BR-M-0001",
        to_ref="unit:m/A",
        link_kind="implements",
        note="cited from mapping/A.md",
    )
    assert "Linked rule:BR-M-0001 -> unit:m/A" in result

    async with db_module.async_session_factory() as db:
        links = (
            await db.exec(select(AimLink).where(AimLink.project_id == project.id))
        ).all()
    assert len(links) == 1
    assert links[0].kind == "implements"
    assert links[0].note == "cited from mapping/A.md"


# ---------------------------------------------------------------------------
# aim_compare
# ---------------------------------------------------------------------------


def _write_golden_case(root: Path, module: str, name: str, case_set: str, content: str) -> None:
    case_dir = root / "golden" / "units" / module / name / "cases" / case_set / "expected"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "out.txt").write_text(content)


@pytest.mark.asyncio
async def test_compare_pass_without_project(sandbox_workspace):
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "hello world\n")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("hello world\n")

    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "pass"
    assert data["diff_count"] == 0
    assert Path(data["report_path"]).exists()


@pytest.mark.asyncio
async def test_compare_fail_reports_clusters(sandbox_workspace):
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "expected line\n")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("different line\n")

    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "fail"
    assert data["diff_count"] == 1
    assert data["clusters"][0]["path"] == "out.txt"


@pytest.mark.asyncio
async def test_compare_missing_golden_case_returns_error(sandbox_workspace):
    result = await aim_compare(unit="m/NEVER", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "error"
    assert "No golden case" in data["error"]


@pytest.mark.asyncio
async def test_compare_records_aim_run_when_project_resolved(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="converted")

    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "hello\n")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("hello\n")

    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "pass"

    async with db_module.async_session_factory() as db:
        unit_row = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).one()
        runs = (await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))).all()
    assert len(runs) == 1
    assert runs[0].kind == "compare"
    assert runs[0].verdict == "pass"


@pytest.mark.asyncio
async def test_compare_uses_project_canonicalizer_profile(sandbox_workspace):
    _write_kb_skeleton(sandbox_workspace)
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "run-id: abc123\nvalue: 1")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("run-id: xyz789\nvalue: 1")

    # No rulebook dir bundled for id "default" -> falls back to a bare
    # profile (no masks), so this run-id difference should still fail.
    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "fail"
