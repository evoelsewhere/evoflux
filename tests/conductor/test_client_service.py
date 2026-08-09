from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.conductor.client import ConductorClient, CredentialStore, redact_telemetry
from app.conductor.models import Manifest
from app.conductor.service import ConductorService
from app.core.config import settings
from app.core.runtime_settings import ConductorSettings


def test_telemetry_redaction_excludes_sensitive_content() -> None:
    cleaned = redact_telemetry(
        {
            "event": "agent.completed",
            "tokens_in": 10,
            "prompt": "private prompt",
            "tool_arguments": {"path": "/secret"},
            "result": "private result",
            "access_token": "secret",
            "unexpected": "value",
        }
    )

    assert cleaned == {"event": "agent.completed", "tokens_in": 10}


@pytest.mark.asyncio
async def test_manifest_etag_and_machine_auth(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credential.json")
    store.save("machine-1", "machine-secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer machine-secret"
        assert request.headers["if-none-match"] == '"m1"'
        return httpx.Response(304, headers={"etag": '"m1"'})

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        manifest, etag = await client.fetch_manifest('"m1"')
    finally:
        await client.close()

    assert manifest is None
    assert etag == '"m1"'
    assert (tmp_path / "credential.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_offline_sync_uses_last_known_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state_dir))
    monkeypatch.setattr(settings, "AGENTS_DIR", str(config_dir / "agents"))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(config_dir / "skills"))
    (config_dir / "agents").mkdir(parents=True)
    (config_dir / "skills").mkdir(parents=True)
    (state_dir / "conductor").mkdir(parents=True)
    credential = state_dir / "conductor" / "credentials.json"
    CredentialStore(credential).save("machine-1", "credential")

    service = ConductorService()
    manifest = Manifest.model_validate(
        {"schema_version": 1, "revision": "cached", "resources": []}
    )
    service._reconciler.save_last_good_manifest(manifest)
    config = ConductorSettings(
        enabled=True,
        url="https://offline.example",
        enforcement_mode="report",
    )
    monkeypatch.setattr(service, "_config", lambda: config)

    class OfflineClient:
        base_url = config.url
        credentials = CredentialStore(credential)

        async def fetch_manifest(self, _etag):
            request = httpx.Request("GET", f"{config.url}/api/v2/manifest")
            raise httpx.ConnectError("offline", request=request)

    service._client = OfflineClient()  # type: ignore[assignment]

    status = await service.sync_now()

    assert status.state == "offline"
    assert status.offline is True
    assert status.manifest_revision == "cached"
    assert (
        json.loads(service._reconciler.last_good_path.read_text())["revision"]
        == "cached"
    )
