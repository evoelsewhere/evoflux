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
from typing import TYPE_CHECKING
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
    RemoteOutboundMessage,
    RemoteOutboundPriority,
    ValidatedRemoteIdentity,
)

if TYPE_CHECKING:
    from app.remote.actions import RemoteActionService
    from app.remote.gates import RemoteGateBridge
    from app.remote.outbound import RemoteProjection

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

    return TelegramAdapter(
        connection_id=connection_id, token=token, on_action=on_action
    )


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

        #: Stream projection for outbound delivery. Created lazily.
        self._projection: RemoteProjection | None = None
        self._observer_unregister: Callable[[], None] | None = None
        self._bridge: RemoteGateBridge | None = None
        self._actions: "RemoteActionService | None" = None

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
        from app.core.db import read_session_factory

        async with read_session_factory() as session:
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

        # Register the outbound projection as a stream observer.
        from app.remote.outbound import RemoteProjection

        projection = RemoteProjection()
        projection.set_adapter(adapter)
        self._projection = projection

        # Create the gate bridge for callback resolution.
        from app.remote.gates import RemoteGateBridge

        self._bridge = RemoteGateBridge(adapter=adapter)
        projection.set_bridge(self._bridge)

        # Slash commands (/help, /status, /new, /stop, /unpair, /actions) and
        # the More-actions menu — shares the same PairingService singleton
        # every other pairing-aware caller uses (see the module docstring in
        # app/remote/pairing.py for why a locally-constructed one would be
        # silently broken).
        from app.remote.actions import RemoteActionService
        from app.remote.pairing import pairing_service as _shared_pairing_service

        self._actions = RemoteActionService(
            pairing_service=_shared_pairing_service,
            adapter=adapter,
            status_provider=lambda: self.status(connection.id),
        )

        from app.services.memory_stream_store import register_observer

        self._observer_unregister = register_observer(projection.observe)

        logger.info("remote_runtime_started connection_id={}", connection.id)

    async def _stop_locked(self) -> None:
        adapter, self._adapter = self._adapter, None
        self._connection_id = None

        # Unregister the stream observer before stopping the adapter.
        if self._observer_unregister is not None:
            self._observer_unregister()
            self._observer_unregister = None
        if self._projection is not None:
            self._projection.set_adapter(None)
            self._projection.set_bridge(None)
            self._projection = None
        self._bridge = None
        self._actions = None

        if adapter is not None:
            await adapter.stop()

    async def _handle_action(self, action: RemoteInboundAction) -> None:
        """Dispatch one classified inbound action to the appropriate service.

        TEXT actions go to :class:`~app.remote.inbound.RemoteInboundService`;
        PAIRING_START actions are consumed by
        :class:`~app.remote.pairing.PairingService`; CALLBACK actions are
        handled by :class:`~app.remote.gates.RemoteGateBridge`.
        """
        from app.remote.contracts import RemoteInboundActionKind

        if action.kind == RemoteInboundActionKind.PAIRING_START:
            await self._handle_pairing(action)
        elif action.kind == RemoteInboundActionKind.TEXT:
            if (action.text or "").strip().startswith("/"):
                await self._handle_command(action)
            else:
                await self._handle_text(action)
        elif action.kind == RemoteInboundActionKind.CALLBACK:
            # Two independent, opaque token namespaces share the callback
            # channel: gate replies (permission/question/plan) owned by
            # RemoteGateBridge, and More-actions menu picks owned by
            # RemoteActionService. Try the menu first — it's a plain dict
            # membership check — and fall back to the gate bridge, which
            # already degrades safely (logs + no-ops) on an unknown token.
            handled = False
            if self._actions is not None and action.callback_token is not None:
                handled = await self._actions.handle_action_callback(action)
            if not handled and self._bridge is not None:
                await self._bridge.handle_callback(action)
            elif not handled and self._bridge is None:
                logger.debug(
                    "remote_callback_no_bridge connection_id={} source_key={}",
                    action.connection_id,
                    action.source_key,
                )
        else:
            logger.debug(
                "remote_inbound_action_unknown connection_id={} kind={}",
                action.connection_id,
                action.kind,
            )

    async def _handle_pairing(self, action: RemoteInboundAction) -> None:
        """Consume a ``/start`` deep-link pairing token."""
        from app.core.db import async_session_factory
        from app.remote.pairing import pairing_service

        token = action.pairing_token
        if not token:
            logger.debug(
                "remote_pairing_start_no_token connection_id={}",
                action.connection_id,
            )
            return

        async with async_session_factory() as session:
            result = await pairing_service.consume(
                session,
                token,
                action.principal,
                is_private_chat=True,
                is_bot_sender=False,
            )

        if result is not None:
            logger.info(
                "remote_pairing_success connection_id={} principal_id={}",
                action.connection_id,
                action.principal.principal_id,
            )
            # A silently-persisted pairing is indistinguishable from a
            # failed one from the phone's side — confirm it (spec: "sends
            # Connected to EvoFlux on <device label>"). Never sent on
            # rejection (AC-9: a refusal reveals no connection state).
            if self._adapter is not None:
                await self._adapter.send(
                    RemoteOutboundMessage(
                        connection_id=action.connection_id,
                        destination_id=action.principal.destination_id,
                        text=f"Connected to EvoFlux on {result.label}.",
                        priority=RemoteOutboundPriority.HIGH,
                    )
                )
        else:
            logger.debug(
                "remote_pairing_rejected connection_id={} principal_id={}",
                action.connection_id,
                action.principal.principal_id,
            )

    async def _handle_command(self, action: RemoteInboundAction) -> None:
        """Dispatch a ``/command`` to :class:`~app.remote.actions.RemoteActionService`
        and send its result back.

        Unauthorized (unpaired sender) dispatches are answered with nothing,
        matching every other refusal in this feature — a stranger sending
        ``/help`` to a bot they haven't paired with must not learn anything
        the bot is willing to say to a paired user.
        """
        from app.core.db import async_session_factory

        if self._actions is None:
            return

        async with async_session_factory() as session:
            result = await self._actions.dispatch_command(session, action)

        if result.status == "unauthorized":
            logger.debug(
                "remote_command_unauthorized connection_id={} principal_id={}",
                action.connection_id,
                action.principal.principal_id,
            )
            return

        # ``/actions`` already sends its own message (with buttons) inside
        # RemoteActionService — sending its returned text again here would
        # duplicate it. Every other command relies entirely on this send.
        command = (action.text or "").strip().split(maxsplit=1)[0][1:].lower()
        if command == "actions":
            return

        if result.text and self._adapter is not None:
            await self._adapter.send(
                RemoteOutboundMessage(
                    connection_id=action.connection_id,
                    destination_id=action.principal.destination_id,
                    text=result.text,
                    priority=RemoteOutboundPriority.HIGH,
                )
            )

    async def _handle_text(self, action: RemoteInboundAction) -> None:
        """Submit paired plain text to the inbound service."""
        from app.core.db import async_session_factory
        from app.remote.inbound import RemoteInboundService
        from app.remote.pairing import pairing_service

        # Share the same PairingService instance the routes mint links
        # through and _handle_pairing consumes tokens against — a
        # locally-constructed one would carry its own empty rate-limiter
        # state and diverge from the single source of truth for pairing.
        inbound_service = RemoteInboundService(pairing_service=pairing_service)

        async with async_session_factory() as session:
            result = await inbound_service.handle_text(session, action)

        logger.debug(
            "remote_text_handled connection_id={} status={} session_id={}",
            action.connection_id,
            result.status,
            result.session_id,
        )

        # Register the session with the projection so outbound events are
        # delivered back through Telegram.
        if result.session_id is not None and self._projection is not None:
            self._projection.register_session(
                str(result.session_id),
                connection_id=str(action.connection_id),
                destination_id=action.principal.destination_id,
                tags=frozenset(
                    {"remote_origin", f"remote_connection:{action.connection_id}"}
                ),
            )


remote_runtime = RemoteRuntime()
