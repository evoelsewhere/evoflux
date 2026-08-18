from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.search_everywhere import router
from app.services.search_everywhere_service import SearchEverywhereItem


@pytest.mark.asyncio
async def test_search_everywhere_route_returns_typed_items(tmp_path, monkeypatch):
    search = AsyncMock(
        return_value=[
            SearchEverywhereItem(
                id="file:app.py",
                kind="file",
                label="app.py",
                description="Repository file",
                path="app.py",
                line=1,
            )
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.team.search_everywhere.search_everywhere", search
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        response = await client.post(
            "/api/team/workspace/search-everywhere",
            params={"workspace": str(tmp_path)},
            json={"query": "app", "limit": 25},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["kind"] == "file"
    search.assert_awaited_once_with(tmp_path.resolve(), "app", limit=25)
