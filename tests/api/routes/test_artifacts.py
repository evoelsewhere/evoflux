from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import artifacts as artifacts_route


class FakeArtifactService:
    def catalog(self, artifact_format=None):
        return {"format": artifact_format, "schema_version": 1}

    async def list_jobs(self, *, session_id=None, status=None, limit=100):
        return [
            {
                "job_id": str(uuid4()),
                "session_id": str(session_id) if session_id else None,
                "status": status or "review_ready",
                "limit": limit,
            }
        ]

    async def status(self, job_id):
        if str(job_id).endswith("0000"):
            raise KeyError("missing")
        return {"job_id": str(job_id), "status": "review_ready"}


@pytest.fixture
async def client(monkeypatch):
    service = FakeArtifactService()
    monkeypatch.setattr(artifacts_route, "get_artifact_service", lambda: service)
    app = FastAPI()
    app.include_router(artifacts_route.router, prefix="/api/artifacts")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_artifact_catalog_route(client: AsyncClient) -> None:
    response = await client.get("/api/artifacts/catalog", params={"format": "pdf"})

    assert response.status_code == 200
    assert response.json() == {"format": "pdf", "schema_version": 1}


@pytest.mark.asyncio
async def test_artifact_job_list_route(client: AsyncClient) -> None:
    session_id = uuid4()
    response = await client.get(
        "/api/artifacts/jobs",
        params={"session_id": str(session_id), "status": "review_ready", "limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["jobs"][0]["session_id"] == str(session_id)
    assert response.json()["jobs"][0]["limit"] == 10
