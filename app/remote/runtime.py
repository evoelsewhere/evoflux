"""Process singleton owning the remote connection's lazy adapter lifecycle.

AC-1 ("off and free by default") is the load-bearing contract of this
module: with no enabled, credentialed connection, nothing here ever
imports ``app.remote.telegram.adapter`` or ``app.remote.telegram.client``,
creates an ``asyncio.Task``, or makes a network call. Every reference to
either Telegram module is therefore a *function-local* import inside a
factory that only runs once a connection is actually enabled and
credentialed — never a module-level import here.

:data:`remote_runtime` is constructed once per process and owns at most one
live :class:`~app.remote.contracts.RemoteAdapter` — the v1 product limit is
one connection (AC-3), so there is never more than one to own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from loguru import logger

from app.core.credential_store import CredentialStoreError
from app.remote.connection_service import (
    CredentialStoreFactory,
    RemoteConnectionService,
    default_credential_store_factory,
)
from app.remote.contracts import (
    RemoteAdapter,
    RemoteAdapterKind,
    RemoteAdapterStatus,
    RemoteAdapterValidationError,
    RemoteConnectionState,
    RemoteInboundAction,
    ValidatedRemoteIdentity,
)

__all__ = [
    "AdapterConstructor",
    "RemoteActionHandler",
    "RemoteRuntime",
    "TelegramAdapterFactory",
    "remote_runtime",
]

#: Invoked for every classified inbound action the adapter dispatches. See
#: :class:`app.remote.telegram.adapter.RemoteActionHandler` — redefined here
#: (rather than imported) so this module never imports anything under
#: ``app.remote.telegram`` at module scope.
RemoteActionHandler = Callable[[RemoteInboundAction], Awaitable[object]]

#: Builds one connection's live adapter from its token. The production
#: implementation (:func:`_construct_telegram_adapter`) imports
#: ``app.remote.telegram.adapter`` lazily, inside the function body, so
#: merely *referencing* this type or constructing a :class:`RemoteRuntime`
#: never triggers that import.
AdapterConstructor = Callable[[UUID, str, RemoteActionHandler], RemoteAdapter]


class TelegramAdapterFactory:
    """Production ``RemoteAdapterFactory`` (see ``app.remote.contracts``).

    Validates a candidate bot token by calling Telegram's ``getMe`` — the
    only network call this factory ever makes, and only when a caller
    (``RemoteConnectionService.create_connection``/``update_token``, reached
    from ``POST``/``PUT /api/remote/connections...``) actually invokes
    :meth:`validate_token`. ``app.remote.telegram.client`` is imported
    lazily inside this method so constructing this factory, or importing
    this module, never pulls it into ``sys.modules`` (AC-1).
    """

    async def validate_token(
        self, adapter: RemoteAdapterKind, token: str
    ) -> ValidatedRemoteIdentity:
        from app.remote.telegram.client import (
            TelegramApiError,
            TelegramClient,
            TelegramMalformedResponseError,
            TelegramTransportError,
        )

        client = TelegramClient(token)
        try:
            me = await client.get_me()
        except (
            TelegramApiError,
            TelegramTransportError,
            TelegramMalformedResponseError,
        ) as exc:
            # Never include the token or the raw provider error (AC-5).
            raise RemoteAdapterValidationError(
                "The bot token could not be validated with Telegram."
            ) from exc
        finally:
            await client.aclose()

        if not me.is_bot:
            raise RemoteAdapterValidationError(
                "The token must belong to a bot account, not a user account."
            )

        return ValidatedRemoteIdentity(
            adapter=adapter, principal_id=str(me.id), username=me.username or ""
        )


def _default_connection_service() -> RemoteConnectionService:
    """The production ``RemoteConnectionService``.

    ``TelegramAdapterFactory()`` construction does not itself import
    Telegram — only a subsequent ``validate_token`` call does — so building
    this service here is safe even when no connection is configured.
    """
    return RemoteConnectionService(adapter_factory=TelegramAdapterFactory())


def _construct_telegram_adapter(
    connection_id: UUID, token: str, on_action: RemoteActionHandler
) -> RemoteAdapter:
    """Build the real Telegram adapter for one enabled, credentialed
    connection.

    This is the one place in this module that imports
    ``app.remote.telegram.adapter`` — and it happens only when
    :meth:`RemoteRuntime._start_locked` has already confirmed a connection
    is enabled and its vault credential is present (AC-1).
    """
    from app.remote.telegram.adapter import TelegramAdapter

    return TelegramAdapter(connection_id=connection_id, token=token, on_action=on_action)


class RemoteRuntime:
    """Owns the lifecycle of at most one live remote adapter.

    Every public method is safe to call at any time, including before any
    connection exists: ``start``/``reconcile_connection`` are no-ops unless
    the current connection is both ``enabled`` and has a vault credential,
    and ``stop``/``status`` never raise even when nothing is running.

    Constructor parameters exist purely for test injection (mirroring
    :class:`~app.remote.connection_service.RemoteConnectionService`'s own
    ``credential_store_factory`` pattern) — production code always
    constructs the module-level :data:`remote_runtime` with its defaults.
    """

    def __init__(
        self,
        *,
        connection_service_factory: Callable[[], RemoteConnectionService] | None = None,
        credential_store_factory: CredentialStoreFactory | None = None,
        adapter_constructor: AdapterConstructor | None = None,
    ) -> None:
        self._connection_service_factory = (
            connection_service_factory or _default_connection_service
        )
        self._credential_store_factory = (
            credential_store_factory or default_credential_store_factory
        )
        self._adapter_constructor = adapter_constructor or _construct_telegram_adapter

        #: Serializes start/stop/reconcile so concurrent calls (e.g. two
        #: rapid route mutations) cannot both observe "nothing running" and
        #: both start an adapter, or interleave a stop with a start.
        self._lock = asyncio.Lock()
        self._adapter: RemoteAdapter | None = None
        self._connection_id: UUID | None = None

    async def start(self) -> None:
        """Start the current connection's adapter, if any (AC-1).

        Called once from the app lifespan. A no-op when no connection
        exists, the connection is disabled, its vault credential is
        missing, or an adapter is already running.
        """
        async with self._lock:
            if self._adapter is not None:
                return
            await self._start_locked()

    async def stop(self) -> None:
        """Stop the running adapter, if any. Idempotent (AC-13) — always
        safe to call, including before ``start()`` was ever called."""
        async with self._lock:
            await self._stop_locked()

    async def reconcile_connection(self, connection_id: UUID) -> None:
        """Re-evaluate runtime state after a connection mutation.

        Called by the HTTP routes after any create, enable/disable, token
        replacement, or removal so the effect is immediate rather than
        requiring a process restart. v1 permits at most one connection
        (AC-3), so the correct reaction to *any* mutation is always the
        same: stop whatever is currently running, then re-evaluate the
        current database state from scratch. If that state is still (or
        newly) enabled and credentialed, a fresh adapter starts — bound to
        a replaced token when one was just rotated; otherwise nothing
        restarts.
        """
        logger.debug("remote_runtime_reconcile connection_id={}", connection_id)
        async with self._lock:
            await self._stop_locked()
            await self._start_locked()

    def status(self, connection_id: UUID) -> RemoteAdapterStatus:
        """Safe, diagnosable status for *connection_id* (AC-34).

        Returns the live adapter's status when it is the one currently
        running; otherwise a ``disabled`` shape naming *connection_id*.
        Never raises and never imports or constructs anything
        Telegram-specific.
        """
        if self._adapter is not None and self._connection_id == connection_id:
            return self._adapter.status()
        return RemoteAdapterStatus(
            connection_id=connection_id, state=RemoteConnectionState.DISABLED
        )

    # ------------------------------------------------------------------
    # Internal — callers must hold ``self._lock``.
    # ------------------------------------------------------------------

    async def _start_locked(self) -> None:
        from app.core.db import async_session_factory

        async with async_session_factory() as session:
            connections = await self._connection_service_factory().list(session)
        connection = connections[0] if connections else None
        if connection is None or not connection.enabled:
            return

        store = self._credential_store_factory(connection.id)
        try:
            token = store.load()
        except CredentialStoreError as exc:
            logger.error(
                "remote_runtime_credential_load_failed connection_id={} error={}",
                connection.id,
                exc,
            )
            return
        if not token:
            logger.warning(
                "remote_runtime_credential_missing connection_id={}", connection.id
            )
            return

        adapter = self._adapter_constructor(connection.id, token, self._handle_action)
        await adapter.start()
        self._adapter = adapter
        self._connection_id = connection.id

    async def _stop_locked(self) -> None:
        adapter, self._adapter = self._adapter, None
        self._connection_id = None
        if adapter is not None:
            await adapter.stop()

    async def _handle_action(self, action: RemoteInboundAction) -> None:
        """Placeholder inbound dispatch.

        This task (Desktop API and lazy runtime lifecycle) is scoped to
        AC-1, AC-2, AC-3, AC-5, AC-7, AC-10, AC-12, AC-13, AC-33, and AC-34
        — none of which require acting on inbound Telegram updates. A later
        task supplies the real ``RemoteInboundService`` (natural-language
        ingress and pairing consumption, AC-8/AC-14+) that this handler
        will delegate to. Until then, inbound actions are received — so the
        adapter's poll loop and offset bookkeeping run correctly end to
        end — and safely dropped, rather than duplicating business logic
        that belongs to ``PairingService``/a later inbound service here.
        """
        logger.debug(
            "remote_inbound_action_dropped connection_id={} kind={}",
            action.connection_id,
            action.kind,
        )


remote_runtime = RemoteRuntime()
