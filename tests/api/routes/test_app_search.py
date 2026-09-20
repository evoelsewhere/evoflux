from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_read_session
from app.api.routes.team.app_search import router
from app.services.app_search_service import AppSearchItem


def _app(monkeypatch, items: list[AppSearchItem]) -> tuple[FastAPI, AsyncMock]:
    search = AsyncMock(return_value=items)
    monkeypatch.setattr("app.api.routes.team.app_search.search_app", search)
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    app.dependency_overrides[get_read_session] = lambda: None
    return app, search


@pytest.mark.asyncio
async def test_route_returns_typed_items(monkeypatch):
    app, search = _app(
        monkeypatch,
        [
            AppSearchItem(
                id="session:1",
                kind="session",
                label="Refactor the billing importer",
                description="work · atlas-api",
                session_id="1",
            )
        ],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        response = await client.post(
            "/api/team/search-app", json={"query": "billing", "limit": 25}
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["kind"] == "session"
    assert item["session_id"] == "1"
    search.assert_awaited_once_with(None, "billing", limit=25)


@pytest.mark.asyncio
async def test_route_rejects_an_empty_query(monkeypatch):
    app, search = _app(monkeypatch, [])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        response = await client.post("/api/team/search-app", json={"query": ""})

    assert response.status_code == 422
    search.assert_not_awaited()
