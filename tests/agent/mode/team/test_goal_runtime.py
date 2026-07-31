from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import col, select

from app.agent.agent_loop import Agent
from app.agent.hooks.goal import GOAL_CONTINUATION_DIRECTIVE
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam
from app.models.chat import ChatSession, SessionMessage
from app.services import goal_service
from tests.agent.mode.team.conftest import MockTeamProvider


def _team(session_id: str) -> AgentTeam:
    lead = TeamLead(
        Agent(name="lead", llm_provider=MockTeamProvider("ok")),
        session_id=session_id,
    )
    return AgentTeam(lead=lead, members={})


@pytest.mark.asyncio
async def test_completion_barrier_starts_hidden_goal_continuation(
    mock_stream_store,
):
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        await goal_service.replace_goal(db, session.id, "Finish the implementation")
        await db.commit()

    team = _team(str(session.id))
    activate = MagicMock()
    team.lead.activate_for_continuation = activate
    team._has_active_turn = True
    team.lead.state = "idle"

    await team._try_emit_done()

    activate.assert_called_once_with()
    assert team._has_active_turn is True
    assert not any(
        call.args[1].event == "done" for call in mock_stream_store.call_args_list
    )

    async with db_module.async_session_factory() as db:
        result = await db.exec(
            select(SessionMessage)
            .where(col(SessionMessage.session_id) == session.id)
            .order_by(col(SessionMessage.created_at))
        )
        rows = list(result.all())

    directive = rows[-1]
    assert directive.content == GOAL_CONTINUATION_DIRECTIVE
    assert directive.extra == {
        "command": "goal_continue",
        "hidden_from_user": True,
        "hidden_from_summary": True,
    }


@pytest.mark.asyncio
async def test_paused_goal_allows_terminal_done(mock_stream_store):
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        await goal_service.replace_goal(db, session.id, "Finish")
        await goal_service.pause_goal(db, session.id)
        await db.commit()

    team = _team(str(session.id))
    activate = MagicMock()
    team.lead.activate_for_continuation = activate
    team._has_active_turn = True
    team.lead.state = "idle"

    await team._try_emit_done()

    activate.assert_not_called()
    assert any(
        call.args[1].event == "done" for call in mock_stream_store.call_args_list
    )
    assert team._has_active_turn is False


@pytest.mark.asyncio
async def test_queued_user_messages_take_precedence_over_goal():
    team = _team("018f0000-0000-7000-8000-000000000001")
    team._has_active_turn = True
    team.lead.state = "idle"
    queued = AsyncMock(return_value=True)
    goal = AsyncMock(return_value=True)
    team._activate_queued_user_messages = queued
    team._activate_goal_continuation = goal

    await team._try_emit_done()

    queued.assert_awaited_once()
    goal.assert_not_awaited()


@pytest.mark.asyncio
async def test_goal_cannot_be_replaced_while_turn_is_active():
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()

    team = _team(str(session.id))
    team._has_active_turn = True
    team.lead.state = "working"

    from app.agent.mode.team.team import ContinuePreconditionError

    with pytest.raises(ContinuePreconditionError, match="active turn"):
        await team.handle_user_message(
            "/goal Ship the replacement objective",
            str(session.id),
        )

    async with db_module.async_session_factory() as db:
        goal = await goal_service.get_goal(db, session.id)
    assert goal is None


@pytest.mark.asyncio
async def test_goal_start_persists_objective_and_starts_normal_turn(
    mock_stream_store,
    monkeypatch,
):
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()

    team = _team(str(session.id))
    team.mailbox.send = AsyncMock()
    monkeypatch.setattr(
        "app.agent.mode.team.team.snapshot_service.track",
        AsyncMock(return_value=None),
    )

    await team.handle_user_message(
        "/goal Implement and verify the feature",
        str(session.id),
    )

    team.mailbox.send.assert_awaited_once()
    assert team._has_active_turn is True
    async with db_module.async_session_factory() as db:
        goal = await goal_service.require_goal(db, session.id)
        result = await db.exec(
            select(SessionMessage).where(col(SessionMessage.session_id) == session.id)
        )
        messages = list(result.all())
    assert goal.objective == "Implement and verify the feature"
    assert messages[0].content == "Implement and verify the feature"
    assert messages[0].extra["command"] == "goal_start"
    assert any(
        call.args[1].event == "goal_status" for call in mock_stream_store.call_args_list
    )


@pytest.mark.asyncio
async def test_resume_command_restarts_hidden_goal_turn(mock_stream_store):
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        await goal_service.replace_goal(db, session.id, "Finish")
        await goal_service.pause_goal(db, session.id)
        await db.commit()

    team = _team(str(session.id))
    activate = MagicMock()
    team.lead.activate_for_continuation = activate

    await team.handle_user_message("/goal:resume", str(session.id))

    activate.assert_called_once_with()
    assert team._has_active_turn is True
    async with db_module.async_session_factory() as db:
        goal = await goal_service.require_goal(db, session.id)
        assert goal.status == "active"
