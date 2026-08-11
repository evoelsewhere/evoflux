from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import cast

import httpx
import pytest

from app.conductor.client import (
    ConductorClient,
    ConductorRequestError,
    CredentialStoreError,
    redact_telemetry,
)
from app.conductor.models import Manifest, RegistrationRequest
from app.conductor.service import ConductorService
from app.core.config import settings
from app.core.runtime_settings import (
    ConductorSettings,
    RuntimeSettings,
    load_runtime_settings,
    save_runtime_settings,
)


class MemoryCredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def load(self) -> str | None:
        return self.value

    def save(self, credential: str) -> None:
        self.value = credential

    def delete(self) -> None:
        self.value = None


def registration_payload() -> dict[str, object]:
    return {
        "installation": {
            "id": "2effeb74-c492-40d3-93a5-1632e80329f5",
            "display_name": "EvoFlux on macOS",
            "heartbeat_interval_seconds": 60,
        },
        "project": {
            "id": "2eceb566-b0d7-485c-bddd-83389104e55f",
            "name": "Evo Project",
            "display_name": "Evo",
            "logo_url": "https://conductor.example/logo.svg",
        },
        "member": {
            "id": "2c89a539-ef6f-4c08-8416-3f420f1eb630",
            "display_name": "Mai Nguyen",
            "primary_role": "user",
            "sub_roles": [],
            "tags": [],
        },
        "policy": {
            "collection_level": "L1",
            "telemetry": {"enabled": True},
            "privacy_notice_version": "2026-08-10",
        },
    }


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
async def test_registration_uses_v1_contract_without_persisting_token() -> None:
    store = MemoryCredentialStore()
    idempotency_key = str(uuid.uuid4())
    installation_key = str(uuid.uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/client/register"
        assert request.headers["authorization"] == "Bearer evc_local_secret"
        assert request.headers["idempotency-key"] == idempotency_key
        payload = json.loads(request.content)
        assert payload["installation_key"] == installation_key
        assert "user_id" not in payload
        assert "project_id" not in payload
        return httpx.Response(200, json=registration_payload())

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        registered = await client.register(
            " evc_local_secret ",
            RegistrationRequest(
                installation_key=installation_key,
                display_name="EvoFlux on macOS",
                platform="macos",
                evoflux_version="0.8.0",
            ),
            idempotency_key=idempotency_key,
        )
    finally:
        await client.close()

    assert registered.project.name == "Evo Project"
    assert registered.member.display_name == "Mai Nguyen"
    assert registered.policy.collection_level == "L1"
    assert store.load() is None


@pytest.mark.asyncio
async def test_rejected_registration_is_terminal_and_never_saves_token() -> None:
    store = MemoryCredentialStore()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConductorRequestError) as raised:
            await client.register(
                "evc_rejected_secret",
                RegistrationRequest(
                    installation_key=str(uuid.uuid4()),
                    display_name="EvoFlux on Linux",
                    platform="linux",
                    evoflux_version="0.8.0",
                ),
                idempotency_key=str(uuid.uuid4()),
            )
    finally:
        await client.close()

    assert raised.value.status_code == 401
    assert store.load() is None


@pytest.mark.asyncio
async def test_heartbeat_uses_stored_token() -> None:
    store = MemoryCredentialStore("evc_local_secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/client/heartbeat"
        assert request.headers["authorization"] == "Bearer evc_local_secret"
        assert json.loads(request.content) == {"installation_id": "installation-1"}
        return httpx.Response(
            200,
            json={
                "server_time": "2026-08-10T10:30:00Z",
                "heartbeat_interval_seconds": 60,
                "connection_state": "active",
            },
        )

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        heartbeat = await client.heartbeat("installation-1")
    finally:
        await client.close()
    assert heartbeat.connection_state == "active"


@pytest.mark.asyncio
async def test_v1_snapshot_is_adapted_to_manifest() -> None:
    store = MemoryCredentialStore("evc_local_secret")
    snapshot = [
        {
            "id": "resource-1",
            "kind": "agent",
            "slug": "reviewer",
            "version": "1.2.0",
            "payload": {
                "frontmatter": {"name": "Reviewer"},
                "system_prompt": "Review the proposed change.",
            },
        },
        {
            "id": "resource-2",
            "kind": "workflow",
            "slug": "release",
            "version": "1",
            "payload": {},
        },
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/subscribe/resources"
        assert request.headers["authorization"] == "Bearer evc_local_secret"
        return httpx.Response(200, json=snapshot)

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        manifest, etag = await client.fetch_manifest()
        unchanged, repeated_etag = await client.fetch_manifest(etag)
    finally:
        await client.close()

    assert manifest is not None
    assert [(item.kind, item.slug, item.revision) for item in manifest.resources] == [
        ("agent", "reviewer", "1.2.0")
    ]
    assert etag == f'"v1-{manifest.revision}"'
    assert unchanged is None
    assert repeated_etag == etag


@pytest.mark.asyncio
async def test_governed_text_resource_verifies_canonical_payload_digest() -> None:
    store = MemoryCredentialStore("evc_local_secret")
    payload = {
        "files": [
            {
                "path": "reviewer.md",
                "content": "---\nname: reviewer\ndescription: Review\n---\nReview.\n",
            }
        ]
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/resources/resource-1/versions/version-1"
        return httpx.Response(
            200,
            json={
                "project_id": "project-1",
                "resource_id": "resource-1",
                "version_id": "version-1",
                "kind": "agent",
                "slug": "reviewer",
                "version": "0.1.0",
                "release_channel": "published",
                "payload": payload,
                "sha256": hashlib.sha256(canonical).hexdigest(),
                "size": len(canonical),
            },
        )

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        version = await client.fetch_resource_version("resource-1", "version-1")
    finally:
        await client.close()
    assert version.slug == "reviewer"


@pytest.mark.asyncio
async def test_governed_text_resource_rejects_payload_digest_mismatch() -> None:
    store = MemoryCredentialStore("evc_local_secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "project_id": "project-1",
                "resource_id": "resource-1",
                "version_id": "version-1",
                "kind": "skill",
                "slug": "reviewer",
                "version": "0.1.0",
                "release_channel": "published",
                "payload": {"files": []},
                "sha256": "0" * 64,
                "size": 12,
            },
        )

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ValueError, match="digest mismatch"):
            await client.fetch_resource_version("resource-1", "version-1")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_service_persists_safe_registration_state_and_disconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state_dir))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=False,
                url="https://conductor.example",
            )
        )
    )
    store = MemoryCredentialStore()
    service = ConductorService(store)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/client/register"
        return httpx.Response(200, json=registration_payload())

    def client_factory(config: ConductorSettings) -> ConductorClient:
        return ConductorClient(
            config.url,
            store,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(service, "_new_client", client_factory)
    status = await service.connect("evc_local_secret")

    persisted = load_runtime_settings().conductor
    assert status.enrolled is True
    assert status.project_display_name == "Evo"
    assert persisted.installation_key is not None
    assert persisted.installation_id == "2effeb74-c492-40d3-93a5-1632e80329f5"
    assert persisted.member_display_name == "Mai Nguyen"
    assert persisted.collection_level == "L1"
    assert store.load() == "evc_local_secret"

    disconnected = await service.disconnect()
    assert disconnected.state == "disconnected"
    assert store.load() is None
    assert load_runtime_settings().conductor.installation_id is None


@pytest.mark.asyncio
async def test_failed_connect_reuses_one_persisted_installation_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=False,
                url="https://conductor.example",
            )
        )
    )
    store = MemoryCredentialStore()
    service = ConductorService(store)
    seen_keys: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(json.loads(request.content)["installation_key"])
        return httpx.Response(401, json={"error": "invalid token"})

    def client_factory(config: ConductorSettings) -> ConductorClient:
        return ConductorClient(
            config.url,
            store,
            retries=0,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(service, "_new_client", client_factory)
    for _ in range(2):
        with pytest.raises(ConductorRequestError):
            await service.connect("evc_rejected")

    assert seen_keys[0] == seen_keys[1]
    assert load_runtime_settings().conductor.installation_key == seen_keys[0]
    assert load_runtime_settings().conductor.installation_id is None
    assert store.load() is None


@pytest.mark.asyncio
async def test_credential_store_failure_leaves_no_partial_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=False,
                url="https://conductor.example",
            )
        )
    )

    class FailingCredentialStore(MemoryCredentialStore):
        def save(self, credential: str) -> None:
            del credential
            raise CredentialStoreError("Credential vault unavailable.")

    store = FailingCredentialStore()
    service = ConductorService(store)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=registration_payload())

    monkeypatch.setattr(
        service,
        "_new_client",
        lambda config: ConductorClient(
            config.url,
            store,
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(CredentialStoreError):
        await service.connect("evc_local_secret")

    persisted = load_runtime_settings().conductor
    assert persisted.installation_key is not None
    assert persisted.installation_id is None
    assert persisted.project_id is None
    assert store.load() is None


@pytest.mark.asyncio
async def test_authorization_failure_stops_heartbeat_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=True,
                url="https://conductor.example",
                installation_key=str(uuid.uuid4()),
                installation_id=str(uuid.uuid4()),
            )
        )
    )
    store = MemoryCredentialStore("evc_revoked")
    service = ConductorService(store)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    service._client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    status = await service.heartbeat_now()
    await service._client.close()

    assert status.state == "authorization_required"
    assert service._stop.is_set()


@pytest.mark.asyncio
async def test_heartbeat_persists_server_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    installation_id = str(uuid.uuid4())
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=True,
                url="https://conductor.example",
                installation_key=str(uuid.uuid4()),
                installation_id=installation_id,
            )
        )
    )
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(store)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "server_time": "2026-08-10T10:30:00Z",
                "heartbeat_interval_seconds": 120,
                "connection_state": "active",
            },
        )

    service._client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    status = await service.heartbeat_now()
    await service._client.close()

    assert status.heartbeat_interval_seconds == 120
    assert load_runtime_settings().conductor.heartbeat_interval_seconds == 120


@pytest.mark.asyncio
async def test_stale_installation_requires_registration_and_clears_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=True,
                url="https://conductor.example",
                installation_key=str(uuid.uuid4()),
                installation_id=str(uuid.uuid4()),
                project_id=str(uuid.uuid4()),
                project_name="evo",
                member_id=str(uuid.uuid4()),
                member_display_name="Mai Nguyen",
            )
        )
    )
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(store)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "installation not found"})

    service._client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    status = await service.heartbeat_now()
    await service._client.close()

    persisted = load_runtime_settings().conductor
    assert status.state == "registration_required"
    assert status.enrolled is False
    assert persisted.installation_id is None
    assert persisted.project_id is None
    assert persisted.member_id is None
    assert store.load() == "evc_active"
    assert service._stop.is_set()


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
    store = MemoryCredentialStore("evc_local_secret")

    service = ConductorService(store)
    manifest = Manifest.model_validate(
        {"schema_version": 1, "revision": "cached", "resources": []}
    )
    service._reconciler.save_last_good_manifest(manifest)
    config = ConductorSettings(
        enabled=True,
        url="https://offline.example",
        installation_key=str(uuid.uuid4()),
        installation_id=str(uuid.uuid4()),
        enforcement_mode="report",
    )
    monkeypatch.setattr(service, "_config", lambda: config)

    class OfflineClient:
        base_url = config.url
        credentials = store

        async def fetch_manifest(self, _etag):
            request = httpx.Request("GET", f"{config.url}/api/v1/subscribe/resources")
            raise httpx.ConnectError("offline", request=request)

    service._client = cast(ConductorClient, OfflineClient())
    status = await service.sync_now()

    assert status.state == "offline"
    assert status.offline is True
    assert status.manifest_revision == "cached"
    assert (
        json.loads(service._reconciler.last_good_path.read_text())["revision"]
        == "cached"
    )
