from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.language_servers import router
from app.services import language_server_service


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
async def test_install_route_starts_a_job_and_returns_immediately(monkeypatch):
    """The route reports that work began, not that it finished.

    Installs run for minutes; holding the request open for one meant the only
    progress signal belonged to that request and vanished with it.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_install(_language_id: str):
        started.set()
        await release.wait()

    monkeypatch.setattr(
        "app.services.language_server_service.install_language_server", slow_install
    )
    monkeypatch.setattr(
        "app.services.language_server_service.shutil.which",
        lambda _name: "/usr/bin/npm",
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
        assert response.json()["phase"] == "running"
        assert response.json()["language_id"] == "typescript"

        await asyncio.wait_for(started.wait(), timeout=2)
        # A second request while one is running joins it rather than starting
        # a competing installer.
        again = await client.post(
            "/api/team/workspace/language-servers/typescript/install"
        )
        assert again.json()["started_at"] == response.json()["started_at"]

    release.set()
    task = language_server_service._install_tasks.pop("typescript", None)
    if task is not None:
        await task
    language_server_service._install_jobs.pop("typescript", None)


@pytest.mark.asyncio
async def test_install_route_refuses_when_the_installer_is_missing(monkeypatch):
    monkeypatch.setattr(
        "app.services.language_server_service.shutil.which", lambda _name: None
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/team/workspace/language-servers/typescript/install"
        )

    assert response.status_code == 409
    # The reason has to name the missing tool; "install failed" taught nobody
    # anything.
    assert "npm" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_install_route_rejects_an_unknown_language():
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/team/workspace/language-servers/cobol/install"
        )

    assert response.status_code == 409
    assert "cobol" in response.json()["detail"].lower()
