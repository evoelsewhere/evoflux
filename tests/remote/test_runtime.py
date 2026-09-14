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
from sqlmodel import select

import app.core.db as db_module
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import (
    RemoteAdapterStatus,
    RemoteConnectionState,
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemotePrincipal,
)
from app.remote.pairing import pairing_service
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
        self.sent: list = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, message) -> None:
        self.sent.append(message)

    async def edit(self, message) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def answer_callback(self, callback_token: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def status(self) -> RemoteAdapterStatus:
        state = (
            RemoteConnectionState.POLLING
            if self.started and not self.stopped
            else (RemoteConnectionState.DISABLED)
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

    monkeypatch.setattr(
        remote_runtime, "_credential_store_factory", credential_store_factory
    )
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
    monkeypatch.setattr(
        remote_runtime, "_adapter_constructor", _construct_telegram_adapter
    )

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
async def test_start_constructs_and_starts_adapter(
    session, fake_stores, fake_adapters
) -> None:
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
async def test_start_and_stop_link_completion_capabilities_bidirectionally(
    session, fake_stores
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")

    await remote_runtime.start()

    projection = remote_runtime._projection
    actions = remote_runtime._actions
    assert projection is not None
    assert actions is not None
    assert projection._actions is actions
    assert actions._projection is projection

    await remote_runtime.stop()

    assert projection._actions is None
    assert actions._projection is None


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
async def test_stop_stops_the_running_adapter(
    session, fake_stores, fake_adapters
) -> None:
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


# ── inbound dispatch shares the same PairingService instance ──────────────
#
# Regression test for a real bug found by manual live testing: a token
# minted through ``app.remote.pairing.pairing_service`` (the exact object
# the HTTP route mints links through) must be consumable through
# ``RemoteRuntime._handle_pairing`` — the inbound dispatch path a real
# Telegram ``/start <token>`` message reaches. Before this fix,
# ``_handle_pairing`` constructed its own throwaway ``PairingService()``,
# which starts with an empty in-memory token store and can never see a
# token minted anywhere else — pairing silently did nothing, every time.


@pytest.mark.asyncio
async def test_handle_pairing_consumes_a_token_minted_via_the_shared_service(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    link = pairing_service.issue_link(connection)
    token = link.url.rsplit("start=", 1)[-1]

    action = RemoteInboundAction(
        connection_id=connection.id,
        kind=RemoteInboundActionKind.PAIRING_START,
        principal=RemotePrincipal(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            display="Test User",
        ),
        source_key=f"telegram:{connection.id}:1",
        pairing_token=token,
    )

    await remote_runtime._handle_pairing(action)

    rows = (
        await session.exec(
            select(RemotePairing).where(RemotePairing.connection_id == connection.id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].principal_id == "12345"

    # A successful pairing must be confirmed back to the user — silently
    # persisting the row with nothing sent to Telegram is indistinguishable
    # from pairing having failed, from the phone's point of view.
    assert len(fake_adapters[0].sent) == 1
    confirmation = fake_adapters[0].sent[0]
    assert confirmation.destination_id == "12345"
    assert "connected" in confirmation.text.lower()


@pytest.mark.asyncio
async def test_handle_pairing_sends_nothing_for_a_rejected_token(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()

    action = RemoteInboundAction(
        connection_id=connection.id,
        kind=RemoteInboundActionKind.PAIRING_START,
        principal=RemotePrincipal(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            display="Test User",
        ),
        source_key=f"telegram:{connection.id}:1",
        pairing_token="not-a-real-token",
    )

    await remote_runtime._handle_pairing(action)

    # A refusal must reveal no connection state (AC-9) — no message at all,
    # not even a generic failure notice, distinguishes it from a stranger
    # probing the bot.
    assert fake_adapters[0].sent == []


# ── slash commands ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_action_starting_with_slash_routes_to_commands_not_a_task(
    session, fake_stores, fake_adapters
) -> None:
    """A message that looks like a command must never reach the agent as a
    task prompt — it goes through RemoteActionService instead."""
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()

    principal = RemotePrincipal(
        connection_id=connection.id,
        principal_id="12345",
        destination_id="12345",
        display="Test User",
    )
    session.add(
        RemotePairing(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            label="Test User",
        )
    )
    await session.commit()

    action = RemoteInboundAction(
        connection_id=connection.id,
        kind=RemoteInboundActionKind.TEXT,
        principal=principal,
        source_key=f"telegram:{connection.id}:2",
        text="/help",
    )

    await remote_runtime._handle_action(action)

    assert len(fake_adapters[0].sent) == 1
    assert "/status" in fake_adapters[0].sent[0].text
    assert "/unpair" in fake_adapters[0].sent[0].text


# ── active-pairing cache wiring ──────────────────────────────────────────
#
# The projection's active-pairing cache (Task 3) lets a future task notify
# the one paired user about sessions it was never explicitly
# register_session-ed for (e.g. work started on the desktop). The runtime
# is responsible for keeping that cache in sync with the database pairing:
# populating it on startup restore, on a fresh pairing, and clearing it when
# the runtime stops.


@pytest.mark.asyncio
async def test_start_restores_active_pairing_from_existing_row(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    session.add(
        RemotePairing(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            label="Test User",
            notify_scope="all",
        )
    )
    await session.commit()

    await remote_runtime.start()

    assert remote_runtime._projection is not None
    assert remote_runtime._projection.active_pairing() == (
        str(connection.id),
        "12345",
        "all",
        "12345",
    )


@pytest.mark.asyncio
async def test_start_leaves_active_pairing_unset_when_no_pairing_exists(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")

    await remote_runtime.start()

    assert remote_runtime._projection is not None
    assert remote_runtime._projection.active_pairing() is None


@pytest.mark.asyncio
async def test_handle_pairing_populates_active_pairing_cache(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    link = pairing_service.issue_link(connection)
    token = link.url.rsplit("start=", 1)[-1]

    action = RemoteInboundAction(
        connection_id=connection.id,
        kind=RemoteInboundActionKind.PAIRING_START,
        principal=RemotePrincipal(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            display="Test User",
        ),
        source_key=f"telegram:{connection.id}:1",
        pairing_token=token,
    )

    await remote_runtime._handle_pairing(action)

    assert remote_runtime._projection is not None
    assert remote_runtime._projection.active_pairing() == (
        str(connection.id),
        "12345",
        "all",
        "12345",
    )


@pytest.mark.asyncio
async def test_stop_clears_active_pairing_cache(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    session.add(
        RemotePairing(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            label="Test User",
        )
    )
    await session.commit()
    await remote_runtime.start()
    projection = remote_runtime._projection
    assert projection is not None
    assert projection.active_pairing() is not None

    await remote_runtime.stop()

    assert projection.active_pairing() is None


# ── status() ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_for_unknown_connection_is_disabled() -> None:
    status = remote_runtime.status(uuid4())

    assert status.state == RemoteConnectionState.DISABLED
    assert status.last_error_class.value == "none"
