"""Process panel API contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.team import processes as routes
from app.services.process_manager import ActiveProcess


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/team")
    return TestClient(app)


def test_list_processes_includes_session_title(monkeypatch):
    monkeypatch.setattr(
        routes,
        "list_active_processes",
        lambda: [
            ActiveProcess(
                id="proc_1234567890",
                kind="command",
                label="bun run dev",
                command="bun run dev",
                session_id="session-1",
                pid=123,
                cwd="/repo",
                elapsed_seconds=4.5,
            )
        ],
    )
    titles = AsyncMock(return_value={"session-1": "Frontend work"})
    monkeypatch.setattr(routes, "_session_titles", titles)

    response = _client().get("/api/team/processes")

    assert response.status_code == 200
    process = response.json()["processes"][0]
    assert process["session_title"] == "Frontend work"
    assert process["kind"] == "command"
    assert process["pid"] == 123


def test_terminate_process_returns_not_found_or_no_content(monkeypatch):
    stop = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(routes, "terminate_active_process", stop)
    client = _client()

    assert client.delete("/api/team/processes/proc_1234567890").status_code == 204
    missing = client.delete("/api/team/processes/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Process not found"
