"""HTTP contract tests for local skill demonstration traces."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.skill_recordings import router as skill_recordings_router
from app.core.config import settings
from app.services import skill_distillation_service as distiller
from app.services.skill_recording_service import (
    append_events,
    stop_session,
)


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(skill_recordings_router, prefix="/api/skill-recordings")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


def focus_event(sequence: int = 1) -> dict:
    return {
        "sequence": sequence,
        "elapsed_ms": 50,
        "kind": "focus",
        "target": {
            "automation_id": "search",
            "control_type": "edit",
            "name": "private",
        },
        "value_state": "not_captured",
        "value": None,
        "screenshot": None,
    }


def png_fixture() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


@pytest.mark.asyncio
async def test_session_lifecycle_persists_reviewable_events_and_checkpoint(client):
    created = await client.post("/api/skill-recordings")
    assert created.status_code == 201
    recording_id = created.json()["id"]

    appended = await client.post(
        f"/api/skill-recordings/{recording_id}/events",
        json={"events": [focus_event()]},
    )
    assert appended.status_code == 200
    assert appended.json()["first_sequence"] == 1

    png = png_fixture()
    checkpoint = focus_event(2)
    checkpoint.update(
        kind="screenshot",
        target=None,
        screenshot=base64.b64encode(png).decode("ascii"),
    )
    await client.post(
        f"/api/skill-recordings/{recording_id}/events", json={"events": [checkpoint]}
    )
    image = await client.get(f"/api/skill-recordings/{recording_id}/screenshots/2")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == png

    paused = await client.post(f"/api/skill-recordings/{recording_id}/pause")
    assert paused.status_code == 200
    rejected = await client.post(
        f"/api/skill-recordings/{recording_id}/events",
        json={"events": [focus_event(3)]},
    )
    assert rejected.status_code == 409
    assert (
        await client.post(f"/api/skill-recordings/{recording_id}/resume")
    ).status_code == 200
    assert (
        await client.post(f"/api/skill-recordings/{recording_id}/stop")
    ).status_code == 200

    stored = await client.get(f"/api/skill-recordings/{recording_id}")
    assert stored.status_code == 200
    assert stored.json()["status"] == "stopped"
    assert stored.json()["events"][0]["target"]["name"] is None
    assert stored.json()["events"][1]["screenshot"] == "screenshots/000002.png"
    assert base64.b64encode(png).decode("ascii") not in stored.text

    deleted = await client.delete(f"/api/skill-recordings/{recording_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"id": recording_id, "deleted": True}


@pytest.mark.asyncio
async def test_malformed_or_sensitive_value_payload_is_rejected(client):
    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    invalid = focus_event()
    invalid.update(value="secret", value_state="omitted_secure")

    response = await client.post(
        f"/api/skill-recordings/{recording_id}/events", json={"events": [invalid]}
    )
    assert response.status_code == 422
    assert (await client.get(f"/api/skill-recordings/{recording_id}")).json()[
        "events"
    ] == []


@pytest.mark.asyncio
async def test_unknown_session_and_path_traversal_are_not_found(client):
    for recording_id in ("../outside", "not-a-uuid"):
        response = await client.get(f"/api/skill-recordings/{recording_id}")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_stopped_video_upload_and_read_are_file_backed_and_no_store(client):
    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    stop_session(recording_id)

    uploaded = await client.put(
        f"/api/skill-recordings/{recording_id}/video",
        content=b"synthetic-webm-data",
        headers={"content-type": "video/webm"},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["artifact_id"] == "video"
    assert uploaded.json()["byte_length"] == len(b"synthetic-webm-data")
    assert uploaded.json()["expires_at"]

    video = await client.get(f"/api/skill-recordings/{recording_id}/video")
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/webm"
    assert video.headers["cache-control"] == "no-store"
    assert video.content == b"synthetic-webm-data"


@pytest.mark.asyncio
async def test_video_read_supports_single_byte_ranges_for_player_seeking(client):
    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    stop_session(recording_id)
    await client.put(
        f"/api/skill-recordings/{recording_id}/video",
        content=b"synthetic-webm-data",
        headers={"content-type": "video/webm"},
    )

    video = await client.get(
        f"/api/skill-recordings/{recording_id}/video",
        headers={"range": "bytes=3-8"},
    )

    assert video.status_code == 206
    assert video.headers["content-range"] == "bytes 3-8/19"
    assert video.headers["accept-ranges"] == "bytes"
    assert video.headers["content-length"] == "6"
    assert video.content == b"thetic"


@pytest.mark.asyncio
async def test_video_upload_rejects_wrong_media_type(client):
    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    stop_session(recording_id)

    uploaded = await client.put(
        f"/api/skill-recordings/{recording_id}/video",
        content=b"not-a-video",
        headers={"content-type": "application/octet-stream"},
    )

    assert uploaded.status_code == 415


@pytest.mark.asyncio
async def test_draft_requires_explicit_consent_and_stopped_recording(client):
    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    body = {
        "selected_event_ids": [1],
        "redactions": {},
        "goal": "Export invoices",
        "model": "test:model",
    }
    preview = await client.post(
        f"/api/skill-recordings/{recording_id}/preview", json=body
    )
    assert preview.status_code == 422

    draft_body = {
        **body,
        "confirm_processing": True,
        "preview_sha256": "0" * 64,
        "model": "test:model",
    }
    active = await client.post(
        f"/api/skill-recordings/{recording_id}/draft", json=draft_body
    )
    assert active.status_code == 422

    append_events(recording_id, [focus_event()])
    stop_session(recording_id)
    preview = await client.post(
        f"/api/skill-recordings/{recording_id}/preview", json=body
    )
    draft_body["preview_sha256"] = preview.json()["sha256"]
    draft_body["confirm_processing"] = False
    no_consent = await client.post(
        f"/api/skill-recordings/{recording_id}/draft", json=draft_body
    )
    assert no_consent.status_code == 422


@pytest.mark.asyncio
async def test_draft_route_uses_selected_provider_and_returns_draft_without_saving(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeProvider:
        async def chat(self, messages, tools=None, **kwargs):
            assert tools is None
            assert "untrusted" in messages[0].content.lower()
            return type(
                "ProviderResponse",
                (),
                {
                    "tool_calls": None,
                    "content": (
                        '{"name":"invoice-export",'
                        '"description":"Export invoices with the selected filters.",'
                        '"content":"---\\nname: invoice-export\\n'
                        "description: Export invoices with the selected filters.\\n"
                        '---\\n\\n1. Choose filters.\\n2. Export invoices.\\n",'
                        '"files":[],"evidence_summary":["Exported invoices"]}'
                    ),
                },
            )()

    created = await client.post("/api/skill-recordings")
    recording_id = created.json()["id"]
    append_events(recording_id, [focus_event()])
    stop_session(recording_id)
    preview = await client.post(
        f"/api/skill-recordings/{recording_id}/preview",
        json={
            "selected_event_ids": [1],
            "redactions": {},
            "goal": "Export invoices",
            "model": "test:model",
        },
    )
    monkeypatch.setattr(distiller, "build_provider", lambda model: FakeProvider())
    skill_root = tmp_path / "skills"
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skill_root))

    response = await client.post(
        f"/api/skill-recordings/{recording_id}/draft",
        json={
            "confirm_processing": True,
            "selected_event_ids": [1],
            "redactions": {},
            "preview_sha256": preview.json()["sha256"],
            "model": "test:model",
            "goal": "Export invoices",
        },
    )

    assert response.status_code == 200
    assert response.json()["draft"]["name"] == "invoice-export"
    assert not skill_root.exists()
