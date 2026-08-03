"""``question_replied`` SSE emission from AskUserService (reply + interrupt)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.ask_user import AskUserService
from app.agent.tools.builtin.ask_user import QuestionSpec


async def _pending_id(svc: AskUserService) -> str:
    for _ in range(100):
        if svc._pending:
            return next(iter(svc._pending))
        await asyncio.sleep(0.005)
    raise AssertionError("no pending ask_user request appeared")


@pytest.mark.asyncio
async def test_reply_publishes_question_replied_sse():
    svc = AskUserService("sess-1", stream_session_id="lead-1")
    task = asyncio.create_task(
        svc.ask([QuestionSpec(question="Continue?", options=["yes", "no"])])
    )
    request_id = await _pending_id(svc)

    pushed: list = []

    async def _capture(session_id: str, envelope) -> None:
        pushed.append((session_id, envelope))

    with patch(
        "app.services.memory_stream_store.push_event",
        new=AsyncMock(side_effect=_capture),
    ):
        assert svc.reply(request_id, ["yes"]) is True
        assert await task == ["yes"]
        # Fire-and-forget task needs a tick to run.
        await asyncio.sleep(0)

    asserted = [
        (sid, env)
        for sid, env in pushed
        if getattr(env, "event", None) == "question_replied"
    ]
    assert len(asserted) == 1
    session_id, envelope = asserted[0]
    assert session_id == "lead-1"
    assert envelope.data["request_id"] == request_id
    assert envelope.data["session_id"] == "sess-1"
    assert envelope.data["status"] == "answered"
    assert envelope.data["answers"] == ["yes"]


@pytest.mark.asyncio
async def test_interrupt_cancel_publishes_question_replied_sse():
    svc = AskUserService("sess-2", stream_session_id="lead-2")
    task = asyncio.create_task(
        svc.ask([QuestionSpec(question="Gate?", options=["a", "b"], strict=True)])
    )
    request_id = await _pending_id(svc)

    pushed: list = []

    async def _capture(session_id: str, envelope) -> None:
        pushed.append((session_id, envelope))

    with patch(
        "app.services.memory_stream_store.push_event",
        new=AsyncMock(side_effect=_capture),
    ):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asserted = [
        (sid, env)
        for sid, env in pushed
        if getattr(env, "event", None) == "question_replied"
    ]
    assert len(asserted) == 1
    session_id, envelope = asserted[0]
    assert session_id == "lead-2"
    assert envelope.data["request_id"] == request_id
    assert envelope.data["session_id"] == "sess-2"
    assert envelope.data["status"] == "cancelled"
    assert envelope.data["answers"] == []
    assert request_id not in svc._pending
