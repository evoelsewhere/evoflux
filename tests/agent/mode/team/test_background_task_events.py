"""A background task's notice wakes an idle lead and is persisted for the UI."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlmodel import col, select

from app.agent.agent_loop import Agent
from app.agent.background_tasks import TASK_EVENT_SENDER
from app.agent.mode.team.mailbox import Message
from app.agent.mode.team.member import TeamLead, _inbox_sse_extra
from app.agent.mode.team.team import AgentTeam
from app.agent.schemas.chat import HumanMessage
from app.models.chat import ChatSession, SessionMessage
from tests.agent.mode.team.conftest import MockTeamProvider

_EVENT = {
    "kind": "task_event",
    "task_event": "exited",
    "process_id": "proc_0123456789",
    "command": "pytest -q",
    "status": "succeeded",
    "exit_code": 0,
    "duration_ms": 4200,
    "artifact": "/tmp/proc_0123456789.txt",
}
_TEXT = "[Background task proc_0123456789 finished: Succeeded]\n\n12 passed"


def test_inbox_sse_payload_carries_the_structured_task_event() -> None:
    raw = Message(
        from_agent=TASK_EVENT_SENDER, to_agent="lead", content=_TEXT, extra=dict(_EVENT)
    )
    payload = _inbox_sse_extra(HumanMessage(content=_TEXT), raw)

    assert payload["from_agent"] == TASK_EVENT_SENDER
    assert payload["content"] == _TEXT
    assert payload["task_event"]["process_id"] == "proc_0123456789"
    assert payload["task_event"]["exit_code"] == 0
    assert "kind" not in payload["task_event"]


def test_inbox_sse_payload_is_unchanged_for_ordinary_messages() -> None:
    raw = Message(from_agent="worker", to_agent="lead", content="[worker]: hi")
    payload = _inbox_sse_extra(HumanMessage(content="[worker]: hi"), raw)

    assert payload == {"content": "[worker]: hi", "from_agent": "worker"}


@pytest.mark.asyncio
async def test_a_notice_wakes_an_idle_lead_and_is_persisted() -> None:
    import app.core.db as _db

    sid = uuid.uuid7()
    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(ChatSession(id=sid, agent_name="lead"))

    provider = MockTeamProvider("Tests passed, nothing else to do.")
    lead = TeamLead(
        Agent(name="lead", llm_provider=provider),
        session_id=str(sid),
        db_factory=_db.async_session_factory,
    )
    team = AgentTeam(lead=lead, members={})
    await team.start()
    try:
        assert not team.has_active_user_turn()

        await team.deliver_background_task_event(_TEXT, dict(_EVENT))

        for _ in range(100):
            await asyncio.sleep(0.05)
            task = lead._active_task
            if provider.call_count and (task is None or task.done()):
                break
        assert provider.call_count == 1

        async with _db.async_session_factory() as db:
            rows = (
                await db.exec(
                    select(SessionMessage)
                    .where(col(SessionMessage.session_id) == sid)
                    .order_by(col(SessionMessage.created_at))
                )
            ).all()

        notice = rows[0]
        assert notice.role == "user"
        assert notice.content == _TEXT
        assert notice.extra is not None
        assert notice.extra["from_agent"] == TASK_EVENT_SENDER
        assert notice.extra["kind"] == "task_event"
        assert notice.extra["process_id"] == "proc_0123456789"
        assert rows[-1].role == "assistant"
    finally:
        await team.stop()


@pytest.mark.asyncio
async def test_with_waking_off_the_notice_waits_for_the_next_turn(monkeypatch) -> None:
    import app.core.db as _db

    monkeypatch.setattr(
        "app.core.runtime_settings.background_task_wake_idle", lambda: False
    )
    sid = uuid.uuid7()
    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(ChatSession(id=sid, agent_name="lead"))

    provider = MockTeamProvider("Noted.")
    lead = TeamLead(
        Agent(name="lead", llm_provider=provider),
        session_id=str(sid),
        db_factory=_db.async_session_factory,
    )
    team = AgentTeam(lead=lead, members={})
    await team.start()
    try:
        await team.deliver_background_task_event(_TEXT, dict(_EVENT))
        await asyncio.sleep(0.4)

        # No turn of its own...
        assert provider.call_count == 0
        assert not team.has_active_user_turn()
        # ...but the notice is held for the lead's next turn.
        assert team.mailbox.inbox_size(lead.name) == 1
        held = team.mailbox.drain_nowait(lead.name)
        assert held[0].content == _TEXT
        assert held[0].from_agent == TASK_EVENT_SENDER
    finally:
        await team.stop()
