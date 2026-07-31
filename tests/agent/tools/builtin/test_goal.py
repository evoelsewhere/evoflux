from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools.builtin import goal as goal_tools
from app.models.chat import ChatSession
from app.services import goal_service


@pytest.mark.asyncio
async def test_get_goal_returns_durable_snapshot():
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        await goal_service.replace_goal(
            db,
            session.id,
            "Implement Goal mode",
            token_budget=5_000,
        )
        await db.commit()
    state = SimpleNamespace(metadata={"stream_session_id": str(session.id)})

    result = await goal_tools.get_goal.arun(_injected={"_state": state})

    assert "Implement Goal mode" in result
    assert '"token_budget":5000' in result


@pytest.mark.asyncio
async def test_blocker_can_increment_only_once_per_goal_turn():
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        await goal_service.replace_goal(db, session.id, "Deploy")
        await db.commit()

    first_turn = SimpleNamespace(metadata={"stream_session_id": str(session.id)})
    await goal_tools.update_goal.arun(
        _injected={"_state": first_turn},
        status="blocked",
        blocker="Missing credentials",
    )
    await goal_tools.update_goal.arun(
        _injected={"_state": first_turn},
        status="blocked",
        blocker="Missing credentials",
    )
    async with db_module.async_session_factory() as db:
        goal = await goal_service.require_goal(db, session.id)
        assert goal.blocker_streak == 1

    for expected in (2, 3):
        turn = SimpleNamespace(metadata={"stream_session_id": str(session.id)})
        await goal_tools.update_goal.arun(
            _injected={"_state": turn},
            status="blocked",
            blocker="Missing credentials",
        )
        async with db_module.async_session_factory() as db:
            goal = await goal_service.require_goal(db, session.id)
            assert goal.blocker_streak == expected

    assert goal.status == "blocked"
