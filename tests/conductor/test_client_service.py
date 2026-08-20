from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
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
from app.conductor.models import (
    ManagedResourceRecord,
    Manifest,
    RegistrationRequest,
    ResourceChangePage,
    TelemetryBatchResponse,
)
from app.conductor.service import ConductorService
from app.conductor.telemetry import TelemetryOutbox
from app.conductor.constants.telemetry import (
    TelemetryCollectionLevel,
    TelemetryEventStatus,
    TelemetryEventType,
    TelemetryField,
)
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


def telemetry_delivery_payload(installation_id: str) -> dict[str, object]:
    return {
        "installation_id": installation_id,
        "window_days": 30,
        "from": "2026-07-19T10:00:00Z",
        "to": "2026-08-18T10:00:00Z",
        "events": 201,
        "requests": 10,
        "model_calls": 120,
        "tool_calls": 71,
        "tokens_in": 90_000,
        "tokens_out": 12_000,
        "cache_read_tokens": 5_000,
        "estimated_cost_usd_micros": 900_000,
        "unpriced_model_calls": 3,
        "attributed_events": 133,
        "attributed_requests": 7,
        "attributed_model_calls": 80,
        "attributed_tool_calls": 46,
        "attributed_estimated_cost_usd_micros": 640_000,
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


@pytest.mark.asyncio
async def test_governed_sync_recovers_from_a_rejected_persisted_cursor(
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

    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id="installation-1",
        project_id="project-1",
        enforcement_mode="enforce",
    )
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(store)
    managed_store = service._governed_reconciler.store
    managed_store.replace_project("project-1")
    managed_store.commit_cursor("project-1", "stale-signed-cursor")
    seen_cursors: list[str | None] = []

    class RecoveringClient:
        base_url = config.url
        credentials = store

        async def fetch_changes(self, cursor: str | None) -> ResourceChangePage:
            seen_cursors.append(cursor)
            if cursor is not None:
                raise ConductorRequestError(
                    httpx.codes.BAD_REQUEST, "invalid cursor signature"
                )
            return ResourceChangePage(
                schema_version=2,
                project_id="project-1",
                next_cursor="fresh-signed-cursor",
                has_more=False,
                changes=[],
            )

        async def report_inventory(self, _payload: dict[str, object]) -> None:
            return None

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, RecoveringClient())

    status = await service.sync_now()

    assert seen_cursors == ["stale-signed-cursor", None]
    assert managed_store.load().committed_cursor == "fresh-signed-cursor"
    assert status.state == "in_sync"
    assert status.error is None
    assert status.last_success_at is not None


@pytest.mark.asyncio
async def test_governed_sync_replays_feed_to_backfill_missing_mode_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    agents_dir = config_dir / "agents"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state_dir))
    monkeypatch.setattr(settings, "AGENTS_DIR", str(agents_dir))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(config_dir / "skills"))
    agents_dir.mkdir(parents=True)
    (config_dir / "skills").mkdir(parents=True)

    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    (agents_dir / "managed-agent.md").write_text(content, encoding="utf-8")
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id="installation-1",
        project_id="project-1",
        enforcement_mode="enforce",
    )
    credential_store = MemoryCredentialStore("evc_active")
    service = ConductorService(credential_store)
    managed_store = service._governed_reconciler.store
    managed_store.upsert(
        ManagedResourceRecord(
            project_id="project-1",
            resource_id="agent-1",
            version_id="agent-version-1",
            version="0.1.0",
            applied_version_id="agent-version-1",
            applied_version="0.1.0",
            release_channel="published",
            kind="agent",
            slug="managed-agent",
            modes=["work", "coding"],
            local_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            observed_state="in_sync",
            observed_at=datetime.now(UTC),
        )
    )
    managed_store.commit_cursor("project-1", "already-committed")
    seen_cursors: list[str | None] = []

    class ReplayClient:
        base_url = config.url
        credentials = credential_store

        async def fetch_changes(self, cursor: str | None) -> ResourceChangePage:
            seen_cursors.append(cursor)
            return ResourceChangePage(
                schema_version=2,
                project_id="project-1",
                next_cursor="fresh-cursor",
                has_more=False,
                changes=[],
            )

        async def report_inventory(self, _payload: dict[str, object]) -> None:
            return None

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, ReplayClient())

    await service.sync_now()

    assert seen_cursors == [None]
    assert managed_store.load().committed_cursor == "fresh-cursor"


def test_status_payload_preserves_v1_resource_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    service = ConductorService(MemoryCredentialStore("evc_active"))
    service.status.project_id = "project-1"
    service.status.resources = [
        {
            "kind": "mcp",
            "slug": "browser-tools",
            "state": "in_sync",
            "message": "Legacy V1 manifest resource",
        }
    ]
    service._governed_reconciler.store.replace_project("project-1")

    payload = service.status_payload()

    assert payload["resources"] == service.status.resources


@pytest.mark.asyncio
async def test_inventory_failure_does_not_block_telemetry_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state_dir))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(settings, "AGENTS_DIR", str(config_dir / "agents"))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(config_dir / "skills"))
    (config_dir / "agents").mkdir(parents=True)
    (config_dir / "skills").mkdir(parents=True)
    installation_id = str(uuid.uuid4())
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id=installation_id,
        project_id="project-1",
        collection_level=TelemetryCollectionLevel.COUNTERS,
        enforcement_mode="enforce",
    )
    outbox = TelemetryOutbox(tmp_path / "telemetry.json")
    assert outbox.enqueue(_telemetry_event(installation_id, "event-1"))
    credential_store = MemoryCredentialStore("evc_active")
    service = ConductorService(credential_store, telemetry_store=outbox)
    service._governed_reconciler.store.replace_project("project-1")
    telemetry_batches: list[list[dict[str, object]]] = []

    class InventoryFailureClient:
        base_url = config.url
        credentials = credential_store

        async def report_telemetry(
            self, _installation_id: str, events: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            telemetry_batches.append(events)
            return TelemetryBatchResponse(accepted=len(events), duplicates=0)

        async def fetch_changes(self, _cursor: str | None) -> ResourceChangePage:
            return ResourceChangePage(
                schema_version=2,
                project_id="project-1",
                next_cursor="cursor-1",
                has_more=False,
                changes=[],
            )

        async def report_inventory(self, _payload: dict[str, object]) -> None:
            raise ConductorRequestError(
                400, "content digest does not match applied version"
            )

        async def report_resource_usage(self, _events: list[dict[str, object]]) -> None:
            return None

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, InventoryFailureClient())

    status = await service.sync_now()

    assert [len(batch) for batch in telemetry_batches] == [1, 0]
    assert outbox.count() == 0
    assert status.sync.telemetry.state == "healthy"
    assert status.sync.telemetry.last_success_at is not None
    assert status.sync.inventory.state == "error"
    assert status.state == "error"


@pytest.mark.asyncio
async def test_one_flush_wake_drains_multiple_telemetry_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    installation_id = str(uuid.uuid4())
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id=installation_id,
        project_id="project-1",
        collection_level=TelemetryCollectionLevel.COUNTERS,
    )
    events = [
        _telemetry_event(installation_id, f"event-{index}") for index in range(205)
    ]
    outbox_path = tmp_path / "outbox.json"
    outbox_path.write_text(json.dumps(events), encoding="utf-8")
    outbox = TelemetryOutbox(outbox_path)
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(store, telemetry_store=outbox)
    batch_sizes: list[int] = []

    class DrainClient:
        base_url = config.url
        credentials = store

        async def report_telemetry(
            self, _installation_id: str, batch: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            batch_sizes.append(len(batch))
            return TelemetryBatchResponse(accepted=len(batch), duplicates=0)

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, DrainClient())

    await service._flush_telemetry()

    assert batch_sizes == [100, 100, 5, 0]
    assert outbox.count() == 0
    assert service.status.telemetry.last_flush_accepted == 205

    await service._flush_telemetry()

    assert service.status.telemetry.last_flush_accepted == 205


@pytest.mark.asyncio
async def test_empty_telemetry_queue_is_a_healthy_completed_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    installation_id = str(uuid.uuid4())
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id=installation_id,
        project_id="project-1",
        collection_level=TelemetryCollectionLevel.COUNTERS,
    )
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(
        store,
        telemetry_store=TelemetryOutbox(tmp_path / "empty-outbox.json"),
    )

    calls: list[list[dict[str, object]]] = []

    class SummaryClient:
        async def report_telemetry(
            self, _installation_id: str, events: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            calls.append(events)
            return TelemetryBatchResponse.model_validate(
                {
                    "accepted": 0,
                    "duplicates": 0,
                    "summary": telemetry_delivery_payload(installation_id),
                }
            )

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, SummaryClient())

    await service._flush_telemetry()

    assert service.status.sync.telemetry.state == "healthy"
    assert service.status.sync.telemetry.last_success_at is not None
    assert service.status.sync.telemetry.error is None
    assert calls == [[]]
    assert service.status.telemetry.delivery is not None
    assert service.status.telemetry.delivery.events == 201
    assert service.status_payload()["telemetry"]["delivery"]["window_start"] == (
        "2026-07-19T10:00:00Z"
    )


@pytest.mark.asyncio
async def test_empty_summary_refresh_tolerates_an_older_conductor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    installation_id = str(uuid.uuid4())
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id=installation_id,
        project_id="project-1",
        collection_level=TelemetryCollectionLevel.COUNTERS,
    )
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(
        store,
        telemetry_store=TelemetryOutbox(tmp_path / "empty-old-server.json"),
    )

    class OlderClient:
        async def report_telemetry(
            self, _installation_id: str, _events: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            raise ConductorRequestError(400, "events must contain 1–100 items")

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, OlderClient())

    await service._flush_telemetry()

    assert service.status.sync.telemetry.state == "healthy"
    assert service.status.sync.telemetry.error is None
    assert service.status.telemetry.delivery is None


@pytest.mark.asyncio
async def test_incomplete_telemetry_ack_keeps_the_durable_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    installation_id = str(uuid.uuid4())
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id=installation_id,
        project_id="project-1",
        collection_level=TelemetryCollectionLevel.COUNTERS,
    )
    outbox = TelemetryOutbox(tmp_path / "incomplete-ack.json")
    assert outbox.enqueue(_telemetry_event(installation_id, "event-1"))
    store = MemoryCredentialStore("evc_active")
    service = ConductorService(store, telemetry_store=outbox)

    class IncompleteAckClient:
        base_url = config.url
        credentials = store

        async def report_telemetry(
            self, _installation_id: str, _events: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            return TelemetryBatchResponse(accepted=0, duplicates=0)

    monkeypatch.setattr(service, "_config", lambda: config)
    service._client = cast(ConductorClient, IncompleteAckClient())

    await service._flush_telemetry()

    assert outbox.count() == 1
    assert service.status.sync.telemetry.state == "error"
    assert service.status.sync.telemetry.error == (
        "Conductor acknowledged an incomplete telemetry batch."
    )


@pytest.mark.asyncio
async def test_many_installations_flush_concurrently_without_cross_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    active = 0
    peak = 0
    active_lock = asyncio.Lock()
    services: list[ConductorService] = []
    outboxes: list[TelemetryOutbox] = []

    class ConcurrentClient:
        def __init__(self, config: ConductorSettings, store: MemoryCredentialStore):
            self.base_url = config.url
            self.credentials = store

        async def report_telemetry(
            self, _installation_id: str, events: list[dict[str, object]]
        ) -> TelemetryBatchResponse:
            nonlocal active, peak
            async with active_lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0)
            async with active_lock:
                active -= 1
            return TelemetryBatchResponse(accepted=len(events), duplicates=0)

    for index in range(200):
        installation_id = str(uuid.uuid4())
        config = ConductorSettings(
            enabled=True,
            url="https://conductor.example",
            installation_id=installation_id,
            project_id="project-1",
            collection_level=TelemetryCollectionLevel.COUNTERS,
        )
        store = MemoryCredentialStore(f"evc_user_{index}")
        outbox = TelemetryOutbox(tmp_path / f"outbox-{index}.json")
        assert outbox.enqueue(_telemetry_event(installation_id, f"event-{index}"))
        service = ConductorService(store, telemetry_store=outbox)
        monkeypatch.setattr(service, "_config", lambda config=config: config)
        service._client = cast(ConductorClient, ConcurrentClient(config, store))
        services.append(service)
        outboxes.append(outbox)

    await asyncio.gather(*(service._flush_telemetry() for service in services))

    assert peak > 1
    assert sum(outbox.count() for outbox in outboxes) == 0


def _telemetry_event(installation_id: str, event_id: str) -> dict[str, object]:
    return {
        TelemetryField.EVENT_ID: event_id,
        TelemetryField.INSTALLATION_ID: installation_id,
        TelemetryField.REQUEST_ID: f"request-{event_id}",
        TelemetryField.EVENT_TYPE: TelemetryEventType.MODEL_CALL,
        TelemetryField.STATUS: TelemetryEventStatus.SUCCESS,
        TelemetryField.REPORTED_AT: "2026-08-18T00:00:00+00:00",
        TelemetryField.TOKENS_IN: 10,
    }
