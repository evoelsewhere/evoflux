from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import select

from app.agent.hooks.memory_extraction import (
    MemoryExtractionHook,
    drain_memory_extraction_tasks,
)
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.state import AgentState, RunContext
from app.models.chat import ChatSession
from app.models.memory import MemoryExtractionState, MemoryFact


class _ExtractionProvider:
    model = "mock:memory"

    async def chat(self, messages, tools=None, **kwargs):
        return AssistantMessage(
            content=(
                '{"memories":[{"content":"The user prefers concise verified '
                'answers","kind":"preference","scope":"user",'
                '"confidence":"high"}]}'
            ),
            extra={"usage": {"input": 100, "output": 20, "cache": 0}},
        )


class _InvalidExtractionProvider:
    model = "mock:memory"

    async def chat(self, messages, tools=None, **kwargs):
        return AssistantMessage(content="not-json")


@pytest.mark.asyncio
async def test_hook_persists_fact_and_cursor_at_third_completed_response(
    setup_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core.config import settings
    from app.core.db import async_session_factory

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(wiki))

    session = ChatSession(agent_name="lead")
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

    messages = []
    for index in range(3):
        messages.extend(
            [
                HumanMessage(content=f"Question {index}"),
                AssistantMessage(content=f"Answer {index}"),
            ]
        )
    state = AgentState(messages=messages)
    hook = MemoryExtractionHook(
        _ExtractionProvider(),  # type: ignore[arg-type]
        db_factory=async_session_factory,
        min_assistant_messages=3,
        every_n_messages=10,
    )
    await hook.after_agent(
        RunContext(
            session_id=str(session.id),
            run_id="run",
            agent_name="lead",
        ),
        state,
        messages[-1],  # type: ignore[arg-type]
    )
    await drain_memory_extraction_tasks()

    async with async_session_factory() as db:
        facts = list((await db.exec(select(MemoryFact))).all())
        cursor = await db.get(MemoryExtractionState, session.id)

    assert [fact.content for fact in facts] == [
        "The user prefers concise verified answers"
    ]
    assert facts[0].scope_type == "user"
    assert cursor is not None
    assert cursor.last_assistant_count == 3
    assert cursor.status == "done"
    note_files = list((wiki / "notes").glob("*.md"))
    assert len(note_files) == 1
    assert "user/preference/high" in note_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_invalid_provider_output_keeps_cursor_retryable(setup_db):
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="lead")
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

    messages = [
        HumanMessage(content=f"Question {index}")
        if offset == 0
        else AssistantMessage(content=f"Answer {index}")
        for index in range(3)
        for offset in range(2)
    ]
    hook = MemoryExtractionHook(
        _InvalidExtractionProvider(),  # type: ignore[arg-type]
        db_factory=async_session_factory,
        min_assistant_messages=3,
    )
    await hook.after_agent(
        RunContext(session_id=str(session.id), run_id="run", agent_name="lead"),
        AgentState(messages=messages),
        messages[-1],  # type: ignore[arg-type]
    )
    await drain_memory_extraction_tasks()

    async with async_session_factory() as db:
        cursor = await db.get(MemoryExtractionState, session.id)

    assert cursor is not None
    assert cursor.last_assistant_count == 0
    assert cursor.status == "failed"
    assert cursor.pending_assistant_count is None
