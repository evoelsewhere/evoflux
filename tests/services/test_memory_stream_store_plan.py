"""Pending plan-approval accumulator + reconnect replay in the stream store."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent.schemas.events import (
    PlanApprovalRepliedEvent,
    PlanApprovalRequestedEvent,
)
from app.services import memory_stream_store as mss
from app.services.stream_envelope import StreamEnvelope


@pytest.fixture
async def session():
    session_id = "plan-store-sess"
    await mss.init_turn(session_id)
    yield session_id
    await mss.clear(session_id)


def _requested_envelope(session_id: str) -> StreamEnvelope:
    return StreamEnvelope.from_event(
        PlanApprovalRequestedEvent(
            request_id="req-1",
            session_id=session_id,
            plan="# The plan",
            steps=[{"tool": "edit", "args": {}, "summary": "edit x"}],
        )
    )


async def _replay_events(session_id: str, *, budget: int = 30) -> list[dict]:
    """Collect replayed events from attach() until the live-drain phase."""
    events: list[dict] = []
    gen = mss.attach(session_id)
    try:
        for _ in range(budget):
            try:
                wire = await asyncio.wait_for(gen.__anext__(), timeout=0.1)
            except (TimeoutError, asyncio.TimeoutError, StopAsyncIteration):
                break
            events.append(wire)
    finally:
        await gen.aclose()
    return events


async def test_pending_plan_is_replayed_on_reconnect(session: str):
    await mss.push_event(session, _requested_envelope(session))

    events = await _replay_events(session)
    plan_events = [e for e in events if e.get("event") == "plan_approval_requested"]

    assert len(plan_events) == 1
    data = json.loads(plan_events[0]["data"])
    assert data["request_id"] == "req-1"
    assert data["plan"] == "# The plan"
    assert data["steps"][0]["tool"] == "edit"


async def test_replied_clears_pending_plan(session: str):
    await mss.push_event(session, _requested_envelope(session))
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            PlanApprovalRepliedEvent(
                request_id="req-1", session_id=session, decision="approved"
            )
        ),
    )

    events = await _replay_events(session)
    assert not [e for e in events if e.get("event") == "plan_approval_requested"]
