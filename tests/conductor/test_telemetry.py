from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.conductor.client import ConductorClient
from app.conductor.telemetry import flush_usage, record_skill_usage
from app.core.config import settings


class MemoryCredentialStore:
    def __init__(self, value: str) -> None:
        self.value = value

    def load(self) -> str | None:
        return self.value

    def save(self, credential: str) -> None:
        self.value = credential

    def delete(self) -> None:
        self.value = ""


@pytest.mark.asyncio
async def test_managed_skill_usage_is_durable_and_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = tmp_path / "skills"
    state = tmp_path / "state"
    managed = skills / "research"
    managed.mkdir(parents=True)
    (managed / ".evoflux.json").write_text(
        json.dumps(
            {
                "managed_by": "conductor",
                "resource_id": "11111111-1111-1111-1111-111111111111",
                "resource_version": "1.2.3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state))

    record_skill_usage("local-only", source="manual", mode="work")
    record_skill_usage("research", source="implicit", mode="coding", duration_ms=12)

    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/usage/resources"
        assert request.headers["authorization"] == "Bearer evc_secret"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"accepted": 1, "duplicates": 0, "rejected": 0})

    client = ConductorClient(
        "https://conductor.example",
        MemoryCredentialStore("evc_secret"),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await flush_usage(client) == 1
    finally:
        await client.close()

    events = captured["events"]
    assert isinstance(events, list) and len(events) == 1
    assert events[0]["resource_version"] == "1.2.3"
    assert events[0]["invocation_source"] == "implicit"
    assert "prompt" not in events[0]
    assert not (state / "conductor" / "usage-queue.jsonl").read_text()
