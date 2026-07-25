from __future__ import annotations

from datetime import timedelta
from uuid import uuid7

import pytest

from app.agent.mode.team.delegation_ledger import (
    complete_task,
    create_tasks,
    expire_overdue_tasks,
    release_ready_tasks,
    reopen_task,
)
from app.core import db as db_module
from app.models.chat import ChatSession, _utcnow


async def _session(db) -> ChatSession:
    row = ChatSession(id=uuid7(), agent_name="lead")
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_two_tasks_for_same_recipient_remain_independent():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        first = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "first"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        second = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "second"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        await complete_task(
            db,
            lead_session_id=lead.id,
            task_id=str(first.id),
            delegator="lead",
            recipient="coder#1",
            result={"summary": "first done"},
        )
        await db.commit()

        await db.refresh(first)
        await db.refresh(second)
        assert first.status == "completed"
        assert second.status == "pending"


@pytest.mark.asyncio
async def test_conflicting_duplicate_completion_is_rejected():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        task = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "implement"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        await complete_task(
            db,
            lead_session_id=lead.id,
            task_id=str(task.id),
            delegator="lead",
            recipient="coder#1",
            result={"summary": "first"},
        )
        with pytest.raises(ValueError, match="different final result"):
            await complete_task(
                db,
                lead_session_id=lead.id,
                task_id=str(task.id),
                delegator="lead",
                recipient="coder#1",
                result={"summary": "second"},
            )


@pytest.mark.asyncio
async def test_dependency_cannot_cross_lead_sessions():
    async with db_module.async_session_factory() as db:
        first_lead = await _session(db)
        second_lead = await _session(db)
        foreign_task = (
            await create_tasks(
                db,
                lead_session_id=second_lead.id,
                delegator="lead",
                recipients=["explorer#1"],
                spec={"goal": "foreign"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        with pytest.raises(ValueError, match="Unknown delegation dependencies"):
            await create_tasks(
                db,
                lead_session_id=first_lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "must stay isolated"},
                dependencies=[str(foreign_task.id)],
                deadline_at=None,
            )


@pytest.mark.asyncio
async def test_dependency_blocks_then_releases_after_completion():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        dependency = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["explorer#1"],
                spec={"goal": "research"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        blocked = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "implement"},
                dependencies=[str(dependency.id)],
                deadline_at=None,
            )
        )[0]
        assert blocked.status == "blocked"

        await complete_task(
            db,
            lead_session_id=lead.id,
            task_id=str(dependency.id),
            delegator="lead",
            recipient="explorer#1",
            result={"summary": "research done"},
        )
        ready, failed = await release_ready_tasks(
            db,
            lead_session_id=lead.id,
            live_recipients={"coder#1"},
        )
        assert [row.id for row in ready] == [blocked.id]
        assert failed == []
        assert blocked.status == "pending"


@pytest.mark.asyncio
async def test_failed_dependency_fails_blocked_task():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        dependency = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["explorer#1"],
                spec={"goal": "research"},
                dependencies=[],
                deadline_at=_utcnow() - timedelta(seconds=1),
            )
        )[0]
        blocked = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "implement"},
                dependencies=[str(dependency.id)],
                deadline_at=None,
            )
        )[0]
        await expire_overdue_tasks(db, lead.id)
        ready, failed = await release_ready_tasks(
            db,
            lead_session_id=lead.id,
            live_recipients={"coder#1"},
        )
        assert ready == []
        assert [row.id for row in failed] == [blocked.id]
        assert blocked.status == "failed"
        assert blocked.result["error"] == "delegation dependency failed"


@pytest.mark.asyncio
async def test_rejection_reopens_same_task_and_increments_attempt():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        task = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "implement"},
                dependencies=[],
                deadline_at=None,
            )
        )[0]
        await complete_task(
            db,
            lead_session_id=lead.id,
            task_id=str(task.id),
            delegator="lead",
            recipient="coder#1",
            result={"summary": "done"},
        )
        await reopen_task(
            db,
            lead_session_id=lead.id,
            task_id=str(task.id),
            delegator="lead",
            recipient="coder#1",
            feedback={"reason": "tests missing"},
        )
        assert task.status == "pending"
        assert task.attempt == 2
        assert task.last_rejection == {"reason": "tests missing"}


@pytest.mark.asyncio
async def test_deadline_expiry_fails_open_task():
    async with db_module.async_session_factory() as db:
        lead = await _session(db)
        task = (
            await create_tasks(
                db,
                lead_session_id=lead.id,
                delegator="lead",
                recipients=["coder#1"],
                spec={"goal": "implement"},
                dependencies=[],
                deadline_at=_utcnow() - timedelta(seconds=1),
            )
        )[0]
        expired = await expire_overdue_tasks(db, lead.id)
        assert [row.id for row in expired] == [task.id]
        assert task.status == "failed"
