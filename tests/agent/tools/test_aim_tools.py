from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid7

import pytest
import yaml
from sqlmodel import select

from app.agent.builtin_prompts import tier_tools
from app.agent.loader import _default_tool_registry
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.aim import (
    aim_capture,
    aim_claim,
    aim_compare,
    aim_readiness,
    aim_rules,
    aim_understanding,
    aim_units,
)
from app.core import db as db_module
from app.models.aim import AimLink, AimRun, AimUnit
from app.models.chat import CodingProject, CodingProjectWorkspace
from app.models.workflow import WorkflowExecution
from app.services.aim import kb_store
from app.services.aim.golden import GoldenCaseError, stamp_expected_integrity
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


def _substantive_unit_body(label: str) -> str:
    detail = (
        f"The {label} behavior is derived from source evidence and preserves "
        "interfaces, error ordering, side effects, and externally visible state. "
    )
    return (
        f"# {label}\n\n## Purpose\n\n{detail * 4}\n\n"
        f"## Control flow and interfaces\n\n{detail * 4}\n\n"
        f"## Dependencies and ambiguities\n\n{detail * 4}\n"
    )


async def _make_workflow_execution(name: str) -> WorkflowExecution:
    async with db_module.async_session_factory() as db:
        execution = WorkflowExecution(
            definition_name=name,
            definition_hash="test-hash",
            session_id=uuid7(),
            status="running",
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
        return execution


def _write_kb_skeleton(root: Path) -> None:
    (root / "aim.yaml").write_text(
        "rulebook:\n  id: default\n  version: '0.1'\n"
        "roles:\n  source: []\n  target: []\n"
        "golden_dir: golden\ncompare_default_profile: default\nphase: assess\n"
    )


async def _seed_indexed_unit(
    root: Path,
    unit: str,
    *,
    phase: str,
    target_paths: list[str] | None = None,
) -> None:
    module, name = unit.split("/", 1)
    kb_store.write_unit(
        root,
        module,
        name,
        kind="program",
        phase=phase,
        target_paths=target_paths,
    )
    await aim_units(action="set_phase", unit=unit)


# ---------------------------------------------------------------------------
# Tier gating — the most important regression: aim tools must not leak into
# forge/coding sessions.
# ---------------------------------------------------------------------------


def test_aim_tools_excluded_from_forge_and_coding_tiers():
    registry = _default_tool_registry()
    forge_names = tier_tools(registry, mode="forge", role="member")
    coding_names = tier_tools(registry, mode="coding", role="member")
    assert "aim_units" not in forge_names
    assert "aim_capture" not in forge_names
    assert "aim_compare" not in forge_names
    assert "aim_readiness" not in forge_names
    assert "aim_rules" not in forge_names
    assert "aim_understanding" not in forge_names
    assert "aim_claim" not in forge_names
    assert "aim_execute" not in forge_names
    assert "aim_verify" not in forge_names
    assert "aim_units" not in coding_names
    assert "aim_capture" not in coding_names
    assert "aim_compare" not in coding_names
    assert "aim_readiness" not in coding_names
    assert "aim_rules" not in coding_names
    assert "aim_understanding" not in coding_names
    assert "aim_claim" not in coding_names
    assert "aim_execute" not in coding_names
    assert "aim_verify" not in coding_names


def test_aim_tools_included_in_aim_tier():
    registry = _default_tool_registry()
    aim_names = tier_tools(registry, mode="aim", role="member")
    assert "aim_units" in aim_names
    assert "aim_capture" in aim_names
    assert "aim_compare" in aim_names
    assert "aim_readiness" in aim_names
    assert "aim_rules" in aim_names
    assert "aim_understanding" in aim_names
    assert "aim_claim" in aim_names
    assert "aim_execute" in aim_names
    assert "aim_verify" in aim_names


@pytest.mark.asyncio
async def test_aim_readiness_tool_blocks_incomplete_cutover(sandbox_workspace):
    kb_store.write_unit(
        sandbox_workspace,
        "m",
        "A",
        kind="program",
        phase="equivalent",
        wave=1,
    )
    kb_store.write_unit(
        sandbox_workspace,
        "m",
        "B",
        kind="program",
        phase="converted",
        wave=1,
        target_paths=["src/B.java"],
    )

    result = await aim_readiness(pipeline="aim-cutover-check", wave=1)

    data = json.loads(result)
    assert data["status"] == "blocked"
    assert any("m/B" in blocker for blocker in data["blockers"])


@pytest.mark.asyncio
async def test_aim_readiness_rejects_stale_expected_unit_selection(
    sandbox_workspace,
):
    kb_store.write_unit(
        sandbox_workspace,
        "shared",
        "DATE",
        kind="utility",
        phase="inventory",
    )
    kb_store.write_unit(
        sandbox_workspace,
        "core",
        "PAY",
        kind="program",
        phase="inventory",
        depends_on=["shared/DATE"],
    )

    result = json.loads(
        await aim_readiness(
            pipeline="aim-understand",
            unit="core/PAY",
            expected_units=["core/PAY"],
        )
    )

    assert result["status"] == "blocked"
    assert any("changed after approval" in blocker for blocker in result["blockers"])


@pytest.mark.asyncio
async def test_aim_claim_is_exclusive_and_owner_releases(sandbox_workspace):
    from app.workflow.exec_context import current_execution_id

    await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    first = await _make_workflow_execution("aim-understand")
    second = await _make_workflow_execution("aim-understand")

    first_token = current_execution_id.set(str(first.id))
    try:
        acquired = json.loads(await aim_claim(action="acquire", unit="m/A"))
    finally:
        current_execution_id.reset(first_token)
    assert acquired["status"] == "acquired"

    second_token = current_execution_id.set(str(second.id))
    try:
        blocked = json.loads(await aim_claim(action="acquire", unit="m/A"))
        with pytest.raises(ValueError, match="owned by workflow execution"):
            await aim_claim(action="release", unit="m/A")
    finally:
        current_execution_id.reset(second_token)
    assert blocked["status"] == "blocked"

    first_token = current_execution_id.set(str(first.id))
    try:
        released = json.loads(await aim_claim(action="release", unit="m/A"))
    finally:
        current_execution_id.reset(first_token)
    assert released["status"] == "released"


@pytest.mark.asyncio
async def test_aim_claim_locks_only_explicit_unit_list(sandbox_workspace):
    from app.models.aim import AimClaim
    from app.workflow.exec_context import current_execution_id

    project = await _make_aim_project(sandbox_workspace)
    await aim_units(
        action="set_phase", unit="m/A", kind="program", phase="inventory", wave=1
    )
    await aim_units(
        action="set_phase", unit="m/B", kind="program", phase="inventory", wave=1
    )
    execution = await _make_workflow_execution("aim-convert-wave")

    token = current_execution_id.set(str(execution.id))
    try:
        acquired = json.loads(await aim_claim(action="acquire", units=["m/A"]))
    finally:
        current_execution_id.reset(token)

    assert acquired["count"] == 1
    async with db_module.async_session_factory() as db:
        claims = (
            await db.exec(select(AimClaim).where(AimClaim.project_id == project.id))
        ).all()
    assert len(claims) == 1


@pytest.mark.asyncio
async def test_aim_claim_rejects_partially_missing_explicit_scope(sandbox_workspace):
    from app.workflow.exec_context import current_execution_id

    await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    execution = await _make_workflow_execution("aim-understand")

    token = current_execution_id.set(str(execution.id))
    try:
        with pytest.raises(ValueError, match="missing units: m/B"):
            await aim_claim(action="acquire", units=["m/A", "m/B"])
    finally:
        current_execution_id.reset(token)


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
        phase="inventory",
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
    await _seed_indexed_unit(sandbox_workspace, "m/B", phase="understood")

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
        action="set_phase",
        unit="core-batch/PAYROLL01",
        kind="program",
        phase="inventory",
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
async def test_set_phase_rejects_skipping_lifecycle(sandbox_workspace):
    await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")

    with pytest.raises(
        ValueError, match="illegal phase transition inventory -> converted"
    ):
        await aim_units(action="set_phase", unit="m/A", phase="converted")


@pytest.mark.asyncio
async def test_agent_turn_cannot_own_phase_transition(sandbox_workspace):
    await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    kb_store.write_unit(sandbox_workspace, "m", "A", body="Documented behavior.")

    with pytest.raises(ValueError, match="must run through aim-understand"):
        await aim_units(action="set_phase", unit="m/A", phase="understood")


@pytest.mark.asyncio
async def test_transition_requires_resolved_project(sandbox_workspace):
    from app.workflow.exec_context import current_execution_id

    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    kb_store.write_unit(sandbox_workspace, "m", "A", body="Documented behavior.")
    token = current_execution_id.set(str(uuid7()))
    try:
        with pytest.raises(ValueError, match="resolved AIM project"):
            await aim_units(action="set_phase", unit="m/A", phase="understood")
    finally:
        current_execution_id.reset(token)


@pytest.mark.asyncio
async def test_owning_workflow_advances_ready_unit(sandbox_workspace):
    from app.workflow.exec_context import current_execution_id

    await _make_aim_project(sandbox_workspace)
    await aim_units(action="set_phase", unit="m/A", kind="program", phase="inventory")
    execution = await _make_workflow_execution("aim-understand")

    token = current_execution_id.set(str(execution.id))
    try:
        await aim_claim(action="acquire", unit="m/A")
        snapshot = json.loads(await aim_understanding(action="snapshot", units=["m/A"]))
        kb_store.write_unit(
            sandbox_workspace,
            "m",
            "A",
            body=_substantive_unit_body("A behavior"),
        )
        await aim_understanding(
            action="verify", units=["m/A"], baseline=snapshot["digests"]
        )
        result = await aim_units(action="set_phase", unit="m/A", phase="understood")
    finally:
        current_execution_id.reset(token)

    assert "phase=understood" in result
    events = list(
        (sandbox_workspace / "state" / "transitions" / "m" / "A").glob("*.yaml")
    )
    assert len(events) == 1
    event = yaml.safe_load(events[0].read_text())
    assert event["evidence_refs"][0] == "modules/m/A.md"
    assert event["evidence_refs"][1].startswith("state/evidence/understanding/")


@pytest.mark.asyncio
async def test_understand_workflow_advances_claimed_dependency_closure(
    sandbox_workspace,
):
    from app.workflow.exec_context import current_execution_id

    await _make_aim_project(sandbox_workspace)
    await aim_units(
        action="set_phase",
        unit="shared/DATE",
        kind="utility",
        phase="inventory",
    )
    await aim_units(
        action="set_phase",
        unit="core/PAY",
        kind="program",
        phase="inventory",
        depends_on=["shared/DATE"],
    )
    execution = await _make_workflow_execution("aim-understand")

    token = current_execution_id.set(str(execution.id))
    try:
        acquired = json.loads(
            await aim_claim(action="acquire", units=["shared/DATE", "core/PAY"])
        )
        snapshot = json.loads(
            await aim_understanding(
                action="snapshot", units=["shared/DATE", "core/PAY"]
            )
        )
        kb_store.write_unit(
            sandbox_workspace,
            "shared",
            "DATE",
            body=_substantive_unit_body("Date behavior"),
        )
        kb_store.write_unit(
            sandbox_workspace,
            "core",
            "PAY",
            depends_on=["shared/DATE"],
            body=_substantive_unit_body("Payroll behavior"),
        )
        await aim_understanding(
            action="verify",
            units=["shared/DATE", "core/PAY"],
            baseline=snapshot["digests"],
        )
        await aim_units(action="set_phase", unit="shared/DATE", phase="understood")
        await aim_units(action="set_phase", unit="core/PAY", phase="understood")
        released = json.loads(
            await aim_claim(action="release", units=["shared/DATE", "core/PAY"])
        )
    finally:
        current_execution_id.reset(token)

    assert acquired["count"] == 2
    assert released["count"] == 2
    assert kb_store.read_unit(sandbox_workspace, "shared", "DATE")[0].phase == (
        "understood"
    )
    assert kb_store.read_unit(sandbox_workspace, "core", "PAY")[0].phase == (
        "understood"
    )


@pytest.mark.asyncio
async def test_rule_review_confirmation_unlocks_design(sandbox_workspace):
    from app.services.aim.readiness import evaluate_pipeline
    from app.workflow.exec_context import current_execution_id

    await _make_aim_project(sandbox_workspace)
    await aim_units(
        action="set_phase", unit="m/A", kind="program", phase="inventory"
    )
    kb_store.write_unit(
        sandbox_workspace,
        "m",
        "A",
        phase="understood",
        body=_substantive_unit_body("A behavior"),
    )
    (sandbox_workspace / "target-conventions.md").write_text("# Approved\n")
    rules = sandbox_workspace / "business-rules"
    rules.mkdir()
    (rules / "BR-M-0001.md").write_text(
        "---\nstatus: candidate\nunit: m/A\nsource_ref: src/a.c:1\n---\n\n"
        "# BR-M-0001: Exact behavior\n\nCited behavior.\n"
    )
    execution = await _make_workflow_execution("aim-review-rules")

    token = current_execution_id.set(str(execution.id))
    try:
        await aim_claim(action="acquire", unit="m/A")
        result = json.loads(await aim_rules(action="confirm", unit="m/A"))
        await aim_claim(action="release", unit="m/A")
    finally:
        current_execution_id.reset(token)

    assert result["status"] == "confirmed"
    assert evaluate_pipeline(
        sandbox_workspace, "aim-design-unit", unit="m/A"
    ).allowed


@pytest.mark.asyncio
async def test_record_run_creates_aim_run_row(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    await _seed_indexed_unit(
        sandbox_workspace,
        "m/A",
        phase="converted",
        target_paths=["src/A.java"],
    )

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
        runs = (
            await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))
        ).all()
    assert len(runs) == 1
    assert runs[0].verdict == "pass"
    assert runs[0].stats == {"cases": 3}
    meta_path = sandbox_workspace / "runs" / "m" / "A" / str(runs[0].id) / "meta.yaml"
    assert meta_path.is_file()


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
    assert (sandbox_workspace / "state" / "links" / f"{links[0].id}.yaml").is_file()


# ---------------------------------------------------------------------------
# aim_compare
# ---------------------------------------------------------------------------


def _write_golden_case(
    root: Path,
    module: str,
    name: str,
    case_set: str,
    content: str,
    *,
    meta: str | None = None,
) -> None:
    case_dir = root / "golden" / "units" / module / name / "cases" / case_set
    expected_dir = case_dir / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)
    (expected_dir / "out.txt").write_text(content)
    (case_dir / "legacy.command").write_text("true\n")
    (case_dir / "target.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        meta
        if meta is not None
        else (
            "provenance: captured\n"
            "canonicalizer_profile: default\n"
            "source_revision: test-source-revision\n"
            "environment_fingerprint: test-environment\n"
            "capture_command: test-capture\n"
        )
    )
    try:
        stamp_expected_integrity(case_dir)
    except GoldenCaseError:
        # Tests that deliberately write invalid metadata exercise fail-closed paths.
        pass


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
    assert not Path(data["report_path"]).is_absolute()
    assert (sandbox_workspace / data["report_path"]).exists()


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
async def test_compare_error_records_aim_run_when_project_resolved(
    sandbox_workspace,
):
    project = await _make_aim_project(sandbox_workspace)
    await _seed_indexed_unit(
        sandbox_workspace,
        "m/A",
        phase="converted",
        target_paths=["src/A.rs"],
    )

    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)

    assert data["verdict"] == "error"
    assert (sandbox_workspace / data["report_path"]).is_file()
    async with db_module.async_session_factory() as db:
        unit_row = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).one()
        runs = (
            await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))
        ).all()
    assert len(runs) == 1
    assert runs[0].kind == "compare"
    assert runs[0].verdict == "error"


@pytest.mark.asyncio
async def test_capture_records_domain_run(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    _write_kb_skeleton(sandbox_workspace)
    runners = sandbox_workspace / "rulebook/runners"
    runners.mkdir(parents=True)
    (sandbox_workspace / "rulebook/rulebook.yaml").write_text(
        "id: default\nversion: '0.1'\n"
        "runners: {legacy: runners/legacy.sh}\n"
    )
    (runners / "legacy.sh").write_text(
        "#!/bin/sh\nbash \"$AIM_CASE_DIR/legacy.command\"\n"
    )
    (sandbox_workspace.parent / "aim_source_base").mkdir(exist_ok=True)
    await _seed_indexed_unit(
        sandbox_workspace,
        "m/A",
        phase="understood",
    )
    case_dir = sandbox_workspace / "golden/units/m/A/cases/smoke"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "legacy.command").write_text(
        'printf "baseline\\n" > "$AIM_OUT_DIR/out.txt"\n'
    )
    (case_dir / "target.command").write_text("true\n")
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: external-test-source\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: legacy.command\n"
    )

    result = json.loads(await aim_capture(unit="m/A", case_set="smoke"))

    assert result["status"] == "captured"
    assert (case_dir / "expected/out.txt").is_file()
    async with db_module.async_session_factory() as db:
        unit_row = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).one()
        runs = (
            await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))
        ).all()
    assert len(runs) == 1
    assert runs[0].kind == "capture"
    assert runs[0].verdict == "pass"
    assert (
        sandbox_workspace / "runs" / "m" / "A" / str(runs[0].id) / "meta.yaml"
    ).is_file()


@pytest.mark.asyncio
async def test_compare_requires_golden_metadata(sandbox_workspace):
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "hello\n", meta="")

    result = await aim_compare(unit="m/A", case_set="smoke")

    data = json.loads(result)
    assert data["verdict"] == "error"
    assert (sandbox_workspace / data["report_path"]).is_file()
    assert data["error_kind"] == "missing_golden_metadata"


@pytest.mark.asyncio
async def test_compare_requires_signoff_for_synthesized_golden(sandbox_workspace):
    _write_golden_case(
        sandbox_workspace,
        "m",
        "A",
        "smoke",
        "hello\n",
        meta="provenance: synthesized\ncanonicalizer_profile: default\n",
    )

    result = await aim_compare(unit="m/A", case_set="smoke")

    data = json.loads(result)
    assert data["verdict"] == "error"
    assert data["error_kind"] == "untrusted_golden"


@pytest.mark.asyncio
async def test_compare_records_aim_run_when_project_resolved(sandbox_workspace):
    project = await _make_aim_project(sandbox_workspace)
    await _seed_indexed_unit(
        sandbox_workspace,
        "m/A",
        phase="converted",
        target_paths=["src/A.java"],
    )

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
        runs = (
            await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))
        ).all()
    assert len(runs) == 1
    assert runs[0].kind == "compare"
    assert runs[0].verdict == "pass"
    assert (
        sandbox_workspace / "runs" / "m" / "A" / str(runs[0].id) / "meta.yaml"
    ).is_file()


@pytest.mark.asyncio
async def test_compare_uses_project_canonicalizer_profile(sandbox_workspace):
    _write_kb_skeleton(sandbox_workspace)
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "run-id: abc123\nvalue: 1")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("run-id: xyz789\nvalue: 1")

    # A project manifest pins a real rulebook profile. Missing content must
    # fail closed rather than silently comparing with an empty profile.
    result = await aim_compare(unit="m/A", case_set="smoke")
    data = json.loads(result)
    assert data["verdict"] == "error"
    assert data["error_kind"] == "missing_canonicalizer"


# ---------------------------------------------------------------------------
# Phase-vocabulary enforcement + path-traversal safety (audit hardening).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_phase_rejects_invalid_phase(sandbox_workspace):
    with pytest.raises(ValueError, match="Invalid unit phase"):
        await aim_units(action="set_phase", unit="m/A", kind="program", phase="convert")


@pytest.mark.asyncio
async def test_set_project_phase_rejects_invalid_phase(sandbox_workspace):
    _write_kb_skeleton(sandbox_workspace)
    with pytest.raises(ValueError, match="Invalid project phase"):
        await aim_units(action="set_project_phase", phase="assessed")


@pytest.mark.asyncio
async def test_unit_path_traversal_rejected(sandbox_workspace):
    with pytest.raises(ValueError, match="unit name"):
        await aim_units(action="set_phase", unit="m/../../etc/passwd", kind="program")


@pytest.mark.asyncio
async def test_compare_rejects_case_set_traversal(sandbox_workspace):
    result = await aim_compare(unit="m/A", case_set="../smoke")
    data = json.loads(result)
    assert data["verdict"] == "error"
    assert "case_set" in data["error"]


@pytest.mark.asyncio
async def test_compare_profile_override_still_loads_rulebook_canonicalizer(
    sandbox_workspace,
):
    # Regression: passing profile= used to skip rulebook resolution and
    # return a bare mask-less profile. The KB-local rulebook supplies
    # a 'strict' profile whose mask neutralizes the run-id difference.
    _write_kb_skeleton(sandbox_workspace)
    canon_dir = sandbox_workspace / "rulebook" / "canonicalizers"
    canon_dir.mkdir(parents=True)
    (sandbox_workspace / "rulebook" / "rulebook.yaml").write_text(
        "id: default\nversion: '0.1'\n"
    )
    (canon_dir / "strict.yaml").write_text(
        "id: strict\nmask:\n  - pattern: 'run-id: \\w+'\n    replace: 'run-id: <m>'\n"
    )
    _write_golden_case(
        sandbox_workspace,
        "m",
        "A",
        "smoke",
        "run-id: abc\nv: 1",
        meta=(
            "provenance: captured\n"
            "canonicalizer_profile: strict\n"
            "source_revision: test-source-revision\n"
            "environment_fingerprint: test-environment\n"
            "capture_command: test-capture\n"
        ),
    )
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("run-id: xyz\nv: 1")

    result = await aim_compare(unit="m/A", case_set="smoke", profile="strict")
    data = json.loads(result)
    assert data["verdict"] == "pass"


@pytest.mark.asyncio
async def test_compare_stamps_workflow_execution_id(sandbox_workspace):
    from app.workflow.exec_context import current_execution_id

    project = await _make_aim_project(sandbox_workspace)
    await _seed_indexed_unit(
        sandbox_workspace,
        "m/A",
        phase="converted",
        target_paths=["src/A.java"],
    )
    _write_golden_case(sandbox_workspace, "m", "A", "smoke", "hello\n")
    actual_dir = sandbox_workspace / ".aim-actuals" / "m" / "A" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("hello\n")

    token = current_execution_id.set("exec-123")
    try:
        await aim_compare(unit="m/A", case_set="smoke")
    finally:
        current_execution_id.reset(token)

    async with db_module.async_session_factory() as db:
        unit_row = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
        ).one()
        runs = (
            await db.exec(select(AimRun).where(AimRun.unit_id == unit_row.id))
        ).all()
    assert runs[0].workflow_execution_id == "exec-123"
