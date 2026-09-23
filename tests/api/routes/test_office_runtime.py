from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team import office_runtime as routes
from app.services.office_runtime import InstallJob, RuntimeInstallError, RuntimeStatus


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/team")
    return app


def _status(job: InstallJob | None = None) -> RuntimeStatus:
    return RuntimeStatus(
        available=True,
        platform="darwin-arm64",
        version="26.8.0",
        download_bytes=150_000_000,
        install_bytes=600_000_000,
        installed_version=None,
        job=job,
    )


@pytest.mark.asyncio
async def test_status_route_reports_availability(monkeypatch):
    monkeypatch.setattr(routes, "runtime_status", lambda: _status())

    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/team/office-runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["platform"] == "darwin-arm64"
    assert body["download_bytes"] == 150_000_000
    assert body["job"] is None


@pytest.mark.asyncio
async def test_install_route_starts_download_and_reports_progress(monkeypatch):
    job = InstallJob(
        phase="downloading",
        version="26.8.0",
        bytes_done=0,
        bytes_total=150_000_000,
        started_at="2026-09-23T00:00:00+00:00",
    )
    started: list[bool] = []
    monkeypatch.setattr(
        routes, "start_runtime_install", lambda: started.append(True) or job
    )
    monkeypatch.setattr(routes, "runtime_status", lambda: _status(job))

    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/team/office-runtime/install")

    assert response.status_code == 200
    assert started == [True]
    assert response.json()["job"]["phase"] == "downloading"


@pytest.mark.asyncio
async def test_install_route_conflicts_when_no_bundle_is_published(monkeypatch):
    def refuse() -> InstallJob:
        raise RuntimeInstallError("No verified LibreOffice runtime is published.")

    monkeypatch.setattr(routes, "start_runtime_install", refuse)

    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/team/office-runtime/install")

    assert response.status_code == 409
    assert "No verified" in response.json()["detail"]
