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
