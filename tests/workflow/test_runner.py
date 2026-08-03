"""Runner core (M3): headless walk, SSE progress, rows, stop, /run contract."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlmodel import col, select

import app.models.workflow  # noqa: F401 — register tables before setup_db
from app.workflow.models import parse_definition
from app.workflow.policy import content_hash
from app.workflow.runner import WorkflowRunner

HEADLESS = """
schema_version: 1
name: headless
scope: work
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


@pytest.mark.asyncio
async def test_work_team_boot_uses_persisted_workspace(setup_db, monkeypatch, tmp_path):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    session_id = "06a58f00-0000-7000-8000-000000000010"
    session_uuid = UUID(session_id)
    workspace = tmp_path / "persisted-work-workspace"
    workspace.mkdir()
    async with db_module.async_session_factory() as db:
        db.add(
            ChatSession(
                id=session_uuid,
                agent_name="lead",
                mode="work",
                workspace=str(workspace),
            )
        )
        await db.commit()

    team = SimpleNamespace(workspace=None, mode="work")
    monkeypatch.setattr(
        "app.services.team_manager.find_team_for_session",
        lambda _session_id: None,
    )

    async def get_team(_session_id: str):
        return team

    monkeypatch.setattr(
        "app.services.team_manager.get_or_start_team_for_session",
        get_team,
    )
    state = SimpleNamespace(
        session_id=session_id,
        definition=SimpleNamespace(scope="work"),
        scope_workspace=None,
    )

    restored = await WorkflowRunner()._ensure_team(state)

    assert restored is team
    assert team.workspace == str(workspace)


@pytest.mark.asyncio
async def test_work_workspace_reset_does_not_restore_stale_workflow_scope(setup_db):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    session_id = "06a58f00-0000-7000-8000-000000000011"
    session_uuid = UUID(session_id)
    async with db_module.async_session_factory() as db:
        db.add(
            ChatSession(
                id=session_uuid,
                agent_name="lead",
                mode="work",
                workspace=None,
            )
        )
        await db.commit()

    state = SimpleNamespace(
        session_id=session_id,
        definition=SimpleNamespace(scope="work"),
        scope_workspace="/stale/custom/workspace",
    )

    mode, workspace = await WorkflowRunner()._session_mode_workspace(state)

    assert mode == "work"
    assert workspace is None


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
        assert execution.inputs == {"level": "critical"}
        assert execution.retry_of_execution_id is None
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
async def test_outputs_omit_only_keys_from_skipped_branches(setup_db):
    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: partial-outputs
scope: work
nodes:
    - { id: route, kind: switch, value: selected }
    - { id: selected, kind: transform, set: { result: kept } }
    - { id: skipped, kind: transform, set: { result: omitted } }
edges:
    - { from: route, to: selected, when: selected }
    - { from: route, to: skipped, when: skipped }
outputs:
    always: "{{nodes.selected.output.result}}"
    branch_only: "{{nodes.skipped.output.result}}"
""")
    session_id = "06a58f00-0000-7000-8000-000000000099"

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
        assert execution.outputs == {"always": "kept"}


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
async def test_double_start_rejected_and_stop_works(setup_db, monkeypatch):
    async def block_until_cancelled(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.workflow.runner.run_tool_node", block_until_cancelled)
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


# ── gate / input human-control round trip ─────────────────────────────────────

GATE = """
schema_version: 1
name: gate-race
scope: work
nodes:
  - id: approve
    kind: gate
    title: "Ship it?"
    choices: ["approve", "reject"]
  - { id: shipped, kind: transform, set: { result: shipped } }
edges:
  - { from: approve, to: shipped, when: approve }
outputs:
  choice: "{{nodes.approve.output.choice}}"
"""


def _reply_like_the_rest_endpoint(session_id: str, answers: list[str]) -> list[bool]:
    """Resolve every pending ask for *session_id* the way the reply route does.

    Mirrors ``app.api.routes.team.questions.reply_question``: an empty result
    is exactly the 404 ("not found or already resolved") a client would get.
    """
    from app.agent.ask_user import get_services_for_stream

    outcomes: list[bool] = []
    for service in get_services_for_stream(session_id):
        for request_id in list(service._pending):
            assert service.validate_answers(request_id, answers) is None
            outcomes.append(service.reply(request_id, answers))
    return outcomes


@pytest.mark.asyncio
async def test_gate_reply_is_accepted_the_instant_waiting_gate_is_published(
    setup_db, monkeypatch
):
    """A client that replies the moment it sees ``waiting_gate`` must win.

    The pending ask has to be registered before the pause is published;
    otherwise the reply endpoint has nothing to resolve and 404s.
    """
    from app.services import memory_stream_store

    session_id = "06a58f00-0000-7000-8000-0000000000a1"
    original = memory_stream_store.push_event
    replies: list[list[bool]] = []

    async def _reply_on_waiting_gate(sid, envelope):
        result = await original(sid, envelope)
        data = getattr(envelope, "data", None) or {}
        if (
            isinstance(data, dict)
            and data.get("type") == "workflow_progress"
            and data.get("status") == "waiting_gate"
            and not replies
        ):
            replies.append(_reply_like_the_rest_endpoint(session_id, ["approve"]))
            if not replies[0]:
                # Unblock the run so the assertion below reports the race
                # instead of hanging until the 24h gate timeout.
                asyncio.get_running_loop().create_task(_late_reply())
        return result

    async def _late_reply() -> None:
        for _ in range(100):
            await asyncio.sleep(0.05)
            if _reply_like_the_rest_endpoint(session_id, ["approve"]):
                return

    monkeypatch.setattr(memory_stream_store, "push_event", _reply_on_waiting_gate)

    runner = WorkflowRunner()
    state = await runner.start(
        parse_definition(GATE),
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait_done(runner, session_id)

    assert replies == [[True]], (
        "no pending gate existed when waiting_gate was published"
    )

    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution, WorkflowGateRequest

    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "completed"
        assert execution.outputs == {"choice": "approve"}
        gate = (
            await db.exec(
                select(WorkflowGateRequest).where(
                    col(WorkflowGateRequest.execution_id) == state.execution_id
                )
            )
        ).one()
        assert gate.status == "answered"
        assert gate.answers == ["approve"]


@pytest.mark.asyncio
async def test_gate_second_reply_is_rejected_without_a_duplicate_resume(
    setup_db, monkeypatch
):
    """Double-reply and wrong-session replies must be clean rejections."""
    from app.services import memory_stream_store

    session_id = "06a58f00-0000-7000-8000-0000000000a2"
    original = memory_stream_store.push_event
    outcomes: list[list[bool]] = []

    async def _reply_twice(sid, envelope):
        result = await original(sid, envelope)
        data = getattr(envelope, "data", None) or {}
        if (
            isinstance(data, dict)
            and data.get("type") == "workflow_progress"
            and data.get("status") == "waiting_gate"
            and not outcomes
        ):
            # A reply addressed to some other session must never resolve ours.
            wrong_session = _reply_like_the_rest_endpoint(
                "06a58f00-0000-7000-8000-0000000000ff", ["approve"]
            )
            assert wrong_session == []
            outcomes.append(_reply_like_the_rest_endpoint(session_id, ["approve"]))
            outcomes.append(_reply_like_the_rest_endpoint(session_id, ["reject"]))
        return result

    monkeypatch.setattr(memory_stream_store, "push_event", _reply_twice)

    runner = WorkflowRunner()
    state = await runner.start(
        parse_definition(GATE),
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait_done(runner, session_id)

    assert outcomes == [[True], [False]]

    from app.core import db as db_module
    from app.models.workflow import WorkflowExecution

    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "completed"
        # The second (rejecting) reply must not have re-routed the run.
        assert execution.outputs == {"choice": "approve"}


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
        session = ChatSession(mode="work")
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

        # A crashed process can leave an execution row as running even though
        # the in-memory runner no longer owns it. Retry must reconcile that
        # orphan instead of rejecting the exact state the UI calls interrupted.
        from uuid import uuid7

        interrupted_id = uuid7()
        async with db_module.async_session_factory() as db:
            db.add(
                WorkflowExecution(
                    id=interrupted_id,
                    definition_name="headless",
                    definition_hash=file_hash,
                    session_id=session.id,
                    status="running",
                    inputs={"level": "calm"},
                )
            )
            await db.commit()

        retry = await client.post(
            "/api/workflows/headless/run",
            json={
                "session_id": session_id,
                "inputs": {"level": "calm"},
                "retry_of_execution_id": str(interrupted_id),
            },
        )
        assert retry.status_code == 200
        await _wait_done(global_runner, session_id)
        retry_id = retry.json()["execution_id"]

    async with db_module.async_session_factory() as db:
        from uuid import UUID as _UUID

        execution = await db.get(WorkflowExecution, _UUID(execution_id))
        assert execution.outputs == {"level": "calm"}
        interrupted = await db.get(WorkflowExecution, interrupted_id)
        assert interrupted.status == "failed"
        assert "interrupted" in interrupted.error
        retried = await db.get(WorkflowExecution, _UUID(retry_id))
        assert retried.retry_of_execution_id == interrupted_id
        assert retried.status == "completed"


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
    running_execution = WorkflowExecution(
        definition_name="aim-convert-unit",
        definition_hash="0" * 64,
        session_id=session_b,
        status="running",
    )
    async with db_module.async_session_factory() as db:
        db.add(
            WorkflowExecution(
                definition_name="aim-assess",
                definition_hash="0" * 64,
                session_id=session_a,
                status="completed",
            )
        )
        db.add(running_execution)
        db.add(
            WorkflowExecution(
                definition_name="unrelated",
                definition_hash="0" * 64,
                session_id=session_other,
                status="running",
            )
        )
        await db.commit()
        running_id = running_execution.id

    # `live` reflects the in-memory runner, not the DB status — session_b's
    # row is driven, session_other's identical 'running' row is an orphan.
    import types

    from app.workflow.runner import runner as global_runner

    global_runner.active[str(session_b)] = types.SimpleNamespace(
        execution_id=running_id
    )
    try:
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            res = await client.get(
                f"/api/workflows/executions?session_ids={session_a},{session_b}"
            )
            assert res.status_code == 200
            rows = res.json()["executions"]
            assert {r["session_id"] for r in rows} == {str(session_a), str(session_b)}
            by_session = {r["session_id"]: r for r in rows}
            assert by_session[str(session_b)]["status"] == "running"
            assert by_session[str(session_b)]["live"] is True
            assert by_session[str(session_a)]["live"] is False

            # Empty / whitespace-only list short-circuits to [].
            empty = await client.get("/api/workflows/executions?session_ids=")
            assert empty.status_code == 200
            assert empty.json()["executions"] == []

            # Malformed uuid → 422, not 500.
            bad = await client.get("/api/workflows/executions?session_ids=not-a-uuid")
            assert bad.status_code == 422
    finally:
        global_runner.active.pop(str(session_b), None)


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
        work_session = ChatSession(mode="work")
        db.add(work_session)
        await db.commit()
        await db.refresh(work_session)

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
            json={"session_id": str(work_session.id), "inputs": {}},
        )
        assert resp.status_code == 422
        assert "aim session" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_concurrent_assessment_in_same_project_rejected(
    setup_db, tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.routes.workflows import router as workflows_router
    from app.core import db as db_module
    from app.core.config import settings as app_settings
    from app.models.chat import ChatSession, CodingProject
    from app.models.workflow import WorkflowExecution

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api/workflows")
    transport = ASGITransport(app=app)
    workspace = tmp_path / "target"
    workspace.mkdir()

    async with db_module.async_session_factory() as db:
        project = CodingProject(name="assessment-lock", kind="aim")
        db.add(project)
        await db.flush()
        first = ChatSession(mode="aim", project_id=project.id, workspace=str(workspace))
        second = ChatSession(
            mode="aim", project_id=project.id, workspace=str(workspace)
        )
        db.add(first)
        db.add(second)
        await db.flush()
        db.add(
            WorkflowExecution(
                definition_name="aim-assess",
                definition_hash="existing",
                session_id=first.id,
                status="running",
            )
        )
        await db.commit()
        second_id = second.id

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        saved = await client.put(
            "/api/workflows/aim-assess",
            json={
                "raw_yaml": (
                    "schema_version: 1\n"
                    "name: aim-assess\n"
                    "scope: aim\n"
                    "nodes:\n"
                    "  - {id: done, kind: notify, message: done}\n"
                )
            },
        )
        await client.post(
            "/api/workflows/aim-assess/approve",
            json={"hash": saved.json()["hash"]},
        )
        response = await client.post(
            "/api/workflows/aim-assess/run",
            json={"session_id": str(second_id), "inputs": {}},
        )

    assert response.status_code == 409
    assert "already active" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reconcile_orphaned_executions_fails_live_rows(setup_db):
    """A restart leaves running/waiting_gate rows the in-memory runner can no
    longer drive; reconciliation must fail them so nothing shows live forever."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4, uuid7

    from app.core import db as db_module
    from app.models.aim import AimClaim, AimUnit
    from app.models.chat import CodingProject
    from app.models.workflow import (
        WorkflowExecution,
        WorkflowGateRequest,
        WorkflowNodeRun,
    )
    from app.workflow.runner import reconcile_orphaned_executions

    running_id = uuid7()
    gate_id = uuid7()
    done_id = uuid7()
    async with db_module.async_session_factory() as db:
        project = CodingProject(name="reconcile-aim", kind="aim")
        db.add(project)
        await db.flush()
        unit = AimUnit(
            project_id=project.id,
            module="m",
            name="A",
            kind="program",
        )
        db.add(unit)
        await db.flush()
        db.add(
            WorkflowExecution(
                id=running_id,
                definition_name="w",
                definition_hash="h",
                session_id=uuid4(),
                status="running",
            )
        )
        db.add(
            WorkflowExecution(
                id=gate_id,
                definition_name="w",
                definition_hash="h",
                session_id=uuid4(),
                status="waiting_gate",
            )
        )
        db.add(
            WorkflowExecution(
                id=done_id,
                definition_name="w",
                definition_hash="h",
                session_id=uuid4(),
                status="completed",
            )
        )
        db.add(
            WorkflowNodeRun(execution_id=gate_id, node_id="certify", status="running")
        )
        db.add(
            WorkflowGateRequest(
                execution_id=gate_id,
                node_id="certify",
                kind="gate",
                request_id=str(uuid4()),
                question="Certify?",
                options=["certify", "hold"],
            )
        )
        claim = AimClaim(
            project_id=project.id,
            unit_id=unit.id,
            workflow_execution_id=gate_id,
            workflow_name="w",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        db.add(claim)
        await db.commit()
        claim_id = claim.id

    count = await reconcile_orphaned_executions()
    assert count == 2

    async with db_module.async_session_factory() as db:
        assert (await db.get(WorkflowExecution, running_id)).status == "failed"
        gate_row = await db.get(WorkflowExecution, gate_id)
        assert gate_row.status == "failed"
        assert "restart" in (gate_row.error or "")
        assert (await db.get(WorkflowExecution, done_id)).status == "completed"
        node = (
            await db.exec(
                select(WorkflowNodeRun).where(WorkflowNodeRun.execution_id == gate_id)
            )
        ).one()
        assert node.status == "failed"
        gate = (
            await db.exec(
                select(WorkflowGateRequest).where(
                    WorkflowGateRequest.execution_id == gate_id
                )
            )
        ).one()
        assert gate.status == "interrupted"
        assert gate.resolved_at is not None
        assert await db.get(AimClaim, claim_id) is None


@pytest.mark.asyncio
async def test_reconcile_on_unmigrated_schema_logs_and_continues(monkeypatch):
    """Reconciliation is deliberately non-fatal.

    The lifespan runs it after production migrations, but a schema that is
    still missing the workflow tables (fresh dev DB, failed migration) must
    log and return 0 rather than abort startup.
    """
    from loguru import logger
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core import db as db_module
    from app.workflow.runner import reconcile_orphaned_executions

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(
        db_module,
        "async_session_factory",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    warnings: list[str] = []
    sink_id = logger.add(
        lambda message: warnings.append(message.record["message"]), level="WARNING"
    )
    try:
        assert await reconcile_orphaned_executions() == 0
    finally:
        logger.remove(sink_id)
        await engine.dispose()

    # The swallowed failure must stay visible in the logs — it is the only
    # signal that live-looking runs were left unreconciled.
    assert any("workflow_reconcile_failed" in message for message in warnings)


@pytest.mark.asyncio
async def test_terminal_cleanup_releases_execution_claims(setup_db):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid7

    from app.core import db as db_module
    from app.models.aim import AimClaim, AimUnit
    from app.models.chat import CodingProject
    from app.workflow.runner import WorkflowRunner

    execution_id = uuid7()
    async with db_module.async_session_factory() as db:
        project = CodingProject(name="cleanup-aim", kind="aim")
        db.add(project)
        await db.flush()
        unit = AimUnit(
            project_id=project.id,
            module="m",
            name="A",
            kind="program",
        )
        db.add(unit)
        await db.flush()
        claim = AimClaim(
            project_id=project.id,
            unit_id=unit.id,
            workflow_execution_id=execution_id,
            workflow_name="aim-convert-unit",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        db.add(claim)
        await db.commit()
        claim_id = claim.id

    await WorkflowRunner()._release_execution_claims(execution_id)

    async with db_module.async_session_factory() as db:
        assert await db.get(AimClaim, claim_id) is None


@pytest.mark.asyncio
async def test_claim_heartbeat_extends_execution_lease(setup_db):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid7

    from app.core import db as db_module
    from app.models.aim import AimClaim, AimUnit
    from app.models.chat import CodingProject
    from app.workflow.runner import WorkflowRunner

    execution_id = uuid7()
    async with db_module.async_session_factory() as db:
        project = CodingProject(name="heartbeat-aim", kind="aim")
        db.add(project)
        await db.flush()
        unit = AimUnit(
            project_id=project.id,
            module="m",
            name="A",
            kind="program",
        )
        db.add(unit)
        await db.flush()
        old_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        claim = AimClaim(
            project_id=project.id,
            unit_id=unit.id,
            workflow_execution_id=execution_id,
            workflow_name="aim-understand",
            lease_expires_at=old_expiry,
        )
        db.add(claim)
        await db.commit()
        claim_id = claim.id

    renewed = await WorkflowRunner()._renew_execution_claims(execution_id)

    assert renewed == 1
    async with db_module.async_session_factory() as db:
        claim = await db.get(AimClaim, claim_id)
        assert claim is not None
        assert claim.lease_expires_at > old_expiry + timedelta(hours=3)
