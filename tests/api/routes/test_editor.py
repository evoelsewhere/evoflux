from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.editor import router as editor_router
from app.core.db import get_session
from app.services.change_set_service import clear_change_sets


@pytest.fixture
async def client(tmp_path, monkeypatch):
    session_id = uuid4()
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=SimpleNamespace(
                content=json.dumps(
                    {
                        "kind": "changes",
                        "summary": "Update value",
                        "files": [
                            {
                                "path": "main.py",
                                "proposed_content": "value = 2\n",
                            }
                        ],
                    }
                )
            )
        ),
    )
    session = SimpleNamespace(
        id=session_id,
        mode="coding",
        workspace=str(tmp_path),
        model=None,
        thinking_level=None,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=session))

    async def db_dependency():
        yield db

    team = SimpleNamespace(
        lead=SimpleNamespace(agent=SimpleNamespace(llm_provider=provider)),
        _provider_factory=None,
    )
    monkeypatch.setattr(
        "app.api.routes.team.editor.team_manager.find_team_for_session",
        lambda _id: team,
    )
    app = FastAPI()
    app.include_router(editor_router, prefix="/api/team")
    app.dependency_overrides[get_session] = db_dependency
    transport = ASGITransport(app=app)
    clear_change_sets()
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        yield http, tmp_path, str(session_id), provider
    clear_change_sets()


@pytest.mark.asyncio
async def test_context_preview_is_inspectable_and_explicit(client):
    http, workspace, session_id, _provider = client
    response = await http.post(
        "/api/team/workspace/editor/context",
        params={"workspace": str(workspace)},
        json={
            "session_id": session_id,
            "active_file": "main.py",
            "content": "value = 1\n",
            "document_version": 3,
            "selection": {
                "text": "value",
                "start_line": 1,
                "start_column": 1,
                "end_line": 1,
                "end_column": 6,
            },
        },
    )

    assert response.status_code == 200
    context = response.json()["context"]
    assert context["active_file"] == "main.py"
    assert context["document_version"] == 3
    assert context["selection"]["text"] == "value"
    assert context["provenance"][0]["source"] == "editor-buffer"


@pytest.mark.asyncio
async def test_explicit_action_returns_guarded_change_set(client):
    http, workspace, session_id, provider = client
    response = await http.post(
        "/api/team/workspace/editor/action",
        params={"workspace": str(workspace)},
        json={
            "session_id": session_id,
            "action": "simplify_code",
            "active_file": "main.py",
            "content": "value = 1\n",
            "document_version": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "changes"
    assert body["change_set"]["files"][0]["path"] == "main.py"
    provider.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_dirty_buffer_must_be_saved_before_ai_change(client):
    http, workspace, session_id, provider = client
    response = await http.post(
        "/api/team/workspace/editor/action",
        params={"workspace": str(workspace)},
        json={
            "session_id": session_id,
            "action": "refactor_selection",
            "active_file": "main.py",
            "content": "value = 99\n",
            "selection": {
                "text": "value = 99",
                "start_line": 1,
                "start_column": 1,
                "end_line": 1,
                "end_column": 11,
            },
        },
    )

    assert response.status_code == 409
    assert "Save the active editor buffer" in response.json()["detail"]
    provider.chat.assert_not_awaited()
