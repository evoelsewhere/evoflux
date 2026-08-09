from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import plugins as plugin_routes
from app.core.config import settings
from app.plugin_platform.runtime import plugin_mcp_runtime


@pytest.mark.asyncio
async def test_plugin_api_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    refresh_mock = AsyncMock()
    invalidate_mock = Mock()
    monkeypatch.setattr(plugin_mcp_runtime, "refresh", refresh_mock)
    monkeypatch.setattr(
        plugin_routes.team_manager,
        "invalidate_skill_cache",
        invalidate_mock,
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    plugin_root = tmp_path / "authoring" / "api-plugin"
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/plugins/create",
            json={
                "destination": str(plugin_root),
                "name": "api-plugin",
                "description": "API lifecycle",
                "skill_name": "api-skill",
            },
        )
        assert created.status_code == 201

        inspected = await client.get(
            "/api/plugins/inspect",
            params={"path": str(plugin_root)},
        )
        assert inspected.status_code == 200
        assert inspected.json()["manifest"]["$schema"].endswith("/plugin.schema.json")

        imported = await client.post(
            "/api/plugins/install",
            json={"path": str(plugin_root), "mode": "link", "enabled": True},
        )
        assert imported.status_code == 201
        installation_id = imported.json()["installation"]["id"]

        listed = await client.get("/api/plugins")
        assert listed.status_code == 200
        assert listed.json()["plugins"][0]["installation"]["name"] == "api-plugin"

        disabled = await client.patch(
            f"/api/plugins/{installation_id}/enabled",
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["installation"]["enabled"] is False

        removed = await client.delete(f"/api/plugins/{installation_id}")
        assert removed.status_code == 200
        assert (await client.get("/api/plugins")).json()["plugins"] == []

    assert refresh_mock.await_count == 3
    assert invalidate_mock.call_count == 3
