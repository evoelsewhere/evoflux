from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.git_ai import router as git_ai_router
from app.core.db import get_session


@pytest.mark.asyncio
async def test_git_ai_route_uses_session_provider(tmp_path, monkeypatch):
    session_id = uuid4()
    session = SimpleNamespace(
        mode="coding",
        workspace=str(tmp_path),
        model=None,
        thinking_level=None,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=session))

    async def db_dependency():
        yield db

    provider = SimpleNamespace(provider_name="test")
    team = SimpleNamespace(
        lead=SimpleNamespace(agent=SimpleNamespace(llm_provider=provider)),
        _provider_factory=None,
    )
    monkeypatch.setattr(
        "app.api.routes.team.git_ai.team_manager.find_team_for_session",
        lambda _id: team,
    )
    action = AsyncMock(
        return_value={
            "kind": "text",
            "summary": "Generated",
            "message": "fix: message",
            "title": None,
            "body": None,
            "findings": [],
            "change_set": None,
            "evidence_sha256": "a" * 64,
        }
    )
    monkeypatch.setattr("app.api.routes.team.git_ai.run_git_ai_action", action)
    app = FastAPI()
    app.include_router(git_ai_router, prefix="/api/team")
    app.dependency_overrides[get_session] = db_dependency

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        response = await client.post(
            "/api/team/workspace/git/ai",
            params={"workspace": str(tmp_path)},
            json={
                "session_id": str(session_id),
                "action": "generate_commit_message",
            },
        )

    assert response.status_code == 200
    assert response.json()["message"] == "fix: message"
    action.assert_awaited_once_with(
        workspace=tmp_path.resolve(),
        provider=provider,
        action="generate_commit_message",
        session_id=str(session_id),
        reference=None,
        remote_context=None,
    )
