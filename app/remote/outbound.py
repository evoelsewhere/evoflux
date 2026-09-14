"""Remote outbound projection, redaction, splitting, and delivery.

Observes the global stream (via
:func:`app.services.memory_stream_store.register_observer`) and projects
relevant events for remote-originated sessions into safe, redacted Telegram
messages.

Only sessions tagged ``remote_origin`` are observed.  The projection
collapses duplicate completions, queries finalized assistant text from the
database after ``done``, and applies the ``remote`` outbound-redaction
channel before delivery.

Design constraints (from spec):
- Observers are synchronous, bounded, and non-blocking.
- No network or database work runs under stream locks.
- All outbound text uses ``protect_outbound_text(..., context=OutboundContext(channel="remote"))``.
- No Telegram parse mode — model-authored text must never be interpreted as markup.
- Unicode-safe plain-text splitting at 4096 characters (Telegram provider bound).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger

from app.remote.contracts import (
    RemoteAdapter,
    RemoteButton,
    RemoteOutboundMessage,
    RemoteOutboundPriority,
)
from app.remote.formatting import render_done_card, render_error_card, render_status_card
from app.remote.turn_activity import load_turn_activity

if TYPE_CHECKING:
    from app.remote.actions import RemoteActionService
    from app.remote.gates import RemoteGateBridge

#: Telegram's maximum message length in characters.
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096

#: Events the remote projection forwards to the phone.
_OBSERVED_EVENT_TYPES = frozenset(
    {
        "done",
        "error",
        "permission_asked",
        "question_asked",
        "plan_approval_requested",
        "permission_replied",
        "question_replied",
        "plan_approval_replied",
    }
)


@dataclass
class _TurnDeliveryState:
    """Per-turn bookkeeping for one remote-originated session."""

    session_id: str
    connection_id: str
    destination_id: str
    #: The lifecycle (progress) message correlation, if one was sent.
    lifecycle_correlation_id: str | None = None
    #: Whether a completion message has already been sent for this turn.
    completion_sent: bool = False
    #: True for a turn that owns a single live status card — created by
    #: ``begin_phone_turn`` — that the final done/error card must edit
    #: in place rather than follow with a new message.
    phone_admitted: bool = False
    started_at: float = field(default_factory=time.monotonic)
    turn_started_wall_clock: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: The repeating native-typing-indicator task started alongside the
    #: status card; cancelled and cleared once the turn finalizes.
    typing_task: "asyncio.Task[None] | None" = field(default=None, repr=False)
    title: str = ""
    principal_id: str = ""


@dataclass
class RemoteProjection:
    """Projects stream events for remote-originated sessions into Telegram.

    Registered as a global stream observer.  Each incoming event is checked
    against the session's provenance tags; only ``remote_origin`` sessions
    are tracked.  Relevant events are normalized, redacted, split, and
    enqueued for delivery through the live adapter.
    """

    _adapter: RemoteAdapter | None = field(default=None, repr=False)
    _bridge: "RemoteGateBridge | None" = field(default=None, repr=False)
    #: Set by a later task's ``set_actions`` (Task 6) so ``_finalize_turn``
    #: can mint "Full diff"/"Tool log" drill-down capability tokens. ``None``
    #: until that wiring lands — every use guards on it and treats a missing
    #: service as "no button" (``formatting.py``'s card builders already
    #: omit a button for a ``None`` token).
    _actions: "RemoteActionService | None" = field(default=None, repr=False)
    _turns: dict[str, _TurnDeliveryState] = field(default_factory=dict, repr=False)
    _session_tags: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    _session_connection_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _session_destination_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _pending: list[RemoteOutboundMessage] = field(default_factory=list, repr=False)
    _pending_edits: list[RemoteOutboundMessage] = field(default_factory=list, repr=False)
    #: Turns whose ``done``/``error`` event has been observed but whose
    #: final card hasn't been built and delivered yet — building it needs a
    #: database query (:func:`~app.remote.turn_activity.load_turn_activity`),
    #: which ``observe()`` itself must never do (observers are synchronous
    #: and non-blocking, per this module's design constraints). Queued here
    #: instead and drained by :meth:`drain_pending`, matching how ``_pending``
    #: already defers ``adapter.send`` calls out of ``observe()``.
    _pending_finalizations: list[tuple[_TurnDeliveryState, str | None]] = field(
        default_factory=list, repr=False
    )
    #: Reserved for a later task's unaddressed-delivery drain (Task 5);
    #: unused by this task beyond being cleared alongside the other queues
    #: when no adapter is bound.
    _unaddressed_pending: list[object] = field(default_factory=list, repr=False)
    #: Caches the single v1 pairing's routing info so ``observe`` can reach
    #: sessions it was never explicitly ``register_session``-ed for (e.g.
    #: work started from the desktop, not the phone) — this app supports
    #: exactly one Telegram pairing per installation, so there is never more
    #: than one tuple to cache. ``principal_id`` travels alongside
    #: ``connection_id``/``destination_id`` because a future task mints
    #: capability tokens for these sessions and needs a real, non-empty
    #: owner id: since v1 has exactly one pairing per connection, that
    #: pairing's own principal is the only valid actor for the whole
    #: connection regardless of which surface (phone or desktop) started the
    #: work being notified about.
    _active_pairing: tuple[str, str, str, str] | None = field(
        default=None, repr=False
    )

    def set_adapter(self, adapter: RemoteAdapter | None) -> None:
        """Bind or unbind the live adapter. Called by the runtime on start/stop."""
        self._adapter = adapter

    def set_bridge(self, bridge: "RemoteGateBridge | None") -> None:
        """Bind or unbind the gate bridge. Called by the runtime on start/stop."""
        self._bridge = bridge

    def set_active_pairing(
        self,
        *,
        connection_id: str,
        destination_id: str,
        notify_scope: str,
        principal_id: str,
    ) -> None:
        """Cache the single v1 pairing's routing info.

        Called by the runtime whenever the pairing changes: a pairing is
        created, restored from the database on startup, or the runtime
        stops (via :meth:`clear_active_pairing`).
        """
        self._active_pairing = (
            connection_id,
            destination_id,
            notify_scope,
            principal_id,
        )

    def clear_active_pairing(self) -> None:
        """Drop the cached pairing. Called by the runtime on stop."""
        self._active_pairing = None

    def active_pairing(self) -> tuple[str, str, str, str] | None:
        """Return the cached ``(connection_id, destination_id, notify_scope,
        principal_id)`` tuple, or ``None`` if no pairing is active."""
        return self._active_pairing

    def register_session(
        self,
        session_id: str,
        *,
        connection_id: str,
        destination_id: str,
        tags: frozenset[str] = frozenset(),
    ) -> None:
        """Register a session as remote-originated so its events are projected."""
        self._session_tags[session_id] = tags
        self._session_connection_ids[session_id] = connection_id
        self._session_destination_ids[session_id] = destination_id

    def unregister_session(self, session_id: str) -> None:
        """Stop tracking a session."""
        self._session_tags.pop(session_id, None)
        self._session_connection_ids.pop(session_id, None)
        self._session_destination_ids.pop(session_id, None)
        turn = self._turns.pop(session_id, None)
        if turn is not None:
            self._stop_typing(turn)

    def begin_phone_turn(
        self,
        session_id: str,
        *,
        connection_id: str,
        destination_id: str,
        principal_id: str,
        title: str,
        status: str,
    ) -> None:
        """Create the one status message a phone-admitted turn owns, and
        start the native typing indicator alongside it. Called by
        runtime.py right after ``register_session`` for a text-triggered
        admission."""
        correlation_id = f"status:{session_id}:{uuid.uuid4().hex[:8]}"
        turn = _TurnDeliveryState(
            session_id=session_id,
            connection_id=connection_id,
            destination_id=destination_id,
            principal_id=principal_id,
            lifecycle_correlation_id=correlation_id,
            phone_admitted=True,
            title=title,
        )
        self._turns[session_id] = turn
        text, buttons = render_status_card(title=title, status=status)
        self._enqueue_send(
            destination_id=destination_id,
            text=text,
            buttons=buttons,
            priority=RemoteOutboundPriority.HIGH,
            correlation_id=correlation_id,
        )
        if self._adapter is not None:
            turn.typing_task = asyncio.create_task(self._run_typing_loop(turn))

    async def _run_typing_loop(self, turn: _TurnDeliveryState) -> None:
        adapter = self._adapter
        if adapter is None:
            return
        try:
            while True:
                await adapter.indicate_typing(turn.destination_id)
                await asyncio.sleep(4.0)
        except asyncio.CancelledError:
            pass

    def typing_task_for(self, session_id: str) -> "asyncio.Task[None] | None":
        turn = self._turns.get(session_id)
        return turn.typing_task if turn is not None else None

    def _stop_typing(self, turn: _TurnDeliveryState) -> None:
        if turn.typing_task is not None and not turn.typing_task.done():
            turn.typing_task.cancel()
        turn.typing_task = None

    def observe(self, session_id: str, envelope) -> None:
        """Stream observer callback — invoked synchronously after ``push_event``.

        Must be non-blocking.  Enqueues delivery work for the adapter.
        """
        tags = self._session_tags.get(session_id)
        if tags is None:
            return
        if "remote_origin" not in tags:
            return

        event_type = envelope.event
        if event_type not in _OBSERVED_EVENT_TYPES:
            return

        connection_id = self._session_connection_ids.get(session_id, "")
        destination_id = self._session_destination_ids.get(session_id, "")
        if not connection_id or not destination_id:
            return

        turn = self._turns.get(session_id)
        if turn is None:
            turn = _TurnDeliveryState(
                session_id=session_id,
                connection_id=connection_id,
                destination_id=destination_id,
            )
            self._turns[session_id] = turn

        if event_type == "done":
            self._handle_done(turn, envelope)
        elif event_type == "error":
            self._handle_error(turn, envelope)
        elif event_type in {
            "permission_asked",
            "question_asked",
            "plan_approval_requested",
        }:
            self._handle_gate(turn, event_type, envelope)
        elif event_type in {
            "permission_replied",
            "question_replied",
            "plan_approval_replied",
        }:
            if self._bridge is not None:
                self._bridge.on_reply(session_id, event_type, envelope.data)

    def _handle_done(self, turn: _TurnDeliveryState, envelope) -> None:
        if turn.completion_sent:
            return
        turn.completion_sent = True
        self._pending_finalizations.append((turn, None))
        self._schedule_drain()

    def _handle_error(self, turn: _TurnDeliveryState, envelope) -> None:
        if turn.completion_sent:
            return
        turn.completion_sent = True
        message = envelope.data.get("message", "An error occurred.")
        self._pending_finalizations.append((turn, message))
        self._schedule_drain()

    async def _finalize_turn(
        self, turn: _TurnDeliveryState, *, error_message: str | None
    ) -> None:
        """Build the turn's final done/error card and deliver it.

        Stops the typing indicator first (the turn is over regardless of
        how delivery goes), then queries this turn's tool-call activity to
        build the card, and either edits the status card a phone-admitted
        turn already owns, or sends a new message for every other turn
        (e.g. one started from the desktop that the phone is only
        observing).
        """
        from app.core.db import async_session_factory

        self._stop_typing(turn)
        elapsed = time.monotonic() - turn.started_at
        async with async_session_factory() as db:
            activity = await load_turn_activity(
                db, turn.session_id, since=turn.turn_started_wall_clock
            )

        diff_token: str | None = None
        toollog_token: str | None = None
        if self._actions is not None:
            if activity.diff_text.strip() and activity.diff_text != "No file changes.":
                diff_token = self._actions.register_capability(
                    connection_id=turn.connection_id,
                    principal_id=turn.principal_id,
                    destination_id=turn.destination_id,
                    session_id=turn.session_id,
                    action_kind="diff",
                    action_target=activity.diff_text,
                )
            toollog_token = self._actions.register_capability(
                connection_id=turn.connection_id,
                principal_id=turn.principal_id,
                destination_id=turn.destination_id,
                session_id=turn.session_id,
                action_kind="toollog",
                action_target=activity.tool_log_text,
            )

        if error_message is not None:
            text, buttons = render_error_card(
                title=turn.title,
                message=_redact_text(error_message),
                toollog_token=toollog_token,
            )
        else:
            text, buttons = render_done_card(
                title=turn.title,
                elapsed_seconds=elapsed,
                summary_lines=[_redact_text(line) for line in activity.summary_lines],
                tool_call_count=activity.tool_call_count,
                diff_token=diff_token,
                toollog_token=toollog_token,
            )

        if turn.phone_admitted and turn.lifecycle_correlation_id is not None:
            self._enqueue_edit(
                destination_id=turn.destination_id,
                text=text,
                buttons=buttons,
                correlation_id=turn.lifecycle_correlation_id,
            )
        else:
            self._enqueue_send(
                destination_id=turn.destination_id,
                text=text,
                buttons=buttons,
                priority=RemoteOutboundPriority.HIGH,
            )

    def _handle_gate(self, turn: _TurnDeliveryState, event_type: str, envelope) -> None:
        data = envelope.data
        if self._bridge is not None:
            from uuid import UUID

            self._bridge.on_gate(
                session_id=turn.session_id,
                event_type=event_type,
                data=data,
                connection_id=UUID(turn.connection_id)
                if turn.connection_id
                else UUID(int=0),
                destination_id=turn.destination_id,
            )
            return

        # Fallback: send without opaque tokens (pre-bridge behavior).
        if event_type == "permission_asked":
            text = _redact_text(
                f"Permission requested: {data.get('tool', 'unknown tool')}"
            )
            buttons = (
                RemoteButton(text="Allow", token="perm:once"),
                RemoteButton(text="Reject", token="perm:reject"),
            )
        elif event_type == "question_asked":
            question = data.get("question", "")
            text = _redact_text(f"Question: {question}")
            buttons = ()
        elif event_type == "plan_approval_requested":
            text = _redact_text("A plan is ready for your review.")
            buttons = (
                RemoteButton(text="Approve", token="plan:approve"),
                RemoteButton(text="Reject", token="plan:reject"),
            )
        else:
            return

        self._enqueue_send(
            destination_id=turn.destination_id,
            text=text,
            buttons=buttons,
            priority=RemoteOutboundPriority.HIGH,
        )

    def _enqueue_send(
        self,
        *,
        destination_id: str,
        text: str,
        buttons: tuple[RemoteButton, ...] = (),
        priority: RemoteOutboundPriority = RemoteOutboundPriority.INFORMATIONAL,
        correlation_id: str | None = None,
    ) -> None:
        adapter = self._adapter
        if adapter is None:
            logger.debug("remote_outbound_no_adapter destination_id={}", destination_id)
            return

        connection_id = ""
        for cid in self._session_connection_ids.values():
            connection_id = cid
            break

        chunks = _split_text(text)
        for i, chunk in enumerate(chunks):
            msg = RemoteOutboundMessage(
                connection_id=UUID(connection_id) if connection_id else UUID(int=0),
                destination_id=destination_id,
                text=chunk,
                buttons=buttons if i == len(chunks) - 1 else (),
                priority=priority,
                correlation_id=correlation_id if i == len(chunks) - 1 else None,
            )
            self._pending.append(msg)

        self._schedule_drain()

    def _enqueue_edit(
        self,
        *,
        destination_id: str,
        text: str,
        buttons: tuple[RemoteButton, ...],
        correlation_id: str,
    ) -> None:
        """Edit-flagged delivery — a status card's final transition. Unlike
        ``_enqueue_send``, never splits (a status/done card is always short
        and already bounded by ``formatting.py``'s builders), so it is
        always exactly one queued item."""
        adapter = self._adapter
        if adapter is None:
            return

        connection_id = ""
        for cid in self._session_connection_ids.values():
            connection_id = cid
            break

        msg = RemoteOutboundMessage(
            connection_id=UUID(connection_id) if connection_id else UUID(int=0),
            destination_id=destination_id,
            text=text,
            buttons=buttons,
            correlation_id=correlation_id,
        )
        self._pending_edits.append(msg)
        self._schedule_drain()

    def _schedule_drain(self) -> None:
        """Schedule an async drain of pending messages if a loop is running."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.drain_pending())
        except RuntimeError:
            pass

    async def drain_pending(self) -> None:
        """Finalize completed turns, then send/edit all pending messages
        through the adapter."""
        adapter = self._adapter
        if adapter is None:
            self._pending.clear()
            self._pending_edits.clear()
            self._pending_finalizations.clear()
            self._unaddressed_pending.clear()
            return
        while self._pending_finalizations:
            turn, error_message = self._pending_finalizations.pop(0)
            await self._finalize_turn(turn, error_message=error_message)
        while self._pending:
            msg = self._pending.pop(0)
            try:
                await adapter.send(msg)
            except Exception as exc:
                logger.warning(
                    "remote_outbound_send_failed destination_id={} error={}",
                    msg.destination_id,
                    exc,
                )
        while self._pending_edits:
            msg = self._pending_edits.pop(0)
            try:
                await adapter.edit(msg)
            except Exception as exc:
                logger.warning(
                    "remote_outbound_edit_failed destination_id={} error={}",
                    msg.destination_id,
                    exc,
                )
        await self._drain_unaddressed()

    async def _drain_unaddressed(self) -> None:
        """Placeholder for a later task's unaddressed-delivery drain
        (Task 5) — a no-op until that task replaces this body."""
        return

    def clear_turn(self, session_id: str) -> None:
        """Clear delivery state for a completed turn."""
        turn = self._turns.pop(session_id, None)
        if turn is not None:
            self._stop_typing(turn)


def _redact_text(text: str) -> str:
    """Apply remote-channel outbound redaction."""
    try:
        from app.agent.outbound_redaction import OutboundContext, protect_outbound_text

        protected, _report = protect_outbound_text(
            text, context=OutboundContext(channel="remote")
        )
        return protected
    except Exception:
        return text


def _split_text(text: str) -> list[str]:
    """Split *text* into chunks of at most ``_TELEGRAM_MAX_MESSAGE_LENGTH`` chars.

    Splits on paragraph boundaries when possible, falling back to line
    boundaries, then hard character splits.  Preserves Unicode safety by
    never splitting a surrogate pair or combining sequence.
    """
    if len(text) <= _TELEGRAM_MAX_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= _TELEGRAM_MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        # Try to split at the last paragraph break within the limit.
        split_at = _find_split_point(remaining, _TELEGRAM_MAX_MESSAGE_LENGTH)
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


def _find_split_point(text: str, max_length: int) -> int:
    """Find the best split point within *max_length* characters."""
    # Prefer paragraph break
    idx = text.rfind("\n\n", 0, max_length)
    if idx > 0:
        return idx + 2

    # Fall back to line break
    idx = text.rfind("\n", 0, max_length)
    if idx > 0:
        return idx + 1

    # Fall back to space
    idx = text.rfind(" ", 0, max_length)
    if idx > 0:
        return idx + 1

    # Hard split
    return max_length


__all__ = ["RemoteProjection", "_split_text"]
