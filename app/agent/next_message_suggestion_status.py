"""Publish next-message suggestions through the shared team stream."""

from __future__ import annotations

from app.agent.schemas.events import NextMessageSuggestionEvent
from app.services import memory_stream_store as stream_store
from app.services.stream_envelope import StreamEnvelope


async def publish_next_message_suggestion(
    session_id: str,
    message: str,
    reason: str = "",
) -> None:
    """Show ``message`` as ghost text in the user's chat composer.

    The event is ephemeral by design (``memory_stream_store`` never replays
    it): the suggestion is per-turn UI state, not a transcript fact, so a
    client that reconnects must not be offered a stale next message.
    """

    await stream_store.push_event(
        session_id,
        StreamEnvelope.from_event(
            NextMessageSuggestionEvent(
                session_id=session_id,
                message=message,
                reason=reason,
            )
        ),
    )
