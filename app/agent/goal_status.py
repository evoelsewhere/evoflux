"""Publish durable Goal state through the shared team stream."""

from __future__ import annotations

from app.agent.schemas.events import GoalStatusEvent
from app.models.goal import SessionGoal
from app.services import goal_service
from app.services import memory_stream_store as stream_store
from app.services.stream_envelope import StreamEnvelope


async def publish_goal_status(
    session_id: str,
    goal: SessionGoal | None,
    *,
    source: str,
) -> None:
    payload = (
        goal_service.snapshot(goal).model_dump(mode="json")
        if goal is not None
        else None
    )
    await stream_store.push_event(
        session_id,
        StreamEnvelope.from_event(
            GoalStatusEvent(
                session_id=session_id,
                goal=payload,
                metadata={"source": source},
            )
        ),
    )
