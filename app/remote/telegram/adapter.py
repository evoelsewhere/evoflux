"""Telegram adapter lifecycle: long-poll ownership, offset bookkeeping, and
Telegram error-taxonomy -> connection-state translation.

Modeled on ``app/conductor/service.py``'s ``start``/``stop`` shape (read for
pattern inspiration only — never imported from, never modified): one owner
``asyncio.Task`` runs the poll loop, and an ``asyncio.Event`` makes both the
long poll and any backoff/rate-limit sleep interruptible so ``stop()`` never
waits out the configured poll timeout or a retry delay (AC-13). Genuine
promptness during an in-flight long-poll HTTP call additionally requires
cancelling the task itself (setting an event cannot interrupt an httpx
request that isn't awaiting that event) — again mirroring conductor's
``stop()``.

This module owns Bot API error classification (AC-12): webhook conflicts are
cleared once and retried immediately; a concurrent ``getUpdates`` consumer is
``used_elsewhere`` with bounded backoff; an invalid/revoked token is terminal
for the current ``start()`` call; ``429`` honors ``retry_after`` verbatim;
transport/5xx failures use exponential backoff with jitter; and an
unreachable paired chat only affects delivery status (``phone_reachable``),
never the inbound poll loop — inbound polling and outbound delivery are
independent failure domains.
"""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

import httpx
from loguru import logger

from app.remote.contracts import (
    RemoteAdapterStatus,
    RemoteConnectionState,
    RemoteErrorClass,
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemoteOutboundMessage,
    RemotePrincipal,
)
from app.remote.telegram.client import (
    TelegramApiError,
    TelegramClient,
    TelegramMalformedResponseError,
    TelegramTransportError,
)
from app.remote.telegram.models import TelegramUpdate

#: Invoked for every classified inbound action (text, callback, or pairing
#: start). The adapter advances its offset past an update only after this
#: awaitable completes without raising — see ``_dispatch``. Its return value
#: is not interpreted by the adapter; a later task (interactive ingress
#: integration) may attach meaning to it.
RemoteActionHandler = Callable[[RemoteInboundAction], Awaitable[object]]

#: ``jitter(low, high)`` -> a float in that range. Defaults to
#: ``random.uniform``; tests inject a deterministic function.
JitterFn = Callable[[float, float], float]

#: Injectable clock for ``last_successful_poll_at``.
ClockFn = Callable[[], datetime]

DEFAULT_POLL_TIMEOUT_SECONDS = 50
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_MAX_SECONDS = 60.0
DEFAULT_RATE_LIMIT_FALLBACK_SECONDS = 1

#: Bound on how many un-acknowledged callback tokens the adapter remembers
#: (opaque callback token -> raw Telegram callback_query id) so a burst of
#: unanswered callbacks cannot grow this mapping unboundedly. Ephemeral by
#: design, like every other in-memory interaction token (spec: "Remote
#: interaction contract").
MAX_PENDING_CALLBACK_IDS = 512


def _default_clock() -> datetime:
    return datetime.now(UTC)


class TelegramAdapter:
    """Owns Telegram long-polling lifecycle and Bot API delivery for one
    remote connection.

    Constructed from a bot token (never persisted here — the OS vault and
    connection record are a different layer's job) and an ``on_action``
    callback that receives every normalized inbound action.
    """

    def __init__(
        self,
        *,
        connection_id: UUID,
        token: str,
        on_action: RemoteActionHandler,
        http_client: httpx.AsyncClient | None = None,
        poll_timeout_seconds: int = DEFAULT_POLL_TIMEOUT_SECONDS,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
        jitter: JitterFn = random.uniform,
        clock: ClockFn = _default_clock,
    ) -> None:
        self._connection_id = connection_id
        self._client = TelegramClient(token, http_client=http_client)
        self._on_action = on_action
        self._poll_timeout_seconds = poll_timeout_seconds
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._jitter = jitter
        self._clock = clock

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self._state = RemoteConnectionState.DISABLED
        self._last_error_class = RemoteErrorClass.NONE
        self._last_successful_poll_at: datetime | None = None
        self._phone_reachable: bool | None = None

        #: correlation_id -> (chat_id, message_id), so ``edit()`` can find
        #: the message it was asked to update. Ephemeral by design (spec:
        #: "progress-message IDs ... are deliberately ephemeral").
        self._sent_messages: dict[str, tuple[int, int]] = {}
        #: opaque callback token -> raw Telegram callback_query id.
        self._pending_callback_ids: OrderedDict[str, str] = OrderedDict()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start polling. Safe to call repeatedly while already running."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._state = RemoteConnectionState.STARTING
        self._task = asyncio.create_task(
            self._run(), name=f"telegram-poll-{self._connection_id}"
        )

    async def stop(self) -> None:
        """Stop polling promptly and close the HTTP client. Safe to call
        repeatedly, including before ``start()`` was ever called.

        Setting the stop event resolves an in-progress backoff/rate-limit
        sleep instantly; cancelling the task is additionally required to
        interrupt a genuinely in-flight long-poll HTTP call, which is not
        awaiting that event.
        """
        self._stop_event.set()
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._client.aclose()
        self._state = RemoteConnectionState.DISABLED

    def status(self) -> RemoteAdapterStatus:
        """Safe, diagnosable runtime status (AC-34).

        ``phone_unreachable`` is reported as an overlay on top of an
        otherwise-healthy ``polling`` state — a delivery failure never
        overrides a *worse* poll-loop state (backoff, used_elsewhere,
        invalid_token, ...), matching "inbound polling and outbound
        delivery are independent failure domains" while still using one
        connection-state enum for display.
        """
        state = self._state
        if state == RemoteConnectionState.POLLING and self._phone_reachable is False:
            state = RemoteConnectionState.PHONE_UNREACHABLE
        return RemoteAdapterStatus(
            connection_id=self._connection_id,
            state=state,
            last_error_class=self._last_error_class,
            last_successful_poll_at=self._last_successful_poll_at,
            phone_reachable=self._phone_reachable,
        )

    # ------------------------------------------------------------------
    # Outbound delivery
    # ------------------------------------------------------------------

    async def send(self, message: RemoteOutboundMessage) -> None:
        try:
            sent = await self._client.send_text(
                chat_id=message.destination_id,
                text=message.text,
                buttons=message.buttons,
            )
        except TelegramApiError as exc:
            self._record_delivery_failure(exc)
            raise
        self._record_delivery_success()
        if message.correlation_id is not None:
            self._sent_messages[message.correlation_id] = (
                sent.chat.id,
                sent.message_id,
            )

    async def edit(self, message: RemoteOutboundMessage) -> None:
        target = (
            self._sent_messages.get(message.correlation_id)
            if message.correlation_id is not None
            else None
        )
        if target is None:
            # Nothing recorded to edit (e.g. after a restart — progress
            # message IDs are ephemeral by design). Not this adapter's call
            # whether that matters; it simply has nothing to correct.
            return
        chat_id, message_id = target
        try:
            await self._client.edit_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message.text,
                buttons=message.buttons,
            )
        except TelegramApiError as exc:
            self._record_delivery_failure(exc)
            raise
        self._record_delivery_success()

    async def answer_callback(self, callback_token: str) -> None:
        raw_id = self._pending_callback_ids.pop(callback_token, None)
        if raw_id is None:
            # Expired/unknown token (e.g. after a restart) — nothing to
            # acknowledge at the transport level. Not an error: the caller
            # (a later task) is responsible for telling the user their
            # action expired.
            return
        try:
            await self._client.answer_callback(raw_id)
        except TelegramApiError as exc:
            self._record_delivery_failure(exc)
            raise
        self._record_delivery_success()

    async def indicate_typing(self, destination_id: str) -> None:
        """Best-effort liveliness signal (AC-38): a native "still typing"
        indicator while a turn is unresolved. Never fails the caller — this
        is decoration, not a delivery guarantee, so it must never surface an
        error the way ``send``/``edit``/``answer_callback`` do."""
        try:
            await self._client.send_chat_action(chat_id=destination_id)
        except (
            TelegramApiError,
            TelegramTransportError,
            TelegramMalformedResponseError,
        ):
            pass

    def _record_delivery_failure(self, exc: TelegramApiError) -> None:
        if exc.error_code == 403:
            self._phone_reachable = False
            self._last_error_class = RemoteErrorClass.PHONE_UNREACHABLE

    def _record_delivery_success(self) -> None:
        self._phone_reachable = True
        if self._last_error_class == RemoteErrorClass.PHONE_UNREACHABLE:
            self._last_error_class = RemoteErrorClass.NONE

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        try:
            if not await self._ensure_webhook_deleted():
                return
            await self._register_commands()
            self._state = RemoteConnectionState.POLLING
            offset: int | None = None
            attempt = 0
            while not self._stop_event.is_set():
                try:
                    updates = await self._client.get_updates(
                        offset=offset, timeout=self._poll_timeout_seconds
                    )
                except TelegramApiError as exc:
                    outcome = await self._handle_get_updates_error(exc, attempt)
                    if outcome is None:
                        return
                    attempt = outcome
                    continue
                except (TelegramTransportError, TelegramMalformedResponseError):
                    attempt += 1
                    self._state = RemoteConnectionState.BACKOFF
                    self._last_error_class = RemoteErrorClass.TRANSPORT
                    await self._interruptible_backoff(attempt)
                    continue

                attempt = 0
                self._state = RemoteConnectionState.POLLING
                self._last_error_class = RemoteErrorClass.NONE
                self._last_successful_poll_at = self._clock()
                offset = await self._dispatch(updates, offset)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state = RemoteConnectionState.ERROR
            self._last_error_class = RemoteErrorClass.UNKNOWN
            logger.error(
                "telegram_adapter_poll_loop_crashed connection_id={}",
                self._connection_id,
            )

    async def _register_commands(self) -> None:
        """Advertise the slash-command set as Telegram's native "/" menu.

        Best-effort: a paired user can still type any command by hand, so a
        failure here must never block the poll loop from starting.
        """
        commands = [
            ("help", "Show available commands"),
            ("status", "Show connection and current task status"),
            ("new", "Start a new task"),
            ("stop", "Stop the current running task"),
            ("unpair", "Unpair this phone from EvoFlux"),
            ("actions", "Show more actions (Workflows, Projects, Scheduler)"),
        ]
        try:
            await self._client.set_commands(commands)
        except (TelegramApiError, TelegramTransportError, TelegramMalformedResponseError):
            logger.warning(
                "remote_set_commands_failed connection_id={}", self._connection_id
            )

    async def _ensure_webhook_deleted(self) -> bool:
        """AC-11: remove any webhook and drop pending updates once, before
        the first ``getUpdates`` call. Retries through transport/unknown-API
        failures; an invalid token here is terminal, same as in the main
        loop."""
        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._client.delete_webhook(drop_pending_updates=True)
                return True
            except TelegramApiError as exc:
                if exc.error_code == 401:
                    self._state = RemoteConnectionState.INVALID_TOKEN
                    self._last_error_class = RemoteErrorClass.INVALID_TOKEN
                    return False
                attempt += 1
                self._state = RemoteConnectionState.BACKOFF
                self._last_error_class = RemoteErrorClass.UNKNOWN
                await self._interruptible_backoff(attempt)
            except (TelegramTransportError, TelegramMalformedResponseError):
                attempt += 1
                self._state = RemoteConnectionState.BACKOFF
                self._last_error_class = RemoteErrorClass.TRANSPORT
                await self._interruptible_backoff(attempt)
        return False

    async def _handle_get_updates_error(
        self, exc: TelegramApiError, attempt: int
    ) -> int | None:
        """Returns the next ``attempt`` count, or ``None`` if the caller
        should stop polling entirely (invalid token)."""
        if exc.error_code == 401:
            self._state = RemoteConnectionState.INVALID_TOKEN
            self._last_error_class = RemoteErrorClass.INVALID_TOKEN
            return None

        if exc.error_code == 409:
            description = (exc.description or "").lower()
            if "webhook" in description:
                # Cleared once, then retried immediately — not a backoff
                # state (spec: "Webhook conflict is cleared once").
                try:
                    await self._client.delete_webhook(drop_pending_updates=True)
                except (
                    TelegramApiError,
                    TelegramTransportError,
                    TelegramMalformedResponseError,
                ):
                    pass
                return 0
            # A concurrent getUpdates consumer — bounded backoff, never a
            # tight retry loop.
            self._state = RemoteConnectionState.USED_ELSEWHERE
            self._last_error_class = RemoteErrorClass.USED_ELSEWHERE
            new_attempt = attempt + 1
            await self._interruptible_backoff(new_attempt)
            return new_attempt

        if exc.error_code == 429:
            self._state = RemoteConnectionState.RATE_LIMITED
            self._last_error_class = RemoteErrorClass.RATE_LIMITED
            retry_after = (
                exc.retry_after
                if exc.retry_after is not None
                else DEFAULT_RATE_LIMIT_FALLBACK_SECONDS
            )
            # Honor Telegram's retry_after verbatim — not our own schedule.
            await self._interruptible_sleep(float(retry_after))
            return attempt

        # Unknown API error: generic bounded exponential backoff.
        self._state = RemoteConnectionState.BACKOFF
        self._last_error_class = RemoteErrorClass.UNKNOWN
        new_attempt = attempt + 1
        await self._interruptible_backoff(new_attempt)
        return new_attempt

    async def _dispatch(
        self, updates: Sequence[TelegramUpdate], offset: int | None
    ) -> int | None:
        """Process *updates* in update-ID order. Classification is
        sequential to preserve offset ordering (spec: "Concurrency, failure,
        recovery, and idempotency"). The offset advances past an update only
        once it has been safely classified and, for a dispatched action,
        once ``on_action`` has completed without raising — a handler failure
        stops this batch so the failed update is retried on the next poll
        rather than silently skipped."""
        for update in sorted(updates, key=lambda item: item.update_id):
            action = self._classify(update)
            if action is not None:
                try:
                    await self._on_action(action)
                except Exception:
                    logger.warning(
                        "telegram_inbound_action_handler_failed "
                        "connection_id={} update_id={}",
                        self._connection_id,
                        update.update_id,
                    )
                    return offset
            offset = update.update_id + 1
        return offset

    def _classify(self, update: TelegramUpdate) -> RemoteInboundAction | None:
        source_key = f"telegram:{self._connection_id}:{update.update_id}"

        callback_query = update.callback_query
        if callback_query is not None:
            if not callback_query.data:
                return None
            self._remember_callback(callback_query.data, callback_query.id)
            chat_id = (
                callback_query.message.chat.id
                if callback_query.message is not None
                else callback_query.from_user.id
            )
            principal = RemotePrincipal(
                connection_id=self._connection_id,
                principal_id=str(callback_query.from_user.id),
                destination_id=str(chat_id),
                display=(
                    callback_query.from_user.username
                    or callback_query.from_user.first_name
                    or ""
                ),
            )
            return RemoteInboundAction(
                connection_id=self._connection_id,
                kind=RemoteInboundActionKind.CALLBACK,
                principal=principal,
                source_key=source_key,
                callback_token=callback_query.data,
            )

        message = update.message
        if message is None or message.text is None:
            return None  # media/service message — unsupported, ignored
        if message.chat.type != "private":
            return None  # group/channel — never addressable
        if message.from_user is None or message.from_user.is_bot:
            return None  # bot-authored or unattributable — ignored

        principal = RemotePrincipal(
            connection_id=self._connection_id,
            principal_id=str(message.from_user.id),
            destination_id=str(message.chat.id),
            display=message.from_user.username or message.from_user.first_name or "",
        )
        text = message.text
        if text == "/start" or text.startswith("/start "):
            payload = text[len("/start ") :].strip() if " " in text else ""
            return RemoteInboundAction(
                connection_id=self._connection_id,
                kind=RemoteInboundActionKind.PAIRING_START,
                principal=principal,
                source_key=source_key,
                pairing_token=payload or None,
            )
        return RemoteInboundAction(
            connection_id=self._connection_id,
            kind=RemoteInboundActionKind.TEXT,
            principal=principal,
            source_key=source_key,
            text=text,
        )

    def _remember_callback(self, token: str, raw_callback_query_id: str) -> None:
        self._pending_callback_ids[token] = raw_callback_query_id
        self._pending_callback_ids.move_to_end(token)
        while len(self._pending_callback_ids) > MAX_PENDING_CALLBACK_IDS:
            self._pending_callback_ids.popitem(last=False)

    # ------------------------------------------------------------------
    # Interruptible waits
    # ------------------------------------------------------------------

    async def _interruptible_backoff(self, attempt: int) -> None:
        cap = min(
            self._backoff_max_seconds,
            self._backoff_base_seconds * (2 ** (attempt - 1)),
        )
        delay = self._jitter(0.0, cap) if cap > 0 else 0.0
        await self._interruptible_sleep(delay)

    async def _interruptible_sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=max(0.0, seconds))
        except TimeoutError:
            pass


__all__ = [
    "DEFAULT_BACKOFF_BASE_SECONDS",
    "DEFAULT_BACKOFF_MAX_SECONDS",
    "DEFAULT_POLL_TIMEOUT_SECONDS",
    "MAX_PENDING_CALLBACK_IDS",
    "RemoteActionHandler",
    "TelegramAdapter",
]
