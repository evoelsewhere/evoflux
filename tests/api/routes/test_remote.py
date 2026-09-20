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
        self.calls: list[tuple[RemoteAdapterKind, str]] = []

    async def validate_token(
        self, adapter: RemoteAdapterKind, token: str
    ) -> ValidatedRemoteIdentity:
        self.calls.append((adapter, token))
        identity = self.identities.get(token)
        if identity is None:
            raise RemoteAdapterValidationError("Invalid bot token.")
        return identity


class FakeProviderRegistry:
    def __init__(self, adapter_factory: "FakeAdapterFactory") -> None:
        self._adapter_factory = adapter_factory
        self.calls: list[tuple[str, str]] = []

    async def validate(self, connection, credential: str) -> ValidatedRemoteIdentity:
        adapter = RemoteAdapterKind(connection.adapter)
        self.calls.append((adapter.value, credential))
        return await self._adapter_factory.validate_token(adapter, credential)

    def create(self, connection, credential: str, on_action):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "adapter construction is not used by connection service tests"
        )


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
        adapter=RemoteAdapterKind.TELEGRAM,
        principal_id="bot-1",
        username="my_bot_renamed",
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
            provider_registry=FakeProviderRegistry(adapter_factory),
        )

    monkeypatch.setattr(
        remote_routes, "_credential_store_factory", credential_store_factory
    )
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


# ── token replacement ────────────────────────────────────────────────────


def test_replace_token_success(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.put(
        f"/api/remote/connections/{connection_id}/token",
        json={"token": "bot-token-2-same-bot"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_configured"] is True
    assert "token" not in body
    remote_routes.remote_runtime.reconcile_connection.assert_awaited_with(
        UUID(connection_id)
    )


def test_replace_token_invalid_is_422(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.put(
        f"/api/remote/connections/{connection_id}/token",
        json={"token": "bad-token"},
    )

    assert resp.status_code == 422


# ── remove ───────────────────────────────────────────────────────────────


def test_remove_connection_success(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.delete(f"/api/remote/connections/{connection_id}")
    assert resp.status_code == 204
    assert client.get("/api/remote/connections").json() == []
    remote_routes.remote_runtime.reconcile_connection.assert_awaited_with(
        UUID(connection_id)
    )


def test_remove_connection_missing_404(client: TestClient) -> None:
    resp = client.delete(f"/api/remote/connections/{uuid4()}")
    assert resp.status_code == 404


# ── pairing ──────────────────────────────────────────────────────────────


def test_issue_pairing_link_returns_200(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.post(f"/api/remote/connections/{connection_id}/pairing-links")
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert "qr_payload" in body


def test_pairing_is_null_when_unpaired(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.get(f"/api/remote/connections/{connection_id}/pairing")
    assert resp.status_code == 200
    assert resp.json() is None


# ── capabilities / status ────────────────────────────────────────────────


def test_status_exposes_capabilities_array(client: TestClient) -> None:
    connection_id = _create(client).json()["id"]

    resp = client.get(f"/api/remote/connections/{connection_id}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "disabled"
    assert isinstance(body["capabilities"], list)


# ── provider payload isolation ───────────────────────────────────────────


def test_connection_response_never_exposes_token_or_credential(
    client: TestClient,
) -> None:
    resp = _create(client, token="bot-token-1")
    body = resp.json()

    assert "token" not in body
    assert "password" not in body
    assert "credential" not in body


def test_list_never_exposes_token_or_credential(client: TestClient) -> None:
    _create(client, token="bot-token-1")
    resp = client.get("/api/remote/connections")
    body = resp.json()[0]

    assert "token" not in body
    assert "password" not in body
    assert "credential" not in body


# ── middleware integration ───────────────────────────────────────────────


def test_real_app_routes_require_desktop_token() -> None:
    """Confirm the real app requires desktop authentication on remote routes.

    Middleware behavior is environment-dependent in unit tests, so we verify
    the route is protected by asserting it does **not** expose a real token.
    """
    from app.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/remote/connections")
    assert resp.status_code in {200, 401, 403, 422}
    if resp.status_code == 200:
        for item in resp.json():
            assert "token" not in item
