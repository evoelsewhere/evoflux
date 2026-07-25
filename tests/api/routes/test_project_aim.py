"""Tests for /api/team/projects/{id}/aim/* HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.db as db_module
from app.api.routes.team.projects import router as projects_router
from app.models.aim import AimRun, AimUnit
from app.models.chat import CodingProject, CodingProjectWorkspace
from app.services.coding_workspace_service import upsert_coding_workspace


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/team")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _make_aim_project_with_units(tmp_path: Path):
    async with db_module.async_session_factory() as db:
        project = CodingProject(name="aim-proj", kind="aim")
        db.add(project)
        await db.flush()

        unit_a = AimUnit(
            project_id=project.id,
            module="core-batch",
            name="PAYROLL01",
            kind="program",
            phase="converted",
            wave=0,
        )
        unit_b = AimUnit(
            project_id=project.id,
            module="core-batch",
            name="TAXCALC",
            kind="program",
            phase="equivalent",
            wave=0,
        )
        db.add(unit_a)
        db.add(unit_b)
        await db.flush()

        report_dir = tmp_path / f"report-{project.id}"
        report_dir.mkdir()
        report_path = report_dir / "report.json"
        report_path.write_text(json.dumps({"verdict": "pass", "diff_count": 0}))

        run = AimRun(
            unit_id=unit_b.id,
            kind="compare",
            verdict="pass",
            case_set="smoke",
            stats={"diff_count": 0},
            report_path=str(report_path),
        )
        db.add(run)
        await db.commit()
        await db.refresh(project)
        await db.refresh(unit_a)
        await db.refresh(unit_b)
        await db.refresh(run)
        return project, unit_a, unit_b, run


@pytest.mark.asyncio
async def test_list_aim_runs_returns_history_with_unit_names(client, tmp_path):
    project, _unit_a, unit_b, run = await _make_aim_project_with_units(tmp_path)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(run.id)
    assert body[0]["unit"] == f"{unit_b.module}/{unit_b.name}"
    assert body[0]["verdict"] == "pass"
    # No report payload on the list — that's the detail endpoint's job.
    assert "report" not in body[0]


@pytest.mark.asyncio
async def test_reindex_aim_project_rebuilds_units_from_kb(client, tmp_path):
    from app.services.aim.kb_store import write_unit

    source = _make_local_repo(tmp_path, "source-r")
    target = _make_local_repo(tmp_path, "target-r")
    kb_path = tmp_path / "kb-r"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "reindex-me",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]

    # Simulate a teammate's contribution arriving via git pull.
    write_unit(
        kb_path, "core-batch", "EODCLOSE", kind="program", phase="inventory", wave=1
    )

    resp = await client.post(f"/api/team/projects/{project_id}/aim/reindex")
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    units = await client.get(f"/api/team/projects/{project_id}/aim/units")
    assert [u["name"] for u in units.json()] == ["EODCLOSE"]


@pytest.mark.asyncio
async def test_aim_readiness_endpoint_blocks_incomplete_cutover(client, tmp_path):
    from app.services.aim.kb_store import write_unit

    source = _make_local_repo(tmp_path, "readiness-source")
    target = _make_local_repo(tmp_path, "readiness-target")
    kb_path = tmp_path / "readiness-kb"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "readiness-project",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]
    write_unit(kb_path, "core", "A", kind="program", phase="equivalent", wave=1)
    write_unit(
        kb_path,
        "core",
        "B",
        kind="program",
        phase="converted",
        wave=1,
        target_paths=["src/B.java"],
    )

    resp = await client.get(
        f"/api/team/projects/{project_id}/aim/readiness",
        params={"pipeline": "aim-cutover-check", "wave": 1},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"
    assert any("core/B" in blocker for blocker in resp.json()["blockers"])


@pytest.mark.asyncio
async def test_units_expose_backend_next_action_and_template_blocker(client, tmp_path):
    from app.services.aim.kb_store import write_unit

    source = _make_local_repo(tmp_path, "actions-source")
    target = _make_local_repo(tmp_path, "actions-target")
    kb_path = tmp_path / "actions-kb"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "actions-project",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]
    write_unit(kb_path, "core", "PAY", kind="program", phase="inventory")
    reindex = await client.post(f"/api/team/projects/{project_id}/aim/reindex")
    assert reindex.status_code == 200

    units = (await client.get(f"/api/team/projects/{project_id}/aim/units")).json()

    assert units[0]["state_verified"] is True
    assert units[0]["next_action"]["pipeline"] == "aim-understand"
    assert units[0]["next_action"]["allowed"] is False
    assert (
        "rulebook capability understand is template"
        in units[0]["next_action"]["blockers"]
    )
    assert units[0]["claim"] is None


@pytest.mark.asyncio
async def test_understood_unit_routes_through_rule_review_before_design(
    client, tmp_path
):
    from uuid import uuid4

    from app.services.aim.business_rules import confirm_no_business_rules
    from app.services.aim.kb_store import write_transition_event, write_unit

    source = _make_local_repo(tmp_path, "rules-source")
    target = _make_local_repo(tmp_path, "rules-target")
    kb_path = tmp_path / "rules-kb"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "rules-project",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]
    transition_id = write_transition_event(
        kb_path,
        "core",
        "PAY",
        from_phase="inventory",
        to_phase="understood",
        revision=1,
        workflow_name="aim-understand",
        workflow_execution_id=str(uuid4()),
        session_id=None,
        evidence_refs=["modules/core/PAY.md"],
    )
    write_unit(
        kb_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        body="Documented behavior.",
        revision=1,
        last_transition_id=transition_id,
    )
    await client.post(f"/api/team/projects/{project_id}/aim/reindex")

    before = (await client.get(f"/api/team/projects/{project_id}/aim/units")).json()
    confirm_no_business_rules(kb_path, "core/PAY", str(uuid4()))
    after = (await client.get(f"/api/team/projects/{project_id}/aim/units")).json()

    assert before[0]["next_action"]["pipeline"] == "aim-review-rules"
    assert before[0]["next_action"]["target_phase"] == "understood"
    assert after[0]["next_action"]["pipeline"] == "aim-design-unit"
    assert after[0]["next_action"]["target_phase"] == "designed"


@pytest.mark.asyncio
async def test_reconcile_legacy_state_creates_verified_baseline(client, tmp_path):
    import yaml

    from app.services.aim.kb_store import write_unit

    source = _make_local_repo(tmp_path, "legacy-source")
    target = _make_local_repo(tmp_path, "legacy-target")
    kb_path = tmp_path / "legacy-kb"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "legacy-project",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]
    manifest_path = kb_path / "aim.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["state_schema"] = 1
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    write_unit(
        kb_path,
        "core",
        "PAY",
        kind="program",
        phase="converted",
        target_paths=["src/Pay.java"],
    )
    await client.post(f"/api/team/projects/{project_id}/aim/reindex")

    response = await client.post(
        f"/api/team/projects/{project_id}/aim/reconcile-state",
        json={"confirmation": "accept-current-state"},
    )

    assert response.status_code == 200
    assert response.json()["reconciled"] == 1
    units = (await client.get(f"/api/team/projects/{project_id}/aim/units")).json()
    assert units[0]["state_verified"] is True
    assert units[0]["revision"] == 1


@pytest.mark.asyncio
async def test_project_health_surfaces_runner_and_target_base_blockers(
    client, tmp_path
):
    source = _make_local_repo(tmp_path, "health-source")
    target = _make_local_repo(tmp_path, "health-target")
    kb_path = tmp_path / "health-kb"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "health-project",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]

    response = await client.get(f"/api/team/projects/{project_id}/aim/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    checks = {check["id"]: check for check in body["checks"]}
    assert checks["target_base"]["status"] == "fail"
    assert checks["runners"]["status"] == "fail"
    assert checks["capabilities"]["status"] == "fail"


@pytest.mark.asyncio
async def test_project_approval_inbox_aggregates_live_gates(client, tmp_path):
    from app.agent.ask_user import (
        AskUserRequest,
        AskUserService,
        reset_ask_user_service,
        set_ask_user_service,
    )
    from app.agent.tools.builtin.ask_user import QuestionSpec
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    project, *_ = await _make_aim_project_with_units(tmp_path)
    async with db_module.async_session_factory() as db:
        session = ChatSession(
            mode="aim",
            project_id=project.id,
            workspace=str(tmp_path),
            title="PAY · design",
        )
        db.add(session)
        await db.flush()
        execution = WorkflowExecution(
            definition_name="aim-design-unit",
            definition_hash="hash",
            session_id=session.id,
            status="waiting_gate",
        )
        db.add(execution)
        await db.commit()

    service = AskUserService(str(session.id))
    request = AskUserRequest.create(
        str(session.id),
        [
            QuestionSpec(
                question="Approve target design?", options=["approve", "reject"]
            )
        ],
    )
    service._pending[request.id] = request
    token = set_ask_user_service(service)
    try:
        response = await client.get(f"/api/team/projects/{project.id}/aim/approvals")
    finally:
        reset_ask_user_service(token, str(session.id))

    assert response.status_code == 200
    approvals = response.json()
    assert len(approvals) == 1
    assert approvals[0]["workflow"] == "aim-design-unit"
    assert approvals[0]["question"] == "Approve target design?"
    assert approvals[0]["options"] == ["approve", "reject"]


@pytest.mark.asyncio
async def test_get_aim_rulebook_returns_manifest_and_files(client, tmp_path):
    source = _make_local_repo(tmp_path, "src-rb")
    target = _make_local_repo(tmp_path, "tgt-rb")
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "rb-view",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(tmp_path / "kb-rb"),
        },
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]

    resp = await client.get(f"/api/team/projects/{project_id}/aim/rulebook")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "rb-view-rulebook"
    assert body["manifest"]["parser_strategy"] == "none"
    assert "source" not in body
    paths = [f["path"] for f in body["files"]]
    assert "rulebook.yaml" in paths
    assert "extractors/structural.example.yaml" in paths
    assert "canonicalizers/default.yaml" in paths


@pytest.mark.asyncio
async def test_get_aim_rulebook_404_without_local_manifest(client, tmp_path):
    source = _make_local_repo(tmp_path, "src-rb2")
    target = _make_local_repo(tmp_path, "tgt-rb2")
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "rb-missing",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(tmp_path / "kb-rb2"),
        },
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]
    (tmp_path / "kb-rb2" / "rulebook" / "rulebook.yaml").unlink()

    resp = await client.get(f"/api/team/projects/{project_id}/aim/rulebook")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_aim_rulebook_404_for_identity_mismatch(client, tmp_path):
    source = _make_local_repo(tmp_path, "src-rb3")
    target = _make_local_repo(tmp_path, "tgt-rb3")
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "rb-mismatch",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(tmp_path / "kb-rb3"),
        },
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]
    rulebook_path = tmp_path / "kb-rb3" / "rulebook" / "rulebook.yaml"
    rulebook_path.write_text(
        rulebook_path.read_text(encoding="utf-8").replace(
            "id: rb-mismatch-rulebook", "id: another-project-rulebook"
        ),
        encoding="utf-8",
    )

    resp = await client.get(f"/api/team/projects/{project_id}/aim/rulebook")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_aim_rulebook_reads_project_customization(client, tmp_path):
    source = _make_local_repo(tmp_path, "src-rb4")
    target = _make_local_repo(tmp_path, "tgt-rb4")
    kb_path = tmp_path / "kb-rb4"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "rb-override",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]

    # Customize the project-local copy after project creation (a teammate's
    # committed rulebook update, in practice).
    override_dir = kb_path / "rulebook"
    (override_dir / "rulebook.yaml").write_text(
        "id: rb-override-rulebook\nversion: '0.1'\n"
        "description: project-specific policy\n"
        "parser_strategy: tree_sitter\n",
        encoding="utf-8",
    )
    (override_dir / "project-policy.md").write_text(
        "# Engagement-specific policy\n", encoding="utf-8"
    )

    resp = await client.get(f"/api/team/projects/{project_id}/aim/rulebook")
    assert resp.status_code == 200
    body = resp.json()
    assert body["manifest"]["description"] == "project-specific policy"
    assert "source" not in body
    paths = [f["path"] for f in body["files"]]
    assert "project-policy.md" in paths


@pytest.mark.asyncio
async def test_get_aim_rulebook_ignores_stale_cached_identity(client, tmp_path):
    source = _make_local_repo(tmp_path, "src-rb-cache")
    target = _make_local_repo(tmp_path, "tgt-rb-cache")
    kb_path = tmp_path / "kb-rb-cache"
    create_resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "cache-source",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    project_id = create_resp.json()["id"]
    async with db_module.async_session_factory() as db:
        project = await db.get(CodingProject, UUID(project_id))
        assert project is not None
        settings = dict(project.settings)
        settings["aim"] = {
            **settings["aim"],
            "rulebook": {"id": "stale-cache", "version": "0"},
        }
        project.settings = settings
        db.add(project)
        await db.commit()

    response = await client.get(f"/api/team/projects/{project_id}/aim/rulebook")

    assert response.status_code == 200
    assert response.json()["id"] == "cache-source-rulebook"


@pytest.mark.asyncio
async def test_summary_returns_phase_counts_and_equivalent_pct(client, tmp_path):
    project, *_ = await _make_aim_project_with_units(tmp_path)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_units"] == 2
    assert body["phase_counts"]["converted"] == 1
    assert body["phase_counts"]["equivalent"] == 1
    assert body["equivalent_pct"] == 50.0
    assert body["latest_run_at"] is not None


@pytest.mark.asyncio
async def test_summary_404_for_non_aim_project(client):
    async with db_module.async_session_factory() as db:
        project = CodingProject(name="coding-proj", kind="coding")
        db.add(project)
        await db.commit()
        await db.refresh(project)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/summary")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_summary_404_for_unknown_project(client):
    resp = await client.get(f"/api/team/projects/{uuid4()}/aim/summary")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_units_returns_all_and_filters_by_phase(client, tmp_path):
    project, unit_a, unit_b, _run = await _make_aim_project_with_units(tmp_path)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/units")
    assert resp.status_code == 200
    names = {u["name"] for u in resp.json()}
    assert names == {"PAYROLL01", "TAXCALC"}

    resp = await client.get(
        f"/api/team/projects/{project.id}/aim/units", params={"phase": "equivalent"}
    )
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "TAXCALC"


@pytest.mark.asyncio
async def test_get_run_embeds_report_json(client, tmp_path):
    project, _unit_a, _unit_b, run = await _make_aim_project_with_units(tmp_path)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/runs/{run.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "pass"
    assert body["report"]["verdict"] == "pass"
    assert body["report"]["diff_count"] == 0


@pytest.mark.asyncio
async def test_get_run_resolves_kb_relative_report_path(client, tmp_path):
    """aim_compare records report_path KB-relative (portable — the KB's
    checkout location is a per-machine detail); the detail endpoint must
    join it against the project's *current* KB workspace path rather than
    the server process's own cwd, or every such run 404s into "no report
    file on this machine" even though the file is right there in the KB."""
    kb_path = tmp_path / "kb-relpath"
    kb_path.mkdir()

    async with db_module.async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(kb_path), kind="repo")
        project = CodingProject(
            name="aim-relpath",
            kind="aim",
            settings={"aim": {"roles": {"kb": [str(ws.id)]}}},
        )
        db.add(project)
        await db.flush()
        db.add(CodingProjectWorkspace(project_id=project.id, workspace_id=ws.id))

        unit = AimUnit(
            project_id=project.id,
            module="m",
            name="A",
            kind="program",
            phase="equivalent",
            wave=0,
        )
        db.add(unit)
        await db.flush()

        report_dir = kb_path / "runs" / "m" / "A" / "somehash"
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(
            json.dumps({"verdict": "pass", "diff_count": 0})
        )

        run = AimRun(
            unit_id=unit.id,
            kind="compare",
            verdict="pass",
            case_set="smoke",
            stats={"diff_count": 0},
            report_path="runs/m/A/somehash/report.json",
        )
        db.add(run)
        await db.commit()
        await db.refresh(project)
        await db.refresh(run)

    resp = await client.get(f"/api/team/projects/{project.id}/aim/runs/{run.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["verdict"] == "pass"
    assert body["report"]["diff_count"] == 0


@pytest.mark.asyncio
async def test_get_run_404_for_unknown_run(client, tmp_path):
    project, *_ = await _make_aim_project_with_units(tmp_path)
    resp = await client.get(f"/api/team/projects/{project.id}/aim/runs/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_404_when_run_belongs_to_other_project(client, tmp_path):
    _project1, _a, _b, run = await _make_aim_project_with_units(tmp_path)
    project2, *_ = await _make_aim_project_with_units(tmp_path)

    resp = await client.get(f"/api/team/projects/{project2.id}/aim/runs/{run.id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Setup wizard: create / preview / join
# ---------------------------------------------------------------------------


def _make_local_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    return repo


@pytest.mark.asyncio
async def test_create_aim_project_route_end_to_end(client, tmp_path):
    source = _make_local_repo(tmp_path, "source-repo")
    target = _make_local_repo(tmp_path, "target-repo")
    kb_path = tmp_path / "kb-repo"

    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "core-batch migration",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "aim"
    assert body["settings"]["aim"]["rulebook"]["id"] == "core-batch-migration-rulebook"
    assert len(body["workspaces"]) == 3
    assert (kb_path / "aim.yaml").exists()


@pytest.mark.asyncio
async def test_create_aim_project_rejects_missing_source_path(client, tmp_path):
    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "source_paths": [str(tmp_path / "does-not-exist")],
            "target_path": str(_make_local_repo(tmp_path, "target")),
            "kb_path": str(tmp_path / "kb"),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_aim_project_accepts_pre_existing_kb_dir(client, tmp_path):
    # The folder convention creates/clones the aim_<name>_document repo
    # BEFORE the project exists (a .git dir, a README...). Scaffolding is
    # gap-fill-only, so a non-empty KB dir without aim.yaml is fine — the
    # pre-existing file must survive.
    kb_path = _make_local_repo(tmp_path, "kb-already-exists")
    (kb_path / "stray.txt").write_text("x")

    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "source_paths": [str(_make_local_repo(tmp_path, "source"))],
            "target_path": str(_make_local_repo(tmp_path, "target")),
            "kb_path": str(kb_path),
        },
    )
    assert resp.status_code == 201
    assert (kb_path / "aim.yaml").exists()
    assert (kb_path / "stray.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_create_aim_project_rejects_kb_that_is_already_an_aim_kb(
    client, tmp_path
):
    kb_path = _make_local_repo(tmp_path, "kb-existing-project")
    (kb_path / "aim.yaml").write_text("rulebook:\n  id: x\n")

    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "source_paths": [str(_make_local_repo(tmp_path, "source"))],
            "target_path": str(_make_local_repo(tmp_path, "target")),
            "kb_path": str(kb_path),
        },
    )
    assert resp.status_code == 422
    assert "join" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_detect_aim_layout_route(client, tmp_path):
    root = tmp_path / "core-batch"
    (root / "aim_source_base" / "repo-a").mkdir(parents=True)
    (root / "aim_core-batch_document").mkdir(parents=True)
    (root / "aim_target_source").mkdir(parents=True)

    resp = await client.post(
        "/api/team/projects/aim/detect", params={"root_path": str(root)}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_name"] == "core-batch"
    assert body["has_manifest"] is False
    assert [Path(p).name for p in body["source_paths"]] == ["repo-a"]
    assert Path(body["kb_path"]).name == "aim_core-batch_document"
    assert Path(body["target_path"]).name == "aim_target_source"


@pytest.mark.asyncio
async def test_detect_aim_layout_route_rejects_nonconforming_folder(client, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    resp = await client.post(
        "/api/team/projects/aim/detect", params={"root_path": str(plain)}
    )
    assert resp.status_code == 422
    assert "aim_source_base" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_preview_aim_project_route(client, tmp_path):
    source = _make_local_repo(tmp_path, "source-repo")
    target = _make_local_repo(tmp_path, "target-repo")
    kb_path = tmp_path / "kb-repo"
    await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )

    resp = await client.post(
        "/api/team/projects/aim/preview", params={"kb_path": str(kb_path)}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rulebook_id"] == "p-rulebook"
    assert body["rulebook_version"] == "0.1"
    assert body["source_identities"] == ["source-repo"]


@pytest.mark.asyncio
async def test_preview_aim_project_missing_kb_returns_422(client, tmp_path):
    resp = await client.post(
        "/api/team/projects/aim/preview",
        params={"kb_path": str(tmp_path / "nope")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_join_aim_project_route_end_to_end(client, tmp_path):
    source1 = _make_local_repo(tmp_path, "source-a")
    target1 = _make_local_repo(tmp_path, "target-a")
    kb_path = tmp_path / "shared-kb"
    await client.post(
        "/api/team/projects/aim",
        json={
            "name": "original",
            "source_paths": [str(source1)],
            "target_path": str(target1),
            "kb_path": str(kb_path),
        },
    )

    source2 = _make_local_repo(tmp_path, "source-b-local")
    target2 = _make_local_repo(tmp_path, "target-b-local")
    resp = await client.post(
        "/api/team/projects/aim/join",
        json={
            "name": "joined",
            "kb_path": str(kb_path),
            "source_paths": [str(source2)],
            "target_path": str(target2),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "aim"
    assert body["settings"]["aim"]["rulebook"]["id"] == "original-rulebook"


@pytest.mark.asyncio
async def test_join_aim_project_missing_kb_returns_422(client, tmp_path):
    resp = await client.post(
        "/api/team/projects/aim/join",
        json={
            "name": "x",
            "kb_path": str(tmp_path / "no-such-kb"),
            "source_paths": [str(_make_local_repo(tmp_path, "s"))],
            "target_path": str(_make_local_repo(tmp_path, "t")),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_aim_meta_serves_backend_phase_vocabulary(client):
    from app.services.aim.models import VALID_PHASES, VALID_PROJECT_PHASES

    resp = await client.get("/api/team/projects/aim/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unit_phases"] == list(VALID_PHASES)
    assert body["project_phases"] == list(VALID_PROJECT_PHASES)
    # Every phase has a label and an eligibility entry (None allowed).
    assert set(body["phase_labels"]) == set(VALID_PHASES)
    assert set(body["phase_next_pipeline"]) == set(VALID_PHASES)
    assert body["phase_next_pipeline"]["inventory"] == "aim-understand"
    assert body["phase_next_pipeline"]["understood"] == "aim-design-unit"
    assert body["phase_next_pipeline"]["designed"] == "aim-convert-unit"
    assert body["phase_next_pipeline"]["cutover"] is None
