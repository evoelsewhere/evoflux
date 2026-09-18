from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.services import suggested_task_service as svc

PROMPT = (
    "In tests/agent/schemas/test_agent_schemas.py the uuid7 timestamp test "
    "fails intermittently by exactly one microsecond. Reproduce with "
    "`pytest -p no:randomly` run repeatedly, then fix the truncation."
)


@pytest.fixture
async def task_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace="/repo")
        db.add(session)
        await db.commit()
        yield db, session
    await engine.dispose()


async def _create(db, session, **overrides):
    payload = {
        "title": "Fix flaky uuid7 test",
        "tldr": "Noticed it while running the suite.",
        "prompt": PROMPT,
    }
    payload.update(overrides)
    return await svc.create(db, session.id, **payload)


@pytest.mark.asyncio
async def test_create_parks_a_pending_task(task_db):
    db, session = task_db
    task, created = await _create(db, session)
    await db.commit()

    assert created is True
    assert task.status == "pending"
    assert task.spawned_session_id is None


@pytest.mark.asyncio
async def test_same_finding_is_not_raised_twice(task_db):
    db, session = task_db
    first, _ = await _create(db, session)
    await db.commit()

    # Same finding, different spelling: casing, punctuation and spacing are
    # normalised away, so this must resolve to the original chip.
    second, created = await _create(db, session, title="  fix flaky UUID7 test.  ")
    await db.commit()

    assert created is False
    assert second.id == first.id


@pytest.mark.asyncio
async def test_dismissed_finding_is_not_resurrected(task_db):
    db, session = task_db
    task, _ = await _create(db, session)
    await svc.dismiss(db, task, reason="fixed inline")
    await db.commit()

    again, created = await _create(db, session)
    await db.commit()

    assert created is False
    assert again.status == "dismissed"
    assert again.dismiss_reason == "fixed inline"


@pytest.mark.asyncio
async def test_pending_cap_is_enforced(task_db):
    db, session = task_db
    for index in range(svc.MAX_PENDING_PER_SESSION):
        await _create(db, session, title=f"Fix problem number {index}")
    await db.commit()

    with pytest.raises(svc.SuggestedTaskConflictError):
        await _create(db, session, title="One suggestion too many")


@pytest.mark.asyncio
async def test_dismissing_frees_a_slot(task_db):
    db, session = task_db
    created_tasks = []
    for index in range(svc.MAX_PENDING_PER_SESSION):
        task, _ = await _create(db, session, title=f"Fix problem number {index}")
        created_tasks.append(task)
    await svc.dismiss(db, created_tasks[0])
    await db.commit()

    task, created = await _create(db, session, title="Now there is room")
    await db.commit()

    assert created is True
    assert task.status == "pending"


@pytest.mark.asyncio
async def test_prompt_must_stand_alone(task_db):
    db, session = task_db
    with pytest.raises(svc.SuggestedTaskValidationError, match="stand alone"):
        await _create(db, session, prompt="fix the flaky test")


@pytest.mark.asyncio
async def test_started_task_cannot_be_dismissed(task_db):
    db, session = task_db
    task, _ = await _create(db, session)
    spawned = ChatSession(agent_name="lead", mode="coding", workspace="/repo")
    db.add(spawned)
    await db.flush()
    await svc.mark_started(db, task, spawned_session_id=spawned.id)
    await db.commit()

    # The spawned session owns the work now; withdrawing the chip would
    # misreport what happened to it.
    with pytest.raises(svc.SuggestedTaskConflictError, match="already started"):
        await svc.dismiss(db, task)


@pytest.mark.asyncio
async def test_list_returns_only_pending_by_default(task_db):
    db, session = task_db
    keep, _ = await _create(db, session, title="Keep this one open")
    gone, _ = await _create(db, session, title="Retire this one")
    await svc.dismiss(db, gone)
    await db.commit()

    pending = await svc.list_for_session(db, session.id)
    everything = await svc.list_for_session(
        db, session.id, statuses=("pending", "started", "dismissed")
    )

    assert [row.id for row in pending] == [keep.id]
    assert {row.id for row in everything} == {keep.id, gone.id}
