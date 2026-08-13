from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.builtin_plugins.documents import routes as document_routes
from app.api.routes import artifacts as artifacts_route


class FakeArtifactService:
    def catalog(self, artifact_format=None):
        if artifact_format == "unknown":
            raise ValueError("unsupported artifact format: unknown")
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


class FakeRenderBroker:
    def __init__(self) -> None:
        self.heartbeats: list[str] = []
        self.renderer_heartbeats: list[str] = []
        self.completed: list[tuple[str, object, dict]] = []
        self.global_completed: list[tuple[object, dict]] = []

    async def heartbeat(self, session_id: str) -> None:
        self.heartbeats.append(session_id)

    async def heartbeat_renderer(self, renderer_id: str) -> None:
        self.renderer_heartbeats.append(renderer_id)

    async def claim(self, session_id: str):
        return {"request_id": str(uuid4()), "slide_id": "opening"}

    async def claim_next(self, renderer_id: str):
        return {
            "request_id": str(uuid4()),
            "session_id": str(uuid4()),
            "renderer_id": renderer_id,
            "slide_id": "background",
        }

    async def complete(self, session_id: str, request_id, result: dict) -> bool:
        self.completed.append((session_id, request_id, result))
        return True

    async def fail(self, session_id: str, request_id, message: str) -> bool:
        return False

    async def complete_claim(self, request_id, result: dict) -> bool:
        self.global_completed.append((request_id, result))
        return True

    async def fail_claim(self, request_id, message: str) -> bool:
        return False


@pytest.fixture
async def client(monkeypatch):
    service = FakeArtifactService()
    monkeypatch.setattr(artifacts_route, "get_artifact_service", lambda: service)
    app = FastAPI()
    app.include_router(artifacts_route.router, prefix="/api/artifacts")
    app.include_router(document_routes.router, prefix="/api/artifacts")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_artifact_catalog_route(client: AsyncClient) -> None:
    response = await client.get("/api/artifacts/catalog", params={"format": "pdf"})

    assert response.status_code == 200
    assert response.json() == {"format": "pdf", "schema_version": 1}


@pytest.mark.asyncio
async def test_artifact_catalog_rejects_unknown_format(client: AsyncClient) -> None:
    response = await client.get("/api/artifacts/catalog", params={"format": "unknown"})

    assert response.status_code == 404
    assert response.json()["detail"] == "unsupported artifact format: unknown"


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


@pytest.mark.asyncio
async def test_html_slide_renderer_bridge_routes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeRenderBroker()
    monkeypatch.setattr(document_routes, "get_html_slide_render_broker", lambda: broker)
    session_id = uuid4()

    heartbeat = await client.post(f"/api/artifacts/renderers/{session_id}/heartbeat")
    claimed = await client.get(f"/api/artifacts/renderers/{session_id}/next")
    request_id = uuid4()
    completed = await client.post(
        f"/api/artifacts/renderers/{session_id}/requests/{request_id}/complete",
        json={
            "preview_png_base64": "cHJldmlldw==",
            "shell_png_base64": "c2hlbGw=",
            "editable_elements": [],
            "text_coverage": {
                "visible_blocks": 0,
                "visible_characters": 0,
                "native_blocks": 0,
                "native_characters": 0,
                "flattened": [],
            },
            "issues": [],
        },
    )
    missing = await client.post(
        f"/api/artifacts/renderers/{session_id}/requests/{request_id}/fail",
        json={"message": "failed"},
    )

    assert heartbeat.status_code == 204
    assert broker.heartbeats == [str(session_id)]
    assert claimed.status_code == 200
    assert claimed.json()["slide_id"] == "opening"
    assert completed.status_code == 204
    assert broker.completed[0][0] == str(session_id)
    assert broker.completed[0][2]["text_coverage"]["visible_blocks"] == 0
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_global_html_slide_renderer_bridge_routes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeRenderBroker()
    monkeypatch.setattr(document_routes, "get_html_slide_render_broker", lambda: broker)
    renderer_id = uuid4()
    request_id = uuid4()

    heartbeat = await client.post(
        f"/api/artifacts/renderers/global/{renderer_id}/heartbeat"
    )
    claimed = await client.get(f"/api/artifacts/renderers/global/{renderer_id}/next")
    completed = await client.post(
        f"/api/artifacts/renderers/global/{renderer_id}/requests/{request_id}/complete",
        json={
            "preview_png_base64": "cHJldmlldw==",
            "shell_png_base64": "c2hlbGw=",
            "editable_elements": [],
            "text_coverage": {
                "visible_blocks": 0,
                "visible_characters": 0,
                "native_blocks": 0,
                "native_characters": 0,
                "flattened": [],
            },
            "issues": [],
        },
    )

    assert heartbeat.status_code == 204
    assert broker.renderer_heartbeats == [str(renderer_id)]
    assert claimed.status_code == 200
    assert claimed.json()["slide_id"] == "background"
    assert completed.status_code == 204
    assert broker.global_completed[0][0] == request_id


@pytest.mark.asyncio
async def test_html_slide_renderer_bridge_requires_text_coverage(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeRenderBroker()
    monkeypatch.setattr(document_routes, "get_html_slide_render_broker", lambda: broker)

    response = await client.post(
        f"/api/artifacts/renderers/{uuid4()}/requests/{uuid4()}/complete",
        json={
            "preview_png_base64": "cHJldmlldw==",
            "shell_png_base64": "c2hlbGw=",
            "editable_elements": [],
            "issues": [],
        },
    )

    assert response.status_code == 422
    assert broker.completed == []


@pytest.mark.asyncio
async def test_html_slide_renderer_bridge_rejects_malformed_native_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeRenderBroker()
    monkeypatch.setattr(document_routes, "get_html_slide_render_broker", lambda: broker)

    response = await client.post(
        f"/api/artifacts/renderers/{uuid4()}/requests/{uuid4()}/complete",
        json={
            "preview_png_base64": "cHJldmlldw==",
            "shell_png_base64": "c2hlbGw=",
            "editable_elements": [
                {
                    "kind": "text",
                    "name": "Broken title",
                    "x": 0,
                    "y": 0,
                    "width": -1,
                    "height": 40,
                    "paragraphs": [{"runs": [{"text": "Rejected"}]}],
                }
            ],
            "text_coverage": {
                "visible_blocks": 1,
                "visible_characters": 8,
                "native_blocks": 1,
                "native_characters": 8,
                "flattened": [],
            },
            "issues": [],
        },
    )

    assert response.status_code == 422
    assert broker.completed == []


@pytest.mark.asyncio
async def test_html_slide_renderer_bridge_rejects_unknown_manifest_fields(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeRenderBroker()
    monkeypatch.setattr(document_routes, "get_html_slide_render_broker", lambda: broker)

    response = await client.post(
        f"/api/artifacts/renderers/{uuid4()}/requests/{uuid4()}/complete",
        json={
            "preview_png_base64": "cHJldmlldw==",
            "shell_png_base64": "c2hlbGw=",
            "editable_elements": [],
            "text_coverage": {
                "visible_blocks": 0,
                "visible_characters": 0,
                "native_blocks": 0,
                "native_characters": 0,
                "flattened": [],
                "typo_field": 1,
            },
            "issues": [],
        },
    )

    assert response.status_code == 422
    assert broker.completed == []
