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
from collections import OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlparse
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
MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024

#: Bound on how many sent message ids ``clear_history`` remembers per
#: destination, so a long-running connection's history for one chat
#: cannot grow unboundedly. Telegram itself only allows a bot to delete
#: its own messages within 48 hours anyway, so remembering far more than
#: this would rarely help.
MAX_TRACKED_MESSAGES_PER_DESTINATION = 200


def _default_clock() -> datetime:
    return datetime.now(UTC)


class TelegramAdapter:
    """Owns Telegram long-polling lifecycle and Bot API delivery for one
    remote connection.

    Constructed from a bot token (never persisted here — the OS vault and
    connection record are a different layer's job) and an ``on_action``
    callback that receives every normalized inbound action.
    """

    # Terminal cards stay consolidated into the live process message. Telegram
    # edits are intentionally treated as the canonical completion transition;
    # callers must not emit a duplicate terminal message.
    edit_notifies_user = True

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
        self.streaming_provider: str | None = None
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
        #: destination_id -> the most recent message ids this bot sent
        #: there, for ``clear_history``. Bounded per destination
        #: (MAX_TRACKED_MESSAGES_PER_DESTINATION); ephemeral, like every
        #: other in-memory tracking this adapter keeps.
        self._message_history: dict[str, deque[int]] = defaultdict(
            lambda: deque(maxlen=MAX_TRACKED_MESSAGES_PER_DESTINATION)
        )

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
        for attachment in message.attachments:
            parsed = urlparse(attachment.url)
            if parsed.scheme != "https" or not parsed.netloc:
                logger.warning(
                    "telegram_attachment_rejected reason=invalid_url destination_id={}",
                    message.destination_id,
                )
                continue
            if attachment.mime_type and not attachment.mime_type.startswith("image/"):
                logger.warning(
                    "telegram_attachment_rejected reason=unsupported_mime destination_id={}",
                    message.destination_id,
                )
                continue
            if attachment.size_bytes is not None and (
                attachment.size_bytes < 0
                or attachment.size_bytes > MAX_PHOTO_SIZE_BYTES
            ):
                logger.warning(
                    "telegram_attachment_rejected reason=size_limit destination_id={}",
                    message.destination_id,
                )
                continue
            try:
                photo = await self._client.send_photo(
                    chat_id=message.destination_id,
                    photo=attachment.url,
                )
                self._message_history[message.destination_id].append(photo.message_id)
            except TelegramApiError as exc:
                self._record_delivery_failure(exc)
                logger.warning(
                    "telegram_attachment_failed destination_id={} error={}",
                    message.destination_id,
                    exc,
                )
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
        self._message_history[message.destination_id].append(sent.message_id)

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

    async def send_draft(
        self, *, destination_id: str, draft_id: int, text: str
    ) -> None:
        """Send an ephemeral partial response for private-draft providers."""
        try:
            await self._client.send_message_draft(
                chat_id=destination_id,
                draft_id=draft_id,
                text=text,
            )
        except TelegramApiError as exc:
            self._record_delivery_failure(exc)
            raise
        self._record_delivery_success()

    async def clear_history(self, destination_id: str) -> int:
        """Delete every message this bot remembers sending to
        *destination_id* (bounded to the most recent
        ``MAX_TRACKED_MESSAGES_PER_DESTINATION`` — see ``_message_history``).

        Telegram only lets a bot delete its own messages, and only within
        48 hours (docs: "Message can only be deleted if it was sent less
        than 48 hours ago"); a message outside that window (or already
        deleted) is skipped rather than aborting the whole clear — this is
        best-effort tidying, not a guarantee. Not this adapter's job to
        chase down messages it never sent: the user's own messages in a
        private chat cannot be deleted by the bot at all.
        """
        message_ids = list(self._message_history.pop(destination_id, ()))
        cleared = 0
        for message_id in message_ids:
            try:
                await self._client.delete_message(
                    chat_id=destination_id, message_id=message_id
                )
            except (
                TelegramApiError,
                TelegramTransportError,
                TelegramMalformedResponseError,
            ):
                logger.debug(
                    "telegram_delete_message_failed destination_id={} message_id={}",
                    destination_id,
                    message_id,
                )
                continue
            cleared += 1
        return cleared

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
            if exc.error_code == 400:
                # Expired or invalid callback query — Telegram requires
                # answering within 10 seconds; after a server restart or
                # network delay the query is stale.  Log and continue so
                # the actual action (session switch, summarize, etc.) still
                # executes instead of being killed by the transport error.
                logger.debug(
                    "remote_answer_callback_expired error={}",
                    exc,
                )
                self._record_delivery_failure(exc)
                return
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
            # Debug, not warning: this fires repeatedly per turn, so
            # warning-level logging here would be spam rather than a
            # signal (contrast _register_commands, a one-shot startup
            # call where a warning is appropriate).
            logger.debug(
                "telegram_indicate_typing_failed connection_id={}",
                self._connection_id,
            )

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

        ``clear``, ``history``, ``skills``, ``skill``, ``steer``,
        ``switch``, ``delete``, and ``agent`` are deliberate additions
        beyond the control-surface spec's original AC-58 bounded set (9
        commands) — requested directly by users testing this feature
        live, after that set was first implemented.  ``/pair`` was
        removed: ``/start <code>`` now handles code-based pairing.
        """
        commands = [
            ("help", "What can I do here?"),
            ("status", "What's my agent doing right now?"),
            ("new", "Set aside this task, start a new one"),
            ("stop", "Interrupt the agent mid-task"),
            ("settings", "Change mode, model, agent, or thinking level"),
            ("health", "Check system health"),
            ("history", "Browse recent chat sessions"),
            ("changes", "See this task's file changes"),
            ("clear", "Delete my recent messages here"),
            ("actions", "Run a workflow, project, or schedule"),
            ("skills", "Browse available skills"),
            ("skill", "Load a skill by name"),
            ("steer", "Redirect the agent mid-task"),
            ("switch", "Switch to another session"),
            ("delete", "Delete unused sessions"),
            ("agent", "Show agent info and model"),
            ("unpair", "Disconnect this phone"),
        ]
        try:
            await self._client.set_commands(commands)
        except (
            TelegramApiError,
            TelegramTransportError,
            TelegramMalformedResponseError,
        ):
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
                action = await self._materialize_media(action, update)
                try:
                    await self._on_action(action)
                except Exception:
                    logger.exception(
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
        if message is None:
            return None
        text = message.text or message.caption
        if text is None and message.photo:
            largest = message.photo[-1]
            text = (
                f"[Image attached: {largest.width}×{largest.height}; "
                f"file_id={largest.file_id}]"
            )
        elif text is None and message.document is not None:
            document = message.document
            name = document.file_name or "unnamed file"
            details = document.mime_type or "unknown type"
            text = f"[File attached: {name}; {details}; file_id={document.file_id}]"
        if text is None:
            return None  # unsupported service message
        text = str(text)
        normalized_text = text
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
        text = normalized_text
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

    async def _materialize_media(
        self, action: RemoteInboundAction, update: TelegramUpdate
    ) -> RemoteInboundAction:
        """Download media from Telegram and attach it to the inbound action.

        Files are bounded to 10 MiB. Download failures are swallowed with a
        log; the text fallback (caption or descriptive placeholder) is kept.
        """
        from app.remote.contracts import RemoteInboundAttachment

        message = update.message
        if message is None or action.kind != RemoteInboundActionKind.TEXT:
            return action

        attachments: list[RemoteInboundAttachment] = []

        # Photo — always use the largest resolution.
        if message.photo:
            largest = message.photo[-1]
            try:
                content = await self._client.download_file(largest.file_id)
                attachments.append(
                    RemoteInboundAttachment(
                        content=content,
                        filename=f"photo_{largest.file_id[:12]}.jpg",
                        mime_type="image/jpeg",
                    )
                )
            except Exception:
                logger.debug(
                    "telegram_photo_download_failed file_id={}",
                    largest.file_id,
                )

        # Document — download by file_id.
        if message.document is not None:
            document = message.document
            try:
                content = await self._client.download_file(document.file_id)
                filename = document.file_name or f"document_{document.file_id[:12]}"
                attachments.append(
                    RemoteInboundAttachment(
                        content=content,
                        filename=filename,
                        mime_type=document.mime_type,
                    )
                )
            except Exception:
                logger.debug(
                    "telegram_document_download_failed file_id={}",
                    document.file_id,
                )

        if not attachments:
            return action
        return replace(action, attachments=tuple(attachments))

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
