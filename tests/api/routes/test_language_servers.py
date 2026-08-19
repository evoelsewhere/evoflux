from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.language_servers import router
from app.services.language_server_service import language_server_overview


@pytest.mark.asyncio
async def test_language_server_status_route_reports_workspace_detection(
    tmp_path, monkeypatch
):
    (tmp_path / "app.ts").write_text("export const value = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.language_server_service.shutil.which", lambda _name: None
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/team")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/team/workspace/language-servers/status",
            json={"workspaces": [str(tmp_path)]},
        )

    assert response.status_code == 200
    items = {item["language_id"]: item for item in response.json()["servers"]}
    assert items["typescript"]["detected"] is True
    assert items["typescript"]["file_count"] == 1


@pytest.mark.asyncio
async def test_install_route_returns_updated_status(tmp_path, monkeypatch):
    overview = language_server_overview()
    typescript = next(
        item for item in overview.servers if item.language_id == "typescript"
    )
    installed = replace(
        typescript,
        state="ready",
        source="managed",
        command=str(tmp_path / "typescript-language-server"),
        installed_version=typescript.expected_version,
    )

    async def fake_install(_language_id: str):
        return installed

    monkeypatch.setattr(
        "app.api.routes.team.language_servers.install_language_server", fake_install
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/team/workspace/language-servers/typescript/install"
        )

    assert response.status_code == 200
    assert response.json()["source"] == "managed"
