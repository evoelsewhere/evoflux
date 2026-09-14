"""Tests for app/remote/connection_service.py.

Exercises the durable half of connection setup — validate, vault, persist,
one-connection limit, bot-identity binding, and pairing invalidation on
bot replacement — without ever calling Telegram. ``FakeAdapterFactory``
implements the ``RemoteAdapterFactory`` protocol synchronously in-process,
and ``FakeCredentialStore`` stands in for the OS vault.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlmodel import select

import app.core.db as db_module
from app.core.credential_store import CredentialStoreError
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.connection_service import (
    RemoteConnectionConflictError,
    RemoteConnectionNotFoundError,
    RemoteConnectionService,
    RemoteCredentialError,
)
from app.remote.contracts import (
    RemoteAdapterKind,
    RemoteAdapterValidationError,
    ValidatedRemoteIdentity,
)


class FakeCredentialStore:
    """In-memory stand-in for the OS vault, one instance per connection ID."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.save_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.deleted: list[str] = []

    def load(self) -> str | None:
        return self.values.get("token")

    def save(self, credential: str) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.values["token"] = credential

    def delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(self.values.pop("token", ""))


class FakeAdapterFactory:
    """Synchronous, in-process stand-in for ``RemoteAdapterFactory``."""

    def __init__(self) -> None:
        #: token -> identity it resolves to. Missing tokens are invalid.
        self.identities: dict[str, ValidatedRemoteIdentity] = {}
        self.calls: list[str] = []

    async def validate_token(
        self, adapter: RemoteAdapterKind, token: str
    ) -> ValidatedRemoteIdentity:
        self.calls.append(token)
        identity = self.identities.get(token)
        if identity is None:
            raise RemoteAdapterValidationError("Invalid bot token.")
        return identity


@pytest.fixture
def adapter_factory() -> FakeAdapterFactory:
    factory = FakeAdapterFactory()
    factory.identities["bot-token-1"] = ValidatedRemoteIdentity(
        adapter=RemoteAdapterKind.TELEGRAM,
        principal_id="bot-1",
        username="my_bot",
    )
    factory.identities["bot-token-2-same-bot"] = ValidatedRemoteIdentity(
        adapter=RemoteAdapterKind.TELEGRAM,
        principal_id="bot-1",
        username="my_bot_renamed",
    )
    factory.identities["bot-token-3-different-bot"] = ValidatedRemoteIdentity(
        adapter=RemoteAdapterKind.TELEGRAM,
        principal_id="bot-2",
        username="another_bot",
    )
    return factory


@pytest.fixture
def credential_stores() -> dict[UUID, FakeCredentialStore]:
    return {}


@pytest.fixture
def service(adapter_factory, credential_stores):
    def factory(connection_id: UUID) -> FakeCredentialStore:
        return credential_stores.setdefault(connection_id, FakeCredentialStore())

    return RemoteConnectionService(
        adapter_factory=adapter_factory,
        credential_store_factory=factory,
    )


@pytest_asyncio.fixture
async def session():
    async with db_module.async_session_factory() as db_session:
        yield db_session


# ── create_connection ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_validates_token_before_any_persistence(
    session, service, adapter_factory
) -> None:
    with pytest.raises(RemoteAdapterValidationError):
        await service.create_connection(session, token="unknown-token", label="Phone")

    assert (await session.exec(select(RemoteConnection))).all() == []
    assert adapter_factory.calls == ["unknown-token"]


@pytest.mark.asyncio
async def test_create_persists_validated_identity_and_vaults_token(
    session, service, credential_stores
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="My phone"
    )

    assert connection.adapter == "telegram"
    assert connection.adapter_principal_id == "bot-1"
    assert connection.adapter_username == "my_bot"
    assert connection.label == "My phone"
    assert connection.enabled is False

    store = credential_stores[connection.id]
    assert store.load() == "bot-token-1"

    rows = (await session.exec(select(RemoteConnection))).all()
    assert [row.id for row in rows] == [connection.id]


@pytest.mark.asyncio
async def test_create_rejects_second_connection_with_conflict(session, service) -> None:
    await service.create_connection(session, token="bot-token-1", label="First")

    with pytest.raises(RemoteConnectionConflictError):
        await service.create_connection(session, token="bot-token-1", label="Second")

    rows = (await session.exec(select(RemoteConnection))).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_rolls_back_when_vault_save_fails(
    session, service, credential_stores
) -> None:
    # The store doesn't exist yet — pre-seed it under the id the service
    # will generate isn't possible, so instead make every store fail by
    # patching the factory's default behavior via a poisoned instance
    # returned for any id.
    poisoned = FakeCredentialStore()
    poisoned.save_error = CredentialStoreError("vault unavailable")
    service._credential_store_factory = lambda _connection_id: poisoned

    with pytest.raises(RemoteCredentialError):
        await service.create_connection(session, token="bot-token-1", label="Phone")

    assert (await session.exec(select(RemoteConnection))).all() == []


@pytest.mark.asyncio
async def test_create_deletes_vaulted_token_when_commit_fails(
    session, service, credential_stores, monkeypatch
) -> None:
    async def failing_commit() -> None:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(session, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        await service.create_connection(session, token="bot-token-1", label="Phone")

    # Compensating cleanup ran: whichever store got the token had it deleted.
    (store,) = credential_stores.values()
    assert store.load() is None
    assert store.deleted == ["bot-token-1"]


# ── update_token ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_token_for_same_bot_retains_pairing(
    session, service, credential_stores
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    pairing = RemotePairing(
        connection_id=connection.id,
        principal_id="telegram-user-1",
        destination_id="telegram-chat-1",
        label="My phone",
    )
    session.add(pairing)
    await session.commit()

    updated = await service.update_token(
        session, connection.id, token="bot-token-2-same-bot"
    )

    assert updated.adapter_principal_id == "bot-1"
    assert updated.adapter_username == "my_bot_renamed"
    assert credential_stores[connection.id].load() == "bot-token-2-same-bot"

    remaining = (
        await session.exec(
            select(RemotePairing).where(RemotePairing.connection_id == connection.id)
        )
    ).all()
    assert [row.id for row in remaining] == [pairing.id]


@pytest.mark.asyncio
async def test_update_token_for_different_bot_invalidates_pairing(
    session, service
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    pairing = RemotePairing(
        connection_id=connection.id,
        principal_id="telegram-user-1",
        destination_id="telegram-chat-1",
        label="My phone",
    )
    session.add(pairing)
    await session.commit()

    updated = await service.update_token(
        session, connection.id, token="bot-token-3-different-bot"
    )

    assert updated.adapter_principal_id == "bot-2"
    assert updated.adapter_username == "another_bot"

    remaining = (
        await session.exec(
            select(RemotePairing).where(RemotePairing.connection_id == connection.id)
        )
    ).all()
    assert remaining == []


@pytest.mark.asyncio
async def test_update_token_unknown_connection_raises_not_found(
    session, service
) -> None:
    with pytest.raises(RemoteConnectionNotFoundError):
        await service.update_token(session, uuid4(), token="bot-token-1")


@pytest.mark.asyncio
async def test_update_token_rejects_invalid_replacement_without_mutating_connection(
    session, service, credential_stores
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )

    with pytest.raises(RemoteAdapterValidationError):
        await service.update_token(session, connection.id, token="garbage")

    refreshed = await service.get(session, connection.id)
    assert refreshed.adapter_principal_id == "bot-1"
    assert credential_stores[connection.id].load() == "bot-token-1"


# ── set_enabled / remove ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_enabled_toggles_the_connection(session, service) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    assert connection.enabled is False

    enabled = await service.set_enabled(session, connection.id, enabled=True)
    assert enabled.enabled is True

    disabled = await service.set_enabled(session, connection.id, enabled=False)
    assert disabled.enabled is False


@pytest.mark.asyncio
async def test_set_enabled_unknown_connection_raises_not_found(
    session, service
) -> None:
    with pytest.raises(RemoteConnectionNotFoundError):
        await service.set_enabled(session, uuid4(), enabled=True)


@pytest.mark.asyncio
async def test_remove_deletes_connection_pairing_and_vault_value(
    session, service, credential_stores
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    pairing = RemotePairing(
        connection_id=connection.id,
        principal_id="telegram-user-1",
        destination_id="telegram-chat-1",
        label="My phone",
    )
    session.add(pairing)
    await session.commit()

    await service.remove(session, connection.id)

    assert (await session.exec(select(RemoteConnection))).all() == []
    assert (await session.exec(select(RemotePairing))).all() == []
    assert credential_stores[connection.id].load() is None
    assert credential_stores[connection.id].deleted == ["bot-token-1"]


@pytest.mark.asyncio
async def test_remove_unknown_connection_raises_not_found(session, service) -> None:
    with pytest.raises(RemoteConnectionNotFoundError):
        await service.remove(session, uuid4())


@pytest.mark.asyncio
async def test_remove_reports_vault_deletion_failure_without_orphaning_the_row(
    session, service, credential_stores
) -> None:
    """A vault-delete failure must never delete the connection row first —
    that would strand the vault's ``connection:<id>`` secret with no
    remaining reference anywhere in the app. The vault is deleted before the
    row, so a failure here leaves the row intact and the operation safely
    retryable."""
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    credential_stores[connection.id].delete_error = CredentialStoreError(
        "vault unavailable"
    )

    with pytest.raises(RemoteCredentialError):
        await service.remove(session, connection.id)

    # Not orphaned: the row survives, so the vault account is still named
    # and remove() can be retried once the vault is reachable again.
    rows = (await session.exec(select(RemoteConnection))).all()
    assert [row.id for row in rows] == [connection.id]


@pytest.mark.asyncio
async def test_remove_retried_after_vault_recovers_deletes_everything(
    session, service, credential_stores
) -> None:
    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )
    store = credential_stores[connection.id]
    store.delete_error = CredentialStoreError("vault unavailable")

    with pytest.raises(RemoteCredentialError):
        await service.remove(session, connection.id)

    # The vault recovers (e.g. the OS keychain becomes reachable again) and
    # the same remove() call is retried without needing any repair step.
    store.delete_error = None
    await service.remove(session, connection.id)

    assert (await session.exec(select(RemoteConnection))).all() == []
    assert store.load() is None


# ── list / get ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_and_get_reflect_persisted_connections(session, service) -> None:
    assert await service.list(session) == []
    assert await service.get(session, uuid4()) is None

    connection = await service.create_connection(
        session, token="bot-token-1", label="Phone"
    )

    assert [row.id for row in await service.list(session)] == [connection.id]
    fetched = await service.get(session, connection.id)
    assert fetched is not None
    assert fetched.id == connection.id
