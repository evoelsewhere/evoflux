"""Tests for app/remote/runtime.py — the lazy-starting remote runtime.

Exercises ``RemoteRuntime.start/stop/reconcile_connection/status`` through
the process singleton (``remote_runtime``), with its adapter-construction
and credential-store seams monkeypatched to fakes so no real network call,
OS vault write, or Telegram import happens for the "enabled" cases. The
AC-1 test below deliberately uses the *unmodified* singleton against an
empty database to prove the disabled path never imports Telegram.
"""

from __future__ import annotations

import sys
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.remote import RemoteConnection
from app.remote.contracts import RemoteAdapterStatus, RemoteConnectionState
from app.remote.runtime import remote_runtime


class FakeCredentialStore:
    """In-memory stand-in for one connection's vault entry."""

    def __init__(self, token: str | None) -> None:
        self._token = token

    def load(self) -> str | None:
        return self._token

    def save(self, credential: str) -> None:  # pragma: no cover - unused here
        self._token = credential

    def delete(self) -> None:  # pragma: no cover - unused here
        self._token = None


class FakeAdapter:
    """In-memory stand-in for ``RemoteAdapter`` — no network, no task."""

    def __init__(self, *, connection_id: UUID, token: str) -> None:
        self.connection_id = connection_id
        self.token = token
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, message) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def edit(self, message) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def answer_callback(self, callback_token: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def status(self) -> RemoteAdapterStatus:
        state = RemoteConnectionState.POLLING if self.started and not self.stopped else (
            RemoteConnectionState.DISABLED
        )
        return RemoteAdapterStatus(connection_id=self.connection_id, state=state)


@pytest_asyncio.fixture(autouse=True)
async def _reset_runtime():
    """The runtime under test is the real process singleton — make sure no
    fake adapter or monkeypatched seam leaks into another test file."""
    yield
    await remote_runtime.stop()


@pytest_asyncio.fixture
async def session():
    async with db_module.async_session_factory() as db_session:
        yield db_session


@pytest.fixture
def fake_stores() -> dict[UUID, FakeCredentialStore]:
    return {}


@pytest.fixture
def fake_adapters() -> list[FakeAdapter]:
    return []


@pytest.fixture(autouse=True)
def _patch_seams(monkeypatch, fake_stores, fake_adapters):
    """Replace the runtime's Telegram-facing seams with fakes for every
    test in this module except the AC-1 one, which restores the real
    (default) seams itself to prove the production wiring never imports
    Telegram when nothing is configured."""

    def credential_store_factory(connection_id: UUID) -> FakeCredentialStore:
        return fake_stores.setdefault(connection_id, FakeCredentialStore(None))

    def adapter_constructor(connection_id: UUID, token: str, on_action):
        adapter = FakeAdapter(connection_id=connection_id, token=token)
        fake_adapters.append(adapter)
        return adapter

    monkeypatch.setattr(remote_runtime, "_credential_store_factory", credential_store_factory)
    monkeypatch.setattr(remote_runtime, "_adapter_constructor", adapter_constructor)


async def _make_connection(
    session, *, enabled: bool = True, principal_id: str = "bot-1"
) -> RemoteConnection:
    connection = RemoteConnection(
        adapter="telegram",
        label="My phone",
        enabled=enabled,
        adapter_principal_id=principal_id,
        adapter_username="my_bot",
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


# ── AC-1: off and free by default ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_start_does_not_import_telegram(monkeypatch) -> None:
    # Undo this module's autouse fake-seam patch for this one test — it must
    # prove the *real* production wiring (real TelegramAdapterFactory /
    # default_credential_store_factory / _construct_telegram_adapter),
    # against a genuinely empty connections table, never imports Telegram.
    from app.remote.connection_service import default_credential_store_factory
    from app.remote.runtime import _construct_telegram_adapter

    monkeypatch.setattr(
        remote_runtime, "_credential_store_factory", default_credential_store_factory
    )
    monkeypatch.setattr(remote_runtime, "_adapter_constructor", _construct_telegram_adapter)

    sys.modules.pop("app.remote.telegram.adapter", None)
    sys.modules.pop("app.remote.telegram.client", None)

    await remote_runtime.start()

    assert "app.remote.telegram.adapter" not in sys.modules
    assert "app.remote.telegram.client" not in sys.modules
    assert remote_runtime.status(uuid4()).state == RemoteConnectionState.DISABLED


@pytest.mark.asyncio
async def test_start_noop_when_no_connection_exists(fake_adapters) -> None:
    await remote_runtime.start()

    assert fake_adapters == []


@pytest.mark.asyncio
async def test_start_noop_when_connection_disabled(session, fake_adapters) -> None:
    await _make_connection(session, enabled=False)

    await remote_runtime.start()

    assert fake_adapters == []


@pytest.mark.asyncio
async def test_start_noop_when_credential_missing(session, fake_adapters) -> None:
    # enabled, but no token was ever saved to (the fake) vault
    await _make_connection(session, enabled=True)

    await remote_runtime.start()

    assert fake_adapters == []


# ── start() for an enabled, credentialed connection ─────────────────────────


@pytest.mark.asyncio
async def test_start_constructs_and_starts_adapter(session, fake_stores, fake_adapters) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")

    await remote_runtime.start()

    assert len(fake_adapters) == 1
    adapter = fake_adapters[0]
    assert adapter.connection_id == connection.id
    assert adapter.token == "secret-token"
    assert adapter.started is True
    assert remote_runtime.status(connection.id).state == RemoteConnectionState.POLLING


@pytest.mark.asyncio
async def test_start_is_idempotent_while_already_running(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")

    await remote_runtime.start()
    await remote_runtime.start()

    assert len(fake_adapters) == 1


# ── stop() ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_is_safe_before_start_was_ever_called() -> None:
    await remote_runtime.stop()  # must not raise

    assert remote_runtime.status(uuid4()).state == RemoteConnectionState.DISABLED


@pytest.mark.asyncio
async def test_stop_stops_the_running_adapter(session, fake_stores, fake_adapters) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()

    await remote_runtime.stop()

    assert fake_adapters[0].stopped is True
    assert remote_runtime.status(connection.id).state == RemoteConnectionState.DISABLED


@pytest.mark.asyncio
async def test_stop_is_idempotent(session, fake_stores, fake_adapters) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()

    await remote_runtime.stop()
    await remote_runtime.stop()  # must not raise a second time

    assert fake_adapters[0].stopped is True


# ── reconcile_connection() ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_starts_a_newly_enabled_connection(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=False)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    assert fake_adapters == []

    connection.enabled = True
    session.add(connection)
    await session.commit()
    await remote_runtime.reconcile_connection(connection.id)

    assert len(fake_adapters) == 1
    assert fake_adapters[0].started is True


@pytest.mark.asyncio
async def test_reconcile_stops_a_newly_disabled_connection(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    assert len(fake_adapters) == 1

    connection.enabled = False
    session.add(connection)
    await session.commit()
    await remote_runtime.reconcile_connection(connection.id)

    assert fake_adapters[0].stopped is True
    # No second adapter was constructed for the now-disabled connection.
    assert len(fake_adapters) == 1
    assert remote_runtime.status(connection.id).state == RemoteConnectionState.DISABLED


@pytest.mark.asyncio
async def test_reconcile_restarts_with_a_replaced_token(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("old-token")
    await remote_runtime.start()
    assert fake_adapters[0].token == "old-token"

    fake_stores[connection.id] = FakeCredentialStore("new-token")
    await remote_runtime.reconcile_connection(connection.id)

    assert fake_adapters[0].stopped is True
    assert len(fake_adapters) == 2
    assert fake_adapters[1].token == "new-token"
    assert fake_adapters[1].started is True


@pytest.mark.asyncio
async def test_reconcile_after_removal_leaves_nothing_running(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    assert len(fake_adapters) == 1

    await session.delete(await session.get(RemoteConnection, connection.id))
    await session.commit()
    await remote_runtime.reconcile_connection(connection.id)

    assert fake_adapters[0].stopped is True
    assert len(fake_adapters) == 1
    assert remote_runtime.status(connection.id).state == RemoteConnectionState.DISABLED


# ── status() ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_for_unknown_connection_is_disabled() -> None:
    status = remote_runtime.status(uuid4())

    assert status.state == RemoteConnectionState.DISABLED
    assert status.last_error_class.value == "none"
