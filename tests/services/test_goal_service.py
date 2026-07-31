from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.services import goal_service


@pytest.fixture
async def goal_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        session = ChatSession(agent_name="lead")
        db.add(session)
        await db.commit()
        yield db, session
    await engine.dispose()


@pytest.mark.asyncio
async def test_replace_goal_resets_accounting(goal_db):
    db, session = goal_db
    started = datetime(2026, 7, 31, tzinfo=timezone.utc)
    goal = await goal_service.replace_goal(
        db, session.id, "  Ship Goal mode  ", token_budget=20_000, now=started
    )
    goal.tokens_used = 500
    goal.blocker_streak = 2
    await db.commit()

    replaced = await goal_service.replace_goal(
        db,
        session.id,
        "Ship Goal mode with tests",
        token_budget=None,
        expected_version=goal.version,
        now=started + timedelta(seconds=10),
    )

    assert replaced.objective == "Ship Goal mode with tests"
    assert replaced.status == "active"
    assert replaced.token_budget is None
    assert replaced.tokens_used == 0
    assert replaced.time_used_seconds == 0
    assert replaced.blocker_streak == 0
    assert replaced.version == 2


@pytest.mark.asyncio
async def test_pause_and_resume_preserve_elapsed_time(goal_db):
    db, session = goal_db
    started = datetime(2026, 7, 31, tzinfo=timezone.utc)
    await goal_service.replace_goal(db, session.id, "Finish", now=started)

    paused = await goal_service.pause_goal(
        db, session.id, now=started + timedelta(seconds=12)
    )
    assert paused.status == "paused"
    assert paused.time_used_seconds == 12
    assert paused.pause_reason == "user"

    resumed = await goal_service.resume_goal(
        db, session.id, now=started + timedelta(seconds=20)
    )
    snap = goal_service.snapshot(resumed, now=started + timedelta(seconds=25))
    assert snap.status == "active"
    assert snap.time_used_seconds == 17


@pytest.mark.asyncio
async def test_blocked_requires_three_matching_goal_turns(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Deploy")

    first = goal_service.snapshot(
        await goal_service.request_blocked(
            db, session.id, blocker="Missing production credentials"
        )
    )
    second = goal_service.snapshot(
        await goal_service.request_blocked(
            db, session.id, blocker="  missing   production credentials "
        )
    )
    third = goal_service.snapshot(
        await goal_service.request_blocked(
            db, session.id, blocker="Missing production credentials"
        )
    )

    assert first.status == "active"
    assert second.status == "active"
    assert third.status == "blocked"
    assert third.blocker_streak == 3
    assert third.completed_at is not None


@pytest.mark.asyncio
async def test_different_blocker_resets_audit_streak(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Deploy")
    await goal_service.request_blocked(db, session.id, blocker="Missing credentials")
    goal = await goal_service.request_blocked(
        db, session.id, blocker="Waiting for network access"
    )

    assert goal.status == "active"
    assert goal.blocker_streak == 1


@pytest.mark.asyncio
async def test_successful_turn_resets_blocker_streak(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Deploy")
    await goal_service.request_blocked(db, session.id, blocker="Missing credentials")

    goal = await goal_service.reset_blocker_streak(db, session.id)

    assert goal is not None
    assert goal.status == "active"
    assert goal.blocker_streak == 0
    assert goal.blocker_fingerprint is None
    assert goal.status_details is None


@pytest.mark.asyncio
async def test_usage_is_accumulated_and_budget_exhaustion_pauses(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Finish", token_budget=100)

    goal = await goal_service.add_usage(db, session.id, 60)
    assert goal is not None
    assert goal.tokens_used == 60
    assert goal.status == "active"

    goal = await goal_service.add_usage(db, session.id, 45)
    assert goal is not None
    assert goal.tokens_used == 105
    assert goal.status == "paused"
    assert goal.pause_reason == "token_budget"


@pytest.mark.asyncio
async def test_complete_records_summary_and_evidence(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Finish")
    goal = await goal_service.complete_goal(
        db,
        session.id,
        summary="All requested work is complete.",
        evidence=["pytest passed", "typecheck passed"],
    )

    assert goal.status == "complete"
    assert goal.status_details == {
        "summary": "All requested work is complete.",
        "evidence": ["pytest passed", "typecheck passed"],
    }


@pytest.mark.asyncio
async def test_clear_goal_removes_persisted_state(goal_db):
    db, session = goal_db
    await goal_service.replace_goal(db, session.id, "Finish")
    cleared = await goal_service.clear_goal(db, session.id)

    assert cleared.objective == "Finish"
    assert await goal_service.get_goal(db, session.id) is None


@pytest.mark.asyncio
async def test_validation_rejects_empty_objective_and_nonpositive_budget(goal_db):
    db, session = goal_db
    with pytest.raises(goal_service.GoalValidationError):
        await goal_service.replace_goal(db, session.id, "   ")
    with pytest.raises(goal_service.GoalValidationError):
        await goal_service.replace_goal(db, session.id, "Finish", token_budget=0)
