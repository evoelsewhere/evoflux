from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools.builtin import suggested_task as tools
from app.models.chat import ChatSession
from app.services import suggested_task_service as svc

PROMPT = (
    "In app/services/example.py the retry loop swallows the final exception. "
    "Reproduce with `pytest tests/services/test_example.py -q`, then surface "
    "the error instead of returning None."
)


async def _session() -> ChatSession:
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace="/repo")
        db.add(session)
        await db.commit()
    return session


def _state(session: ChatSession) -> SimpleNamespace:
    return SimpleNamespace(metadata={"stream_session_id": str(session.id)})


@pytest.mark.asyncio
async def test_spawn_task_parks_a_chip_without_blocking():
    import app.core.db as db_module

    session = await _session()

    result = await tools.spawn_task.arun(
        _injected={"_state": _state(session)},
        title="Fix swallowed retry exception",
        tldr="Noticed while reading the retry helper.",
        prompt=PROMPT,
    )

    assert "Suggested task created" in result
    async with db_module.async_session_factory() as db:
        rows = await svc.list_for_session(db, session.id)
    assert [row.title for row in rows] == ["Fix swallowed retry exception"]


@pytest.mark.asyncio
async def test_spawn_task_rejects_a_prompt_that_cannot_stand_alone():
    session = await _session()

    import app.core.db as db_module

    result = await tools.spawn_task.arun(
        _injected={"_state": _state(session)},
        title="Fix the thing",
        tldr="Saw it in passing.",
        prompt="fix it",
    )

    # Correctable, so the agent is told how to fix it rather than handed a
    # tool failure.
    assert "[Error]" in result
    assert "stand alone" in result
    async with db_module.async_session_factory() as db:
        assert await svc.list_for_session(db, session.id) == []


@pytest.mark.asyncio
async def test_repeating_a_suggestion_creates_nothing():
    import app.core.db as db_module

    session = await _session()
    state = _state(session)
    args = {
        "title": "Fix swallowed retry exception",
        "tldr": "Noticed while reading the retry helper.",
        "prompt": PROMPT,
    }

    await tools.spawn_task.arun(_injected={"_state": state}, **args)
    second = await tools.spawn_task.arun(_injected={"_state": state}, **args)

    assert "Already suggested" in second
    async with db_module.async_session_factory() as db:
        rows = await svc.list_for_session(db, session.id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_dismiss_task_withdraws_the_chip():
    import app.core.db as db_module

    session = await _session()
    state = _state(session)
    await tools.spawn_task.arun(
        _injected={"_state": state},
        title="Fix swallowed retry exception",
        tldr="Noticed while reading the retry helper.",
        prompt=PROMPT,
    )
    async with db_module.async_session_factory() as db:
        task_id = (await svc.list_for_session(db, session.id))[0].id

    result = await tools.dismiss_task.arun(
        _injected={"_state": state},
        task_id=str(task_id),
        reason="fixed inline",
    )

    assert "withdrawn" in result
    async with db_module.async_session_factory() as db:
        assert await svc.list_for_session(db, session.id) == []


@pytest.mark.asyncio
async def test_dismiss_task_refuses_another_sessions_chip():
    import app.core.db as db_module

    owner = await _session()
    other = await _session()
    await tools.spawn_task.arun(
        _injected={"_state": _state(owner)},
        title="Fix swallowed retry exception",
        tldr="Noticed while reading the retry helper.",
        prompt=PROMPT,
    )
    async with db_module.async_session_factory() as db:
        task_id = (await svc.list_for_session(db, owner.id))[0].id

    result = await tools.dismiss_task.arun(
        _injected={"_state": _state(other)}, task_id=str(task_id)
    )

    assert "No such suggested task" in result
    async with db_module.async_session_factory() as db:
        assert len(await svc.list_for_session(db, owner.id)) == 1
