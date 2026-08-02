"""Tests for app/api/routes/scheduler.py — REST endpoints for scheduled tasks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.db as _db_module
from app.api.routes.scheduler import get_scheduler, router
from app.models.chat import ChatSession
from app.scheduler.models import ScheduledTask
from app.scheduler.scheduler import TaskScheduler


_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_scheduler():
    """An isolated scheduler bound to the in-memory test DB."""
    return TaskScheduler(db_factory=_db_module.async_session_factory)


@pytest.fixture
async def client(fresh_scheduler):
    app = FastAPI()
    app.include_router(router, prefix="/api/scheduler")
    app.dependency_overrides[get_scheduler] = lambda: fresh_scheduler

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c

    await fresh_scheduler.stop()


def _create_payload(**overrides) -> dict:
    payload = {
        "name": "task1",
        "mode": "work",
        "schedule_type": "every",
        "every_seconds": 60,
        "prompt": "hello",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# POST /tasks
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_creates_task_201(self, client):
        resp = await client.post("/api/scheduler/tasks", json=_create_payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "task1"
        assert body["mode"] == "work"
        assert body["workspace"] is None
        assert body["schedule_type"] == "every"
        assert body["every_seconds"] == 60
        assert body["enabled"] is True
        assert body["status"] == "pending"
        assert body["next_fire_at"] is not None

    async def test_coding_mode_requires_workspace(self, client):
        resp = await client.post(
            "/api/scheduler/tasks", json=_create_payload(mode="coding")
        )
        assert resp.status_code == 422
        assert "workspace is required" in resp.text

    async def test_coding_mode_invalid_workspace_422(self, client, tmp_path):
        # Workspace must exist on disk.
        ghost = tmp_path / "does-not-exist"
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(mode="coding", workspace=str(ghost)),
        )
        assert resp.status_code == 422
        assert "Workspace does not exist" in resp.json()["detail"]

    async def test_coding_mode_with_valid_workspace_201(self, client, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="c1", mode="coding", workspace=str(ws)),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mode"] == "coding"
        # Server normalises the workspace path (resolves symlinks, etc.) so
        # compare loosely.
        assert body["workspace"].endswith("ws")

    async def test_duplicate_name_returns_409(self, client):
        first = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="dup")
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="dup")
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"]

    async def test_invalid_schedule_returns_422(self, client):
        # at without at_datetime
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "bad",
                "mode": "work",
                "schedule_type": "at",
                "prompt": "hi",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------


class TestList:
    async def test_empty_list(self, client):
        resp = await client.get("/api/scheduler/tasks")
        assert resp.status_code == 200
        assert resp.json() == {"tasks": []}

    async def test_returns_persisted_tasks(self, client):
        await client.post("/api/scheduler/tasks", json=_create_payload(name="a"))
        await client.post("/api/scheduler/tasks", json=_create_payload(name="b"))
        resp = await client.get("/api/scheduler/tasks")
        assert resp.status_code == 200
        names = sorted(t["name"] for t in resp.json()["tasks"])
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_task(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="findable")
        )
        task_id = created.json()["id"]

        resp = await client.get(f"/api/scheduler/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "findable"

    async def test_unknown_id_returns_404(self, client):
        resp = await client.get(f"/api/scheduler/tasks/{uuid4()}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PUT /tasks/{task_id}
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_updates_fields(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="upd")
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"every_seconds": 30, "prompt": "new prompt"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["every_seconds"] == 30
        assert body["prompt"] == "new prompt"

    async def test_update_to_coding_requires_workspace(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="upd2")
        )
        task_id = created.json()["id"]

        # Existing task has workspace=None; switching to mode=coding without
        # supplying a workspace must 422.
        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"mode": "coding"},
        )
        assert resp.status_code == 422

    async def test_update_to_coding_with_workspace(self, client, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="upd3")
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"mode": "coding", "workspace": str(ws)},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "coding"

    async def test_update_from_coding_to_work_clears_workspace(self, client, tmp_path):
        ws = tmp_path / "ws-to-clear"
        ws.mkdir()
        created = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="clear-ws", mode="coding", workspace=str(ws)),
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}", json={"mode": "work"}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == "work"
        assert resp.json()["workspace"] is None

    async def test_schedule_type_transition_requires_new_type_fields(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="bad-transition")
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}", json={"schedule_type": "at"}
        )

        assert resp.status_code == 422
        assert "at_datetime is required" in resp.json()["detail"]
        current = await client.get(f"/api/scheduler/tasks/{task_id}")
        assert current.json()["schedule_type"] == "every"

    async def test_schedule_type_transition_clears_old_fields(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="good-transition")
        )
        task_id = created.json()["id"]
        target = (datetime.now(_UTC) + timedelta(hours=1)).isoformat()

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"schedule_type": "at", "at_datetime": target},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["schedule_type"] == "at"
        assert body["at_datetime"] is not None
        assert body["every_seconds"] is None
        assert body["cron_expression"] is None

    async def test_rescheduled_one_shot_fires_even_with_prior_run_history(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="rerun-as-at")
        )
        task_id = UUID(created.json()["id"])
        async with _db_module.async_session_factory() as db:
            row = await db.get(ScheduledTask, task_id)
            assert row is not None
            row.run_count = 4
            db.add(row)
            await db.commit()

        target = (datetime.now(_UTC) + timedelta(hours=1)).isoformat()
        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"schedule_type": "at", "at_datetime": target},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_count"] == 4
        assert body["status"] == "pending"
        assert body["next_fire_at"] is not None

        await client.post(f"/api/scheduler/tasks/{task_id}/pause")
        resumed = await client.post(f"/api/scheduler/tasks/{task_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["next_fire_at"] == body["next_fire_at"]

    async def test_partial_update_rejects_field_for_other_schedule_type(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="mixed-shape")
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"cron_expression": "0 9 * * *"},
        )

        assert resp.status_code == 422
        assert "Only every_seconds" in resp.json()["detail"]

    async def test_explicit_null_clears_session_id(self, client):
        sid = str(uuid4())
        created = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="clear-session", session_id=sid),
        )
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}", json={"session_id": None}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["session_id"] is None

    async def test_unknown_id_returns_404(self, client):
        resp = await client.put(
            f"/api/scheduler/tasks/{uuid4()}",
            json={"prompt": "x"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /tasks/{task_id}
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_deletes_task_204(self, client, fresh_scheduler):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="del")
        )
        task_id = created.json()["id"]

        resp = await client.delete(f"/api/scheduler/tasks/{task_id}")
        assert resp.status_code == 204

        # Confirm gone
        get_resp = await client.get(f"/api/scheduler/tasks/{task_id}")
        assert get_resp.status_code == 404

    async def test_unknown_id_returns_404(self, client):
        resp = await client.delete(f"/api/scheduler/tasks/{uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /tasks/{id}/pause + /resume
# ---------------------------------------------------------------------------


class TestPauseResume:
    async def test_pause_sets_paused(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="p")
        )
        task_id = created.json()["id"]
        resp = await client.post(f"/api/scheduler/tasks/{task_id}/pause")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["status"] == "paused"

    async def test_resume_re_enables(self, client):
        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="r")
        )
        task_id = created.json()["id"]
        await client.post(f"/api/scheduler/tasks/{task_id}/pause")
        resp = await client.post(f"/api/scheduler/tasks/{task_id}/resume")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["status"] == "pending"

    async def test_pause_unknown_id_404(self, client):
        resp = await client.post(f"/api/scheduler/tasks/{uuid4()}/pause")
        assert resp.status_code == 404

    async def test_resume_unknown_id_404(self, client):
        resp = await client.post(f"/api/scheduler/tasks/{uuid4()}/resume")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /tasks/{id}/trigger
# ---------------------------------------------------------------------------


class TestTrigger:
    async def test_returns_202_and_dispatched_status(self, client, monkeypatch):
        # Stub _fire_task so the test doesn't actually invoke any team logic.
        async def _noop(task):
            return None

        monkeypatch.setattr(
            "app.scheduler.scheduler.TaskScheduler._fire_task",
            lambda self, task: _noop(task),
        )

        created = await client.post(
            "/api/scheduler/tasks", json=_create_payload(name="trig")
        )
        task_id = created.json()["id"]
        resp = await client.post(f"/api/scheduler/tasks/{task_id}/trigger")
        assert resp.status_code == 202
        assert resp.json() == {"status": "dispatched"}

    async def test_unknown_id_returns_404(self, client):
        resp = await client.post(f"/api/scheduler/tasks/{uuid4()}/trigger")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Schedule type "at" — round-trip
# ---------------------------------------------------------------------------


class TestAtTask:
    async def test_create_at_with_future_datetime(self, client):
        target = (datetime.now(_UTC) + timedelta(hours=1)).isoformat()
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "at_one",
                "mode": "work",
                "schedule_type": "at",
                "at_datetime": target,
                "prompt": "hi",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["schedule_type"] == "at"
        assert body["at_datetime"] is not None
        assert body["next_fire_at"] is not None

    async def test_naive_at_datetime_uses_declared_timezone(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "local_at",
                "mode": "work",
                "schedule_type": "at",
                "at_datetime": "2030-01-02T09:00:00",
                "timezone": "Asia/Ho_Chi_Minh",
                "prompt": "hi",
            },
        )

        assert resp.status_code == 201, resp.text
        # 09:00 in UTC+7 is persisted/returned as 02:00 UTC.
        assert resp.json()["next_fire_at"].startswith("2030-01-02T02:00:00")

    async def test_unknown_timezone_rejected(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "bad_tz",
                "mode": "work",
                "schedule_type": "cron",
                "cron_expression": "0 9 * * *",
                "timezone": "Mars/Olympus_Mons",
                "prompt": "hi",
            },
        )

        assert resp.status_code == 422
        assert "Unknown IANA timezone" in resp.text


# ---------------------------------------------------------------------------
# Schedule type "cron" — round-trip
# ---------------------------------------------------------------------------


class TestCronTask:
    async def test_create_with_valid_cron(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "cron_one",
                "mode": "work",
                "schedule_type": "cron",
                "cron_expression": "0 0 * * *",
                "prompt": "hi",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["schedule_type"] == "cron"
        assert body["cron_expression"] == "0 0 * * *"

    async def test_invalid_cron_rejected_422(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json={
                "name": "bad_cron",
                "mode": "work",
                "schedule_type": "cron",
                "cron_expression": "totally bogus",
                "prompt": "hi",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# session_id compatibility with mode/workspace
# ---------------------------------------------------------------------------


async def _seed_session(
    sid: UUID, *, mode: str = "work", workspace: str | None = None
) -> None:
    async with _db_module.async_session_factory() as db:
        db.add(ChatSession(id=sid, mode=mode, workspace=workspace))
        await db.commit()


class TestSessionCompat:
    async def test_create_rejects_mismatched_session_mode(self, client, tmp_path):
        # Session is 'work'; task asks for 'coding' on a real workspace.
        # Target validation passes, session-compat validation must reject.
        ws = tmp_path / "ws"
        ws.mkdir()
        sid = uuid4()
        await _seed_session(sid, mode="work")
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(
                name="mismatch1",
                mode="coding",
                workspace=str(ws),
                session_id=str(sid),
            ),
        )
        assert resp.status_code == 422
        assert "mode" in resp.json()["detail"]

    async def test_create_rejects_mismatched_workspace(self, client, tmp_path):
        ws_a = tmp_path / "a"
        ws_a.mkdir()
        ws_b = tmp_path / "b"
        ws_b.mkdir()
        sid = uuid4()
        await _seed_session(sid, mode="coding", workspace=str(ws_a.resolve()))

        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(
                name="ws_mismatch",
                mode="coding",
                workspace=str(ws_b),
                session_id=str(sid),
            ),
        )
        assert resp.status_code == 422
        assert "workspace" in resp.json()["detail"]

    async def test_create_accepts_matching_session(self, client, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        ws_resolved = str(ws.resolve())
        sid = uuid4()
        await _seed_session(sid, mode="coding", workspace=ws_resolved)

        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(
                name="ok_match",
                mode="coding",
                workspace=ws_resolved,
                session_id=str(sid),
            ),
        )
        assert resp.status_code == 201, resp.text

    async def test_create_allows_nonexistent_session(self, client):
        # First-fire-creates-it case: explicit UUID not yet in DB → pass.
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="ghost_sid", session_id=str(uuid4())),
        )
        assert resp.status_code == 201

    async def test_create_allows_auto_session_id(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="auto_sid", session_id="auto"),
        )
        assert resp.status_code == 201

    async def test_create_rejects_garbage_session_id(self, client):
        resp = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="bad_sid", session_id="not-a-uuid"),
        )
        assert resp.status_code == 422

    async def test_update_mode_conflicts_with_existing_session(self, client, tmp_path):
        # Create a task bound to a 'work' session; switching it to 'coding'
        # must now fail because the session row is 'work'.
        sid = uuid4()
        await _seed_session(sid, mode="work")
        ws = tmp_path / "ws"
        ws.mkdir()

        created = await client.post(
            "/api/scheduler/tasks",
            json=_create_payload(name="upd_conflict", session_id=str(sid)),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]

        resp = await client.put(
            f"/api/scheduler/tasks/{task_id}",
            json={"mode": "coding", "workspace": str(ws)},
        )
        assert resp.status_code == 422
        assert "mode" in resp.json()["detail"]
