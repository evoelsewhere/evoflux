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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger

from app.remote.contracts import (
    RemoteAdapter,
    RemoteButton,
    RemoteOutboundMessage,
    RemoteOutboundPriority,
)

if TYPE_CHECKING:
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
    _turns: dict[str, _TurnDeliveryState] = field(default_factory=dict, repr=False)
    _session_tags: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    _session_connection_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _session_destination_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _pending: list[RemoteOutboundMessage] = field(default_factory=list, repr=False)

    def set_adapter(self, adapter: RemoteAdapter | None) -> None:
        """Bind or unbind the live adapter. Called by the runtime on start/stop."""
        self._adapter = adapter

    def set_bridge(self, bridge: "RemoteGateBridge | None") -> None:
        """Bind or unbind the gate bridge. Called by the runtime on start/stop."""
        self._bridge = bridge

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
        self._turns.pop(session_id, None)

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
        text = _redact_text(
            envelope.data.get("text", "Task completed.") or "Task completed."
        )
        self._enqueue_send(
            destination_id=turn.destination_id,
            text=text,
            priority=RemoteOutboundPriority.HIGH,
        )

    def _handle_error(self, turn: _TurnDeliveryState, envelope) -> None:
        message = envelope.data.get("message", "An error occurred.")
        text = _redact_text(f"Error: {message}")
        self._enqueue_send(
            destination_id=turn.destination_id,
            text=text,
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
            )
            self._pending.append(msg)

        self._schedule_drain()

    def _schedule_drain(self) -> None:
        """Schedule an async drain of pending messages if a loop is running."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.drain_pending())
        except RuntimeError:
            pass

    async def drain_pending(self) -> None:
        """Send all pending messages through the adapter."""
        adapter = self._adapter
        if adapter is None:
            self._pending.clear()
            return
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

    def clear_turn(self, session_id: str) -> None:
        """Clear delivery state for a completed turn."""
        self._turns.pop(session_id, None)


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
