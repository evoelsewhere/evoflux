from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.team.motion_review import router as motion_review_router
from app.core.db import get_read_session
from app.agent.schemas.events import MotionProgressEvent
from app.services.motion_review_service import (
    clear_motion_review_requests,
    wait_for_motion_samples,
)


def jpeg() -> bytes:
    sof = (
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8" + sof + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x00\xff\xd9"


@pytest.fixture
async def motion_review_client(monkeypatch):
    session_id = uuid4()
    session = SimpleNamespace(id=session_id, parent_session_id=None)

    async def get(_model, _id):
        return session

    db = SimpleNamespace(get=get)

    async def db_dependency():
        yield db

    app = FastAPI()
    app.include_router(motion_review_router, prefix="/api/team")
    app.dependency_overrides[get_read_session] = db_dependency
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, session_id, session


@pytest.fixture(autouse=True)
async def cleanup_requests():
    await clear_motion_review_requests()
    yield
    await clear_motion_review_requests()


@pytest.mark.asyncio
async def test_authorized_route_resolves_only_bounded_matching_sample(
    motion_review_client,
):
    client, session_id, _session = motion_review_client
    job_id = "motion-" + "a" * 32
    event = MotionProgressEvent(
        agent="lead",
        job_id=job_id,
        sequence=2,
        artifact_id="rainfall-story",
        artifact_revision=3,
        status="running",
        phase="reviewing",
        sample_request_id="request-1",
        selected_samples=[
            {
                "sample_id": "intake-hit",
                "beat_id": "intake",
                "frame_index": 42,
                "timestamp_ms": 1400,
                "role": "impact",
            }
        ],
    )
    waiting = asyncio.create_task(
        wait_for_motion_samples(str(session_id), event, timeout_seconds=1)
    )
    await asyncio.sleep(0)
    body = {
        "sample_request_id": "request-1",
        "artifact_id": "rainfall-story",
        "artifact_revision": 3,
        "samples": [
            {
                "sample_id": "intake-hit",
                "frame_index": 42,
                "timestamp_ms": 1400,
                "mime_type": "image/jpeg",
                "image_base64": base64.b64encode(jpeg()).decode(),
            }
        ],
    }
    response = await client.post(
        f"/api/team/{session_id}/motion-review/{job_id}",
        json=body,
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "sample_count": 1}
    assert (await waiting)[0].sample_id == "intake-hit"


@pytest.mark.asyncio
async def test_route_rejects_unknown_or_child_session(motion_review_client):
    client, session_id, session = motion_review_client
    session.parent_session_id = uuid4()
    response = await client.post(
        f"/api/team/{session_id}/motion-review/{'motion-' + 'a' * 32}",
        json={},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_enforces_request_body_cap_before_json_validation(
    motion_review_client,
):
    client, session_id, _session = motion_review_client
    response = await client.post(
        f"/api/team/{session_id}/motion-review/{'motion-' + 'a' * 32}",
        content=b"{" + b" " * 3_500_000 + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
