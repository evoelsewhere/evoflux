"""Runner core (M3): headless walk, SSE progress, rows, stop, /run contract."""

from __future__ import annotations

import asyncio

import pytest
from sqlmodel import col, select

import app.models.workflow  # noqa: F401 — register tables before setup_db
from app.workflow.models import parse_definition
from app.workflow.policy import content_hash
from app.workflow.runner import WorkflowRunner

HEADLESS = """
schema_version: 1
name: headless
scope: forge
inputs:
  - { name: level, type: string, required: true }
nodes:
  - id: probe
    kind: tool
    tool: shell
    args: { command: "echo severity={{inputs.level}}" }
  - id: shape
    kind: transform
    set:
      summary: "probe said {{nodes.probe.output.text | truncate:40}}"
      level: "{{inputs.level}}"
  - id: route
    kind: switch
    value: "{{nodes.shape.output.level}}"
  - id: alarm
    kind: notify
    title: "headless"
    message: "CRITICAL: {{nodes.shape.output.summary}}"
  - id: chill
    kind: notify
    message: "all calm"
edges:
  - { from: probe, to: shape }
  - { from: shape, to: route }
  - { from: route, to: alarm, when: critical }
  - { from: route, to: chill, when: "*" }
outputs:
  level: "{{nodes.route.output.value}}"
"""


async def _wait_done(runner: WorkflowRunner, session_id: str, timeout: float = 15.0):
    for _ in range(int(timeout * 20)):
        if not runner.is_driving(session_id):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("execution did not finish in time")


@pytest.fixture
def progress_events(monkeypatch):
    events: list[dict] = []
    from app.services import memory_stream_store

    original = memory_stream_store.push_event

    async def _capture(session_id, envelope):
        data = getattr(envelope, "data", None) or {}
        if isinstance(data, dict) and data.get("type") in (
            "workflow_progress",
            "desktop_notification",
        ):
            events.append(data)
        return await original(session_id, envelope)

    monkeypatch.setattr(memory_stream_store, "push_event", _capture)
    return events


@pytest.mark.asyncio
async def test_headless_walk_runs_to_completion_with_rows(setup_db, progress_events):
    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution, WorkflowNodeRun

    runner = WorkflowRunner()
    definition = parse_definition(HEADLESS)
    session_id = "06a58f00-0000-7000-8000-000000000001"

    state = await runner.start(
        definition,
        definition_hash=content_hash(HEADLESS.encode()),
        session_id=session_id,
        inputs={"level": "critical"},
        scope_workspace=None,
    )
    await _wait_done(runner, session_id)

    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution is not None
        assert execution.status == "completed"
        assert execution.outputs == {"level": "critical"}
        rows = (
            await db.exec(
                select(WorkflowNodeRun).where(
                    col(WorkflowNodeRun.execution_id) == state.execution_id
                )
            )
        ).all()
        by_node = {row.node_id: row for row in rows}
        assert by_node["probe"].status == "succeeded"
        assert "severity=critical" in by_node["probe"].output["text"]
        assert by_node["route"].status == "succeeded"
        assert by_node["alarm"].status == "succeeded"
        # The '*' branch died — chill never ran.
        assert "chill" not in by_node

    statuses = [
        e["status"] for e in progress_events if e["type"] == "workflow_progress"
    ]
    assert statuses[0] == "running"
    assert statuses[-1] == "completed"
    notifications = [e for e in progress_events if e["type"] == "desktop_notification"]
    assert any("CRITICAL" in n["body"] for n in notifications)


@pytest.mark.asyncio
async def test_template_failure_fails_execution(setup_db):
    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: broken-template
nodes:
  - { id: t, kind: transform, set: { x: "{{nodes.ghost.output.y}}" } }
""")
    session_id = "06a58f00-0000-7000-8000-000000000002"
    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait_done(runner, session_id)

    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "failed"
        assert "does not resolve" in (execution.error or "")


@pytest.mark.asyncio
async def test_phase2_kinds_refused(setup_db):
    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: phase2
nodes:
  - { id: w, kind: wait, seconds: 5 }
""")
    session_id = "06a58f00-0000-7000-8000-000000000003"
    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait_done(runner, session_id)
    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "failed"
        assert "Phase 2" in (execution.error or "")


@pytest.mark.asyncio
async def test_double_start_rejected_and_stop_works(setup_db):
    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: slowpoke
nodes:
  - id: nap
    kind: tool
    tool: shell
    args: { command: "sleep 30" }
""")
    session_id = "06a58f00-0000-7000-8000-000000000004"
    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    with pytest.raises(RuntimeError, match="already active"):
        await runner.start(
            definition,
            definition_hash="0" * 64,
            session_id=session_id,
            inputs={},
            scope_workspace=None,
        )
    await asyncio.sleep(0.2)
    assert await runner.stop(state.execution_id) is True
    await _wait_done(runner, session_id, timeout=5)
    assert runner.is_driving(session_id) is False


# ── /run endpoint contract ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_endpoint_contract(setup_db, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.routes.workflows import router as workflows_router
    from app.core import db as db_module
    from app.core.config import settings as app_settings
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api/workflows")
    transport = ASGITransport(app=app)

    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = str(session.id)

    raw = HEADLESS
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        saved = await client.put("/api/workflows/headless", json={"raw_yaml": raw})
        assert saved.status_code == 200
        file_hash = saved.json()["hash"]

        # Unapproved → 403.
        forbidden = await client.post(
            "/api/workflows/headless/run",
            json={"session_id": session_id, "inputs": {"level": "calm"}},
        )
        assert forbidden.status_code == 403

        await client.post("/api/workflows/headless/approve", json={"hash": file_hash})

        # Missing required input → 422.
        missing = await client.post(
            "/api/workflows/headless/run", json={"session_id": session_id, "inputs": {}}
        )
        assert missing.status_code == 422

        run = await client.post(
            "/api/workflows/headless/run",
            json={"session_id": session_id, "inputs": {"level": "calm"}},
        )
        assert run.status_code == 200
        execution_id = run.json()["execution_id"]

        from app.workflow.runner import runner as global_runner

        await _wait_done(global_runner, session_id)

        detail = await client.get(f"/api/workflows/executions/{execution_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["execution"]["status"] == "completed"
        node_ids = [r["node_id"] for r in body["node_runs"]]
        assert node_ids[:3] == ["probe", "shape", "route"]
        # 'calm' hits the '*' default branch.
        assert "chill" in node_ids

    async with db_module.async_session_factory() as db:
        from uuid import UUID as _UUID

        execution = await db.get(WorkflowExecution, _UUID(execution_id))
        assert execution.outputs == {"level": "calm"}


@pytest.mark.asyncio
async def test_list_executions_by_session_ids(setup_db, tmp_path, monkeypatch):
    """GET /executions?session_ids= returns newest-first rows for exactly the
    requested sessions (the AIM Pipelines table's status join)."""
    from uuid import uuid4

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.routes.workflows import router as workflows_router
    from app.core import db as db_module
    from app.core.config import settings as app_settings
    from app.models.workflow import WorkflowExecution

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api/workflows")
    transport = ASGITransport(app=app)

    session_a, session_b, session_other = uuid4(), uuid4(), uuid4()
    async with db_module.async_session_factory() as db:
        db.add(
            WorkflowExecution(
                definition_name="aim-assess",
                definition_hash="0" * 64,
                session_id=session_a,
                status="completed",
            )
        )
        db.add(
            WorkflowExecution(
                definition_name="aim-convert-unit",
                definition_hash="0" * 64,
                session_id=session_b,
                status="failed",
                error="boom",
            )
        )
        db.add(
            WorkflowExecution(
                definition_name="unrelated",
                definition_hash="0" * 64,
                session_id=session_other,
                status="running",
            )
        )
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        res = await client.get(
            f"/api/workflows/executions?session_ids={session_a},{session_b}"
        )
        assert res.status_code == 200
        rows = res.json()["executions"]
        assert {r["session_id"] for r in rows} == {str(session_a), str(session_b)}
        by_session = {r["session_id"]: r for r in rows}
        assert by_session[str(session_b)]["status"] == "failed"
        assert by_session[str(session_b)]["error"] == "boom"

        # Empty / whitespace-only list short-circuits to [].
        empty = await client.get("/api/workflows/executions?session_ids=")
        assert empty.status_code == 200
        assert empty.json()["executions"] == []

        # Malformed uuid → 422, not 500.
        bad = await client.get("/api/workflows/executions?session_ids=not-a-uuid")
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_run_scope_mismatch_rejected(setup_db, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.routes.workflows import router as workflows_router
    from app.core import db as db_module
    from app.core.config import settings as app_settings
    from app.models.chat import ChatSession

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api/workflows")
    transport = ASGITransport(app=app)

    async with db_module.async_session_factory() as db:
        forge_session = ChatSession(mode="forge")
        db.add(forge_session)
        await db.commit()
        await db.refresh(forge_session)

    aim_flow = """
schema_version: 1
name: aim-only
scope: aim
nodes:
  - { id: n, kind: notify, message: hi }
"""
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        saved = await client.put("/api/workflows/aim-only", json={"raw_yaml": aim_flow})
        await client.post(
            "/api/workflows/aim-only/approve", json={"hash": saved.json()["hash"]}
        )
        resp = await client.post(
            "/api/workflows/aim-only/run",
            json={"session_id": str(forge_session.id), "inputs": {}},
        )
        assert resp.status_code == 422
        assert "aim session" in resp.json()["detail"]
