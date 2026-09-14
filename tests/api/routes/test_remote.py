"""Tests for app/api/routes/remote.py — the ``/api/remote/*`` desktop API.

Route handlers are exercised against an isolated ``FastAPI()`` app carrying
only this router, with ``get_connection_service`` overridden to a fake
adapter-validation/vault-free `RemoteConnectionService` (mirroring
``tests/remote/test_connection_service.py``'s fakes) and
``remote_runtime``'s ``reconcile_connection``/``status`` monkeypatched so no
test here depends on — or re-tests — the runtime's own lifecycle logic
(covered separately by ``tests/remote/test_runtime.py``). A dedicated test
at the bottom uses the real ``create_app()`` to prove these routes sit
behind the existing desktop-token middleware like every other route.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.core.db as db_module
from app.api.routes import remote as remote_routes
from app.models.remote import RemotePairing
from app.remote.connection_service import RemoteConnectionService
from app.remote.contracts import (
    RemoteAdapterKind,
    RemoteAdapterStatus,
    RemoteAdapterValidationError,
    RemoteConnectionState,
    ValidatedRemoteIdentity,
)

#: Telegram bot tokens look like ``123456789:AAExampleShapeOnly``. Used only
#: to assert our OpenAPI example never resembles a real one.
_TELEGRAM_TOKEN_SHAPE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


class FakeCredentialStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def load(self) -> str | None:
        return self.value

    def save(self, credential: str) -> None:
        self.value = credential

    def delete(self) -> None:
        self.value = None


class FakeAdapterFactory:
    def __init__(self) -> None:
        self.identities: dict[str, ValidatedRemoteIdentity] = {}

    async def validate_token(
        self, adapter: RemoteAdapterKind, token: str
    ) -> ValidatedRemoteIdentity:
        identity = self.identities.get(token)
        if identity is None:
            raise RemoteAdapterValidationError("Invalid bot token.")
        return identity


@pytest.fixture
def credential_stores() -> dict[UUID, FakeCredentialStore]:
    return {}


@pytest.fixture
def adapter_factory() -> FakeAdapterFactory:
    factory = FakeAdapterFactory()
    factory.identities["bot-token-1"] = ValidatedRemoteIdentity(
        adapter=RemoteAdapterKind.TELEGRAM, principal_id="bot-1", username="my_bot"
    )
    factory.identities["bot-token-2-same-bot"] = ValidatedRemoteIdentity(
        adapter=RemoteAdapterKind.TELEGRAM, principal_id="bot-1", username="my_bot_renamed"
    )
    return factory


@pytest.fixture
def app(adapter_factory, credential_stores, monkeypatch) -> FastAPI:
    def credential_store_factory(connection_id: UUID) -> FakeCredentialStore:
        return credential_stores.setdefault(connection_id, FakeCredentialStore())

    def connection_service() -> RemoteConnectionService:
        return RemoteConnectionService(
            adapter_factory=adapter_factory,
            credential_store_factory=credential_store_factory,
        )

    monkeypatch.setattr(remote_routes, "_credential_store_factory", credential_store_factory)
    monkeypatch.setattr(
        remote_routes.remote_runtime, "reconcile_connection", AsyncMock()
    )
    monkeypatch.setattr(
        remote_routes.remote_runtime,
        "status",
        lambda connection_id: RemoteAdapterStatus(
            connection_id=connection_id, state=RemoteConnectionState.DISABLED
        ),
    )

    fastapi_app = FastAPI()
    fastapi_app.include_router(remote_routes.router, prefix="/api/remote")
    fastapi_app.dependency_overrides[remote_routes.get_connection_service] = (
        connection_service
    )
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def db_session():
    async with db_module.async_session_factory() as session:
        yield session


def _create(client: TestClient, *, label: str = "My phone", token: str = "bot-token-1"):
    return client.post("/api/remote/connections", json={"label": label, "token": token})


# ── list / create ────────────────────────────────────────────────────────


def test_list_connections_empty(client: TestClient) -> None:
    resp = client.get("/api/remote/connections")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_connection_success(client: TestClient) -> None:
    resp = _create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["label"] == "My phone"
    assert body["adapter"] == "telegram"
    assert body["adapter_principal_id"] == "bot-1"
    assert body["adapter_username"] == "my_bot"
    assert body["enabled"] is False
    assert body["token_configured"] is True
    assert "token" not in body
    assert body["status"]["state"] == "disabled"
    remote_routes.remote_runtime.reconcile_connection.assert_awaited_once_with(
        UUID(body["id"])
    )


def test_create_connection_invalid_token_is_422(client: TestClient) -> None:
    resp = _create(client, token="not-a-real-token")
    assert resp.status_code == 422
    remote_routes.remote_runtime.reconcile_connection.assert_not_awaited()


def test_create_second_connection_conflicts_409(client: TestClient) -> None:
    first = _create(client)
    assert first.status_code == 201

    second = _create(client, label="Second phone", token="bot-token-2-same-bot")
    assert second.status_code == 409


def test_list_connections_returns_created(client: TestClient) -> None:
    _create(client)
    resp = client.get("/api/remote/connections")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["label"] == "My phone"


# ── patch ────────────────────────────────────────────────────────────────


def test_patch_updates_label_and_enabled(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.patch(
        f"/api/remote/connections/{connection_id}",
        json={"label": "Renamed", "enabled": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Renamed"
    assert body["enabled"] is True
    remote_routes.remote_runtime.reconcile_connection.assert_awaited_with(
        UUID(connection_id)
    )


def test_patch_rejects_unknown_field_422(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.patch(
        f"/api/remote/connections/{connection_id}", json={"token": "sneaky-token"}
    )

    assert resp.status_code == 422


def test_patch_missing_connection_404(client: TestClient) -> None:
    resp = client.patch(f"/api/remote/connections/{uuid4()}", json={"label": "x"})
    assert resp.status_code == 404


def test_patch_invalid_uuid_422(client: TestClient) -> None:
    resp = client.patch("/api/remote/connections/not-a-uuid", json={"label": "x"})
    assert resp.status_code == 422


# ── token replace ────────────────────────────────────────────────────────


def test_replace_token_success(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.put(
        f"/api/remote/connections/{connection_id}/token",
        json={"token": "bot-token-2-same-bot"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["adapter_username"] == "my_bot_renamed"
    assert body["token_configured"] is True
    assert "token" not in body


def test_replace_token_invalid_is_422(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.put(
        f"/api/remote/connections/{connection_id}/token",
        json={"token": "not-a-real-token"},
    )

    assert resp.status_code == 422


def test_replace_token_missing_connection_404(client: TestClient) -> None:
    resp = client.put(
        f"/api/remote/connections/{uuid4()}/token", json={"token": "bot-token-1"}
    )
    assert resp.status_code == 404


# ── remove ───────────────────────────────────────────────────────────────


def test_remove_connection(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.delete(f"/api/remote/connections/{connection_id}")

    assert resp.status_code == 204
    assert client.get("/api/remote/connections").json() == []
    remote_routes.remote_runtime.reconcile_connection.assert_awaited_with(
        UUID(connection_id)
    )


def test_remove_missing_connection_404(client: TestClient) -> None:
    resp = client.delete(f"/api/remote/connections/{uuid4()}")
    assert resp.status_code == 404


# ── pairing links ────────────────────────────────────────────────────────


def test_issue_pairing_link(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.post(f"/api/remote/connections/{connection_id}/pairing-links")

    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("https://t.me/my_bot?start=")
    assert body["qr_payload"] == body["url"]
    assert "expires_at" in body


def test_issue_pairing_link_missing_connection_404(client: TestClient) -> None:
    resp = client.post(f"/api/remote/connections/{uuid4()}/pairing-links")
    assert resp.status_code == 404


# ── pairing read/revoke ──────────────────────────────────────────────────


def test_get_pairing_none(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.get(f"/api/remote/connections/{connection_id}/pairing")

    assert resp.status_code == 200
    assert resp.json() is None


def test_get_pairing_missing_connection_404(client: TestClient) -> None:
    resp = client.get(f"/api/remote/connections/{uuid4()}/pairing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_pairing_returns_existing_pairing(client: TestClient, db_session) -> None:
    connection_id = UUID(_create(client).json()["id"])
    pairing = RemotePairing(
        connection_id=connection_id,
        principal_id="user-1",
        destination_id="user-1",
        label="Alice's phone",
        display="Alice",
    )
    db_session.add(pairing)
    await db_session.commit()

    resp = client.get(f"/api/remote/connections/{connection_id}/pairing")

    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Alice's phone"
    assert body["display"] == "Alice"


@pytest.mark.asyncio
async def test_revoke_pairing_removes_it(client: TestClient, db_session) -> None:
    connection_id = UUID(_create(client).json()["id"])
    pairing = RemotePairing(
        connection_id=connection_id,
        principal_id="user-1",
        destination_id="user-1",
        label="Alice's phone",
        display="Alice",
    )
    db_session.add(pairing)
    await db_session.commit()

    resp = client.delete(f"/api/remote/connections/{connection_id}/pairing")
    assert resp.status_code == 204

    after = client.get(f"/api/remote/connections/{connection_id}/pairing")
    assert after.json() is None


def test_revoke_pairing_missing_connection_404(client: TestClient) -> None:
    resp = client.delete(f"/api/remote/connections/{uuid4()}/pairing")
    assert resp.status_code == 404


# ── status ───────────────────────────────────────────────────────────────


def test_get_connection_status(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.get(f"/api/remote/connections/{connection_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["connection_id"] == connection_id
    assert body["state"] == "disabled"
    assert body["paired"] is False
    assert body["last_error_class"] == "none"


def test_get_connection_status_missing_connection_404(client: TestClient) -> None:
    resp = client.get(f"/api/remote/connections/{uuid4()}/status")
    assert resp.status_code == 404


def test_get_connection_status_invalid_uuid_422(client: TestClient) -> None:
    resp = client.get("/api/remote/connections/not-a-uuid/status")
    assert resp.status_code == 422


# ── OpenAPI: no returned token fields, no realistic example ─────────────


def test_openapi_exposes_no_token_in_any_response_schema(app: FastAPI) -> None:
    schema = app.openapi()
    schemas = schema["components"]["schemas"]

    request_schemas_with_token = {
        "RemoteConnectionCreateRequest",
        "RemoteConnectionTokenReplaceRequest",
    }
    for name, definition in schemas.items():
        properties = definition.get("properties", {})
        if "token" not in properties:
            continue
        assert name in request_schemas_with_token, (
            f"{name} unexpectedly exposes a raw 'token' field"
        )

    assert "token_configured" in schemas["RemoteConnectionResponse"]["properties"]
    assert "token" not in schemas["RemoteConnectionResponse"]["properties"]


def test_openapi_token_example_is_not_realistic(app: FastAPI) -> None:
    schema = app.openapi()
    definition = schema["components"]["schemas"]["RemoteConnectionCreateRequest"]
    example = definition["properties"]["token"].get("example", "")
    assert not _TELEGRAM_TOKEN_SHAPE.match(example)


# ── desktop authentication ───────────────────────────────────────────────


def test_remote_routes_require_desktop_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-desktop-token")
    from app.api.app import create_app

    real_app_client = TestClient(create_app())

    unauthenticated = real_app_client.get("/api/remote/connections")
    assert unauthenticated.status_code == 401

    authenticated = real_app_client.get(
        "/api/remote/connections",
        headers={"Authorization": "Bearer secret-desktop-token"},
    )
    assert authenticated.status_code == 200
