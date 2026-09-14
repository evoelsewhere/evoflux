"""Durable connection-record coordination: validate, vault, persist, limit.

Keeps the v1 one-connection product limit, credential custody, and bot
identity binding in one narrow service so HTTP routes (a later task) stay
thin and the Telegram adapter (a later task) never touches ``settings.yaml``,
the database, or the credential vault directly.

Per the spec's concurrency contract, a database transaction here never
performs network or vault I/O: a token is validated against the adapter and
saved to the OS credential vault *before* the connection row is inserted or
updated, with a compensating vault write if the database commit then fails.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.credential_store import (
    CredentialStore,
    CredentialStoreError,
    CredentialStoreProtocol,
)
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import (
    RemoteAdapterFactory,
    RemoteAdapterKind,
    RemoteAdapterValidationError,
)

#: Vault service name every remote connection's credential is stored under.
#: The account key is derived per connection as ``connection:<uuid>`` and
#: never appears in an API response.
CREDENTIAL_VAULT_SERVICE = "EvoFlux Remote"

CredentialStoreFactory = Callable[[UUID], CredentialStoreProtocol]

__all__ = [
    "CREDENTIAL_VAULT_SERVICE",
    "CredentialStoreFactory",
    "RemoteAdapterValidationError",
    "RemoteConnectionConflictError",
    "RemoteConnectionError",
    "RemoteConnectionNotFoundError",
    "RemoteConnectionService",
    "RemoteCredentialError",
    "default_credential_store_factory",
]


def default_credential_store_factory(connection_id: UUID) -> CredentialStoreProtocol:
    """The production vault-account keying: ``connection:<connection_id>``."""
    return CredentialStore(
        service=CREDENTIAL_VAULT_SERVICE, account=f"connection:{connection_id}"
    )


class RemoteConnectionError(Exception):
    """Base class for :class:`RemoteConnectionService` domain errors."""


class RemoteConnectionConflictError(RemoteConnectionError):
    """A second connection was requested.

    AC-3: v1 permits exactly one configured connection. This is a
    service-level product limit, not a database uniqueness constraint, so a
    later release can lift it without a migration.
    """


class RemoteConnectionNotFoundError(RemoteConnectionError):
    """An operation named a connection ID that does not exist."""


class RemoteCredentialError(RemoteConnectionError):
    """The OS credential vault could not complete an operation.

    Never carries the token or any vault-internal detail beyond the
    underlying :class:`~app.core.credential_store.CredentialStoreError`
    message, which is itself already safe (AC-5).
    """


class RemoteConnectionService:
    """Coordinates connection lifecycle across the database, the OS
    credential vault, and adapter-identity validation."""

    def __init__(
        self,
        *,
        adapter_factory: RemoteAdapterFactory,
        credential_store_factory: CredentialStoreFactory | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._credential_store_factory = (
            credential_store_factory or default_credential_store_factory
        )

    def _store(self, connection_id: UUID) -> CredentialStoreProtocol:
        return self._credential_store_factory(connection_id)

    async def list(self, session: AsyncSession) -> list[RemoteConnection]:
        result = await session.exec(select(RemoteConnection))
        return list(result.all())

    async def get(
        self, session: AsyncSession, connection_id: UUID
    ) -> RemoteConnection | None:
        return await session.get(RemoteConnection, connection_id)

    async def create_connection(
        self, session: AsyncSession, *, token: str, label: str
    ) -> RemoteConnection:
        """Validate *token*, vault it, then persist a new connection.

        Raises :class:`RemoteConnectionConflictError` if a connection
        already exists,
        :class:`~app.remote.contracts.RemoteAdapterValidationError` if the
        token does not resolve to a bot identity, or
        :class:`RemoteCredentialError` if the vault save fails. In every
        failure case, no connection record is created.
        """
        if await self.list(session):
            raise RemoteConnectionConflictError(
                "This installation already has a configured remote connection."
            )

        identity = await self._adapter_factory.validate_token(
            RemoteAdapterKind.TELEGRAM, token
        )

        connection = RemoteConnection(
            adapter=identity.adapter.value,
            label=label,
            enabled=False,
            adapter_principal_id=identity.principal_id,
            adapter_username=identity.username,
        )

        store = self._store(connection.id)
        try:
            store.save(token)
        except CredentialStoreError as exc:
            raise RemoteCredentialError(str(exc)) from exc

        try:
            session.add(connection)
            await session.commit()
        except BaseException:
            await session.rollback()
            _delete_best_effort(store)
            raise

        await session.refresh(connection)
        return connection

    async def update_token(
        self, session: AsyncSession, connection_id: UUID, *, token: str
    ) -> RemoteConnection:
        """Validate and atomically replace a connection's bot token.

        A new identity whose ``principal_id`` differs from the one already
        stored (a different bot) invalidates the existing pairing row before
        the new credential becomes active (AC-6, AC-10). A new identity for
        the *same* bot leaves any existing pairing untouched — only the
        decorative username may change.
        """
        connection = await self.get(session, connection_id)
        if connection is None:
            raise RemoteConnectionNotFoundError(
                f"Remote connection {connection_id} does not exist."
            )

        identity = await self._adapter_factory.validate_token(
            RemoteAdapterKind.TELEGRAM, token
        )

        store = self._store(connection_id)
        try:
            previous_token = store.load()
        except CredentialStoreError:
            previous_token = None

        try:
            store.save(token)
        except CredentialStoreError as exc:
            raise RemoteCredentialError(str(exc)) from exc

        different_bot = identity.principal_id != connection.adapter_principal_id
        connection.adapter_principal_id = identity.principal_id
        connection.adapter_username = identity.username

        try:
            if different_bot:
                existing_pairings = await session.exec(
                    select(RemotePairing).where(
                        RemotePairing.connection_id == connection_id
                    )
                )
                for pairing in existing_pairings.all():
                    await session.delete(pairing)
            session.add(connection)
            await session.commit()
        except BaseException:
            await session.rollback()
            if previous_token is not None:
                _save_best_effort(store, previous_token)
            raise

        await session.refresh(connection)
        return connection

    async def set_enabled(
        self, session: AsyncSession, connection_id: UUID, *, enabled: bool
    ) -> RemoteConnection:
        connection = await self.get(session, connection_id)
        if connection is None:
            raise RemoteConnectionNotFoundError(
                f"Remote connection {connection_id} does not exist."
            )
        connection.enabled = enabled
        session.add(connection)
        await session.commit()
        await session.refresh(connection)
        return connection

    async def set_label(
        self, session: AsyncSession, connection_id: UUID, *, label: str
    ) -> RemoteConnection:
        """Rename a connection. Purely local metadata — never touches the
        vault, adapter identity, or pairing (mirrors :meth:`set_enabled`)."""
        connection = await self.get(session, connection_id)
        if connection is None:
            raise RemoteConnectionNotFoundError(
                f"Remote connection {connection_id} does not exist."
            )
        connection.label = label
        session.add(connection)
        await session.commit()
        await session.refresh(connection)
        return connection

    async def remove(self, session: AsyncSession, connection_id: UUID) -> None:
        """Delete the connection's vault entry, then the connection
        (cascading its pairing).

        The vault entry is deleted *first*, deliberately mirroring
        :meth:`create_connection` and :meth:`update_token`'s vault-before-
        commit ordering. A DB row that outlives its vault entry is a safe,
        recoverable state — the row still names the connection, so the user
        can retry ``remove`` (or ``set_enabled(False)``) and nothing is ever
        orphaned. The reverse order would delete the only reference to the
        vault account (``connection:<id>``) before confirming the secret was
        actually cleared, permanently stranding a live bot token in the OS
        vault if the vault delete then failed.
        """
        connection = await self.get(session, connection_id)
        if connection is None:
            raise RemoteConnectionNotFoundError(
                f"Remote connection {connection_id} does not exist."
            )

        store = self._store(connection_id)
        try:
            store.delete()
        except CredentialStoreError as exc:
            raise RemoteCredentialError(str(exc)) from exc

        await session.delete(connection)
        await session.commit()


def _delete_best_effort(store: CredentialStoreProtocol) -> None:
    try:
        store.delete()
    except CredentialStoreError:
        pass


def _save_best_effort(store: CredentialStoreProtocol, token: str) -> None:
    try:
        store.save(token)
    except CredentialStoreError:
        pass
