"""Publish parked-suggestion state through the shared team stream."""

from __future__ import annotations

from app.agent.schemas.events import SuggestedTaskEvent
from app.services import memory_stream_store as stream_store
from app.services.stream_envelope import StreamEnvelope
from app.services.suggested_task_service import SuggestedTaskSnapshot


async def publish_suggested_task(
    session_id: str,
    task: SuggestedTaskSnapshot,
    *,
    source: str,
) -> None:
    """Push one chip's current state to the session's stream.

    Takes a snapshot rather than the ORM row: every caller publishes after
    committing, where the row is expired and reading an attribute off it
    would go back to a closed session.
    """

    await stream_store.push_event(
        session_id,
        StreamEnvelope.from_event(
            SuggestedTaskEvent(
                session_id=session_id,
                task=task.model_dump(mode="json"),
                metadata={"source": source},
            )
        ),
    )
