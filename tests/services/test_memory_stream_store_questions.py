"""Pending ask-user / permission accumulator + reconnect replay."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent.schemas.events import (
    PermissionAskedEvent,
    PermissionRepliedEvent,
    QuestionAskedEvent,
    QuestionRepliedEvent,
)
from app.services import memory_stream_store as mss
from app.services.stream_envelope import StreamEnvelope


@pytest.fixture
async def session():
    session_id = "ask-store-sess"
    await mss.init_turn(session_id)
    yield session_id
    await mss.clear(session_id)


async def _replay_events(session_id: str, *, budget: int = 30) -> list[dict]:
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


async def test_pending_question_is_replayed_on_reconnect(session: str):
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            QuestionAskedEvent(
                request_id="q-1",
                session_id=session,
                questions=[{"question": "Continue?", "options": ["yes", "no"]}],
            )
        ),
    )

    events = await _replay_events(session)
    asked = [e for e in events if e.get("event") == "question_asked"]
    assert len(asked) == 1
    data = json.loads(asked[0]["data"])
    assert data["request_id"] == "q-1"
    assert data["questions"][0]["question"] == "Continue?"


async def test_question_replied_clears_pending_replay(session: str):
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            QuestionAskedEvent(
                request_id="q-1",
                session_id=session,
                questions=[{"question": "Continue?", "options": ["yes", "no"]}],
            )
        ),
    )
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            QuestionRepliedEvent(
                request_id="q-1",
                session_id=session,
                status="answered",
                answers=["yes"],
            )
        ),
    )

    events = await _replay_events(session)
    assert not [e for e in events if e.get("event") == "question_asked"]


async def test_pending_permission_is_replayed_on_reconnect(session: str):
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            PermissionAskedEvent(
                request_id="p-1",
                session_id=session,
                tool="shell",
                patterns=["rm -rf"],
            )
        ),
    )

    events = await _replay_events(session)
    asked = [e for e in events if e.get("event") == "permission_asked"]
    assert len(asked) == 1
    data = json.loads(asked[0]["data"])
    assert data["request_id"] == "p-1"
    assert data["tool"] == "shell"
    assert data["patterns"] == ["rm -rf"]


async def test_permission_replied_clears_pending_replay(session: str):
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            PermissionAskedEvent(
                request_id="p-1",
                session_id=session,
                tool="shell",
                patterns=["curl"],
            )
        ),
    )
    await mss.push_event(
        session,
        StreamEnvelope.from_event(
            PermissionRepliedEvent(
                request_id="p-1",
                session_id=session,
                reply="once",
            )
        ),
    )

    events = await _replay_events(session)
    assert not [e for e in events if e.get("event") == "permission_asked"]
