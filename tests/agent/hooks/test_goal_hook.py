from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.hooks.goal import GoalContextHook, GoalUsageHook
from app.agent.schemas.chat import AssistantMessage
from app.agent.state import AgentState, ModelRequest, RunContext
from app.models.chat import ChatSession
from app.services import goal_service


@pytest_asyncio.fixture
async def goal_runtime_db() -> AsyncIterator[tuple[object, ChatSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
    yield factory, session
    await engine.dispose()


def _ctx(session_id: str) -> tuple[RunContext, AgentState, ModelRequest]:
    ctx = RunContext(session_id=session_id, run_id="run", agent_name="lead")
    state = AgentState(messages=[])
    request = ModelRequest(messages=(), system_prompt="Base prompt.")
    return ctx, state, request


@pytest.mark.asyncio
async def test_context_hook_injects_only_active_goal(goal_runtime_db):
    factory, session = goal_runtime_db
    async with factory() as db:
        await goal_service.replace_goal(db, session.id, "Ship durable Goal mode")
        await db.commit()

    hook = GoalContextHook(db_factory=factory, session_id=str(session.id))
    ctx, state, request = _ctx(str(session.id))

    active_request = await hook.before_model(ctx, state, request)

    assert active_request is not None
    assert "Ship durable Goal mode" in active_request.system_prompt
    assert "Goal mode never expands permissions" in active_request.system_prompt

    async with factory() as db:
        await goal_service.pause_goal(db, session.id)
        await db.commit()

    assert await hook.before_model(ctx, state, request) is None


@pytest.mark.asyncio
async def test_usage_hook_counts_team_model_tokens_and_pauses_budget(goal_runtime_db):
    factory, session = goal_runtime_db
    async with factory() as db:
        await goal_service.replace_goal(
            db,
            session.id,
            "Finish",
            token_budget=100,
        )
        await db.commit()

    hook = GoalUsageHook(db_factory=factory, session_id=str(session.id))
    ctx, state, _ = _ctx(str(session.id))
    await hook.before_agent(ctx, state)
    await hook.after_model(
        ctx,
        state,
        AssistantMessage(
            content="progress",
            extra={"usage": {"input": 70, "output": 35, "cache": 10}},
        ),
    )

    async with factory() as db:
        goal = await goal_service.require_goal(db, session.id)
        assert goal.tokens_used == 105
        assert goal.status == "paused"
        assert goal.pause_reason == "token_budget"


@pytest.mark.asyncio
async def test_context_hook_resets_unreported_blocker(goal_runtime_db):
    factory, session = goal_runtime_db
    async with factory() as db:
        await goal_service.replace_goal(db, session.id, "Deploy")
        await goal_service.request_blocked(db, session.id, blocker="No credentials")
        await db.commit()

    hook = GoalContextHook(db_factory=factory, session_id=str(session.id))
    ctx, state, _ = _ctx(str(session.id))
    await hook.after_agent(ctx, state, AssistantMessage(content="made progress"))

    async with factory() as db:
        goal = await goal_service.require_goal(db, session.id)
        assert goal.blocker_streak == 0


@asynccontextmanager
async def _unused_factory():
    yield None


@pytest.mark.asyncio
async def test_goal_hooks_ignore_non_uuid_test_sessions():
    ctx, state, request = _ctx("test-session")
    context_hook = GoalContextHook(
        db_factory=_unused_factory,
        session_id="test-session",
    )
    usage_hook = GoalUsageHook(
        db_factory=_unused_factory,
        session_id="test-session",
    )

    assert await context_hook.before_model(ctx, state, request) is None
    await usage_hook.before_agent(ctx, state)
    await usage_hook.after_model(
        ctx,
        state,
        AssistantMessage(extra={"usage": {"input": 1, "output": 1}}),
    )
