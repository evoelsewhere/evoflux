"""Tests for /api/team/projects/{id}/aim/* HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.db as db_module
from app.api.routes.team.projects import router as projects_router
from app.models.aim import AimRun, AimUnit
from app.models.chat import CodingProject


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
            "rulebook_id": "java8-java21",
            "rulebook_version": "0.1",
            "source_paths": [str(source)],
            "target_path": str(target),
            "kb_path": str(kb_path),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "aim"
    assert body["settings"]["aim"]["rulebook"]["id"] == "java8-java21"
    assert len(body["workspaces"]) == 3
    assert (kb_path / "aim.yaml").exists()


@pytest.mark.asyncio
async def test_create_aim_project_rejects_missing_source_path(client, tmp_path):
    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "rulebook_id": "default",
            "source_paths": [str(tmp_path / "does-not-exist")],
            "target_path": str(_make_local_repo(tmp_path, "target")),
            "kb_path": str(tmp_path / "kb"),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_aim_project_rejects_non_empty_kb_path(client, tmp_path):
    kb_path = _make_local_repo(tmp_path, "kb-already-exists")
    (kb_path / "stray.txt").write_text("x")

    resp = await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "rulebook_id": "default",
            "source_paths": [str(_make_local_repo(tmp_path, "source"))],
            "target_path": str(_make_local_repo(tmp_path, "target")),
            "kb_path": str(kb_path),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preview_aim_project_route(client, tmp_path):
    source = _make_local_repo(tmp_path, "source-repo")
    target = _make_local_repo(tmp_path, "target-repo")
    kb_path = tmp_path / "kb-repo"
    await client.post(
        "/api/team/projects/aim",
        json={
            "name": "p",
            "rulebook_id": "vb6-dotnet",
            "rulebook_version": "0.2",
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
    assert body["rulebook_id"] == "vb6-dotnet"
    assert body["rulebook_version"] == "0.2"
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
            "rulebook_id": "java8-java21",
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
    assert body["settings"]["aim"]["rulebook"]["id"] == "java8-java21"


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
