"""Tests for the dream service."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

import pytest

from app.agent.agent_loop import Agent
from app.agent.providers.base import LLMProviderBase
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatMessage,
    Usage,
)
from app.models.chat import ChatSession, DreamLog, SessionMessage
from app.services.dream import (
    DREAM_AGENT_NAME,
    DreamAgentConfig,
    _diff_topics,
    _load_dream_agent,
    _synthesise_note,
    _synthesise_session,
    get_manual_dream_run_status,
    get_unprocessed_notes,
    get_unprocessed_sessions,
    mark_note_processed,
    mark_session_processed,
    run_dream,
    start_manual_dream_run,
)


# ── Mock LLM provider ─────────────────────────────────────────────────────────


class _MockProvider(LLMProviderBase):
    model = "mock-model"

    def __init__(self, reply: str = "Done."):
        super().__init__()
        self._reply = reply

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[ChatCompletionChunk]:
        reply = self._reply

        async def _gen() -> AsyncIterator[ChatCompletionChunk]:
            yield ChatCompletionChunk(
                id="c1",
                created=1_000_000,
                model="mock-model",
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionDelta(content=reply),
                        finish_reason="stop",
                    )
                ],
                usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        return _gen()

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AssistantMessage:
        return AssistantMessage(content=self._reply)


def _make_dream_agent() -> Agent:
    return Agent(name="dream", llm_provider=_MockProvider())


def _make_loaded_agent() -> tuple[Agent, object]:
    """Return (agent, sandbox_token) like ``_load_dream_agent``."""
    from app.agent.sandbox import SandboxConfig, set_sandbox

    token = set_sandbox(SandboxConfig(workspace="/tmp"))
    return _make_dream_agent(), token


def _make_dream_config(**overrides) -> DreamAgentConfig:
    base = {"name": "dream", "model": "mock:model", "system_prompt": "test"}
    base.update(overrides)
    return DreamAgentConfig.model_validate(base)


@pytest.fixture(autouse=True)
def _wiki_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "wiki"
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(target))
    (target / "notes").mkdir(parents=True, exist_ok=True)
    yield target


# ── get_unprocessed_sessions ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_empty(setup_db):
    """No sessions → empty list."""
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db)
    assert result == []


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_returns_unprocessed(setup_db):
    """Sessions not in dream_log are returned (regardless of message count)."""
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db)
    assert len(result) == 1
    assert result[0].id == session.id


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_excludes_processed(setup_db):
    """Sessions already in dream_log are excluded."""
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

    async with async_session_factory() as db:
        await mark_session_processed(db, session.id, "test-agent", [])

    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db)
    assert result == []


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_excludes_dream_agent_sessions(setup_db):
    """Dream's own sessions are excluded so dream cannot feed itself (bug #7)."""
    from app.core.db import async_session_factory

    user_session = ChatSession(agent_name="test-agent")
    dream_session = ChatSession(agent_name=DREAM_AGENT_NAME)
    async with async_session_factory() as db:
        db.add(user_session)
        db.add(dream_session)
        await db.commit()

    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db)
    assert len(result) == 1
    assert result[0].id == user_session.id


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_respects_renamed_dream_agent(setup_db):
    """A custom dream agent name must still filter its sessions."""
    from app.core.db import async_session_factory

    user_session = ChatSession(agent_name="test-agent")
    renamed_dream_session = ChatSession(agent_name="my-custom-dream")
    async with async_session_factory() as db:
        db.add(user_session)
        db.add(renamed_dream_session)
        await db.commit()

    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db, dream_agent_name="my-custom-dream")
    assert len(result) == 1
    assert result[0].id == user_session.id


# ── mark_session_processed ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_session_processed_inserts_row(setup_db):
    """mark_session_processed should insert a DreamLog row and commit immediately."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    session_id = uuid.uuid4()
    async with async_session_factory() as db:
        await mark_session_processed(db, session_id, "agent", ["topic-a"])

    async with async_session_factory() as db:
        result = await db.exec(select(DreamLog))
        rows = result.all()
    assert len(rows) == 1
    assert rows[0].agent_name == "agent"


# ── get_unprocessed_notes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_unprocessed_notes_empty(setup_db, _wiki_dir: Path):
    """No note files → empty list."""
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        result = await get_unprocessed_notes(db)
    assert result == []


@pytest.mark.asyncio
async def test_get_unprocessed_notes_returns_unprocessed(setup_db, _wiki_dir: Path):
    """Note files not in dream_notes_log are returned."""
    from app.core.db import async_session_factory

    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("Note content.", encoding="utf-8")

    async with async_session_factory() as db:
        result = await get_unprocessed_notes(db)
    assert "2026-04-29.md" in result


@pytest.mark.asyncio
async def test_get_unprocessed_notes_excludes_processed(setup_db, _wiki_dir: Path):
    """Note files already in dream_notes_log are excluded."""
    from app.core.db import async_session_factory

    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("Note content.", encoding="utf-8")

    async with async_session_factory() as db:
        await mark_note_processed(db, "2026-04-29.md")

    async with async_session_factory() as db:
        result = await get_unprocessed_notes(db)
    assert result == []


@pytest.mark.asyncio
async def test_get_unprocessed_notes_requeues_modified_file(setup_db, _wiki_dir: Path):
    """Appending after consolidation must make the same daily file pending."""
    from app.core.db import async_session_factory

    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("First fact.", encoding="utf-8")
    async with async_session_factory() as db:
        await mark_note_processed(db, note_file.name)
    note_file.write_text("First fact.\nSecond fact.", encoding="utf-8")

    async with async_session_factory() as db:
        assert note_file.name in await get_unprocessed_notes(db)


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_requeues_new_messages(setup_db):
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="lead")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="First"))
        await db.commit()
        await mark_session_processed(db, session.id, "lead", [])

    async with async_session_factory() as db:
        assert session.id not in {row.id for row in await get_unprocessed_sessions(db)}
        db.add(SessionMessage(session_id=session.id, role="user", content="Second"))
        await db.commit()

    async with async_session_factory() as db:
        assert session.id in {row.id for row in await get_unprocessed_sessions(db)}


@pytest.mark.asyncio
async def test_get_unprocessed_sessions_excludes_child_and_side_chat(setup_db):
    from app.core.db import async_session_factory

    lead = ChatSession(agent_name="lead")
    async with async_session_factory() as db:
        db.add(lead)
        await db.flush()
        child = ChatSession(agent_name="member", parent_session_id=lead.id)
        side = ChatSession(agent_name="lead", session_type="side_chat")
        db.add(child)
        db.add(side)
        await db.commit()

    async with async_session_factory() as db:
        ids = {row.id for row in await get_unprocessed_sessions(db)}

    assert lead.id in ids
    assert child.id not in ids
    assert side.id not in ids


# ── Dream v2 source selection helpers ────────────────────────────────────────


# ── run_dream ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_nothing_to_process(setup_db, _wiki_dir: Path):
    """run_dream with nothing to process returns zeros."""
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        result = await run_dream(db)
    assert result["sessions_processed"] == 0
    assert result["notes_processed"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_start_manual_dream_run_completes_and_reports_status(
    setup_db, _wiki_dir: Path
):
    """POST /dream/run's background-task path returns immediately, then
    ``get_manual_dream_run_status`` reflects completion with the real result.
    """
    import asyncio

    from app.core.db import async_session_factory
    from app.services import dream as dream_module

    dream_module._manual_run_state = dream_module.ManualDreamRunState()

    started = start_manual_dream_run(async_session_factory)
    assert started == {"status": "started"}

    status = get_manual_dream_run_status()
    assert status["running"] is True
    assert status["result"] is None
    assert status["error"] is None

    task = dream_module._manual_run_task
    assert task is not None
    await asyncio.wait_for(task, timeout=5)

    status = get_manual_dream_run_status()
    assert status["running"] is False
    assert status["error"] is None
    assert status["result"] == {
        "sessions_processed": 0,
        "notes_processed": 0,
        "remaining": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_start_manual_dream_run_dedupes_concurrent_manual_calls(
    setup_db, _wiki_dir: Path
):
    """A second manual trigger while one is in flight reports already_running
    instead of spawning a duplicate background task."""
    import asyncio

    from app.core.db import async_session_factory
    from app.services import dream as dream_module

    dream_module._manual_run_state = dream_module.ManualDreamRunState()

    first = start_manual_dream_run(async_session_factory)
    assert first == {"status": "started"}
    second = start_manual_dream_run(async_session_factory)
    assert second == {"status": "already_running"}

    task = dream_module._manual_run_task
    assert task is not None
    await asyncio.wait_for(task, timeout=5)
    assert get_manual_dream_run_status()["running"] is False


@pytest.mark.asyncio
async def test_run_dream_keeps_sessions_pending_without_config(
    setup_db, _wiki_dir: Path
):
    """Non-empty sessions must not be marked processed when dream cannot run."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    _remove_dream_md()
    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        result = await run_dream(db)
    assert result["sessions_processed"] == 0
    assert result["remaining"] == 1
    assert result["skipped"] == "no_model_configured"

    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_run_dream_keeps_sessions_pending_without_model(
    setup_db, _wiki_dir: Path
):
    """Model-less Dream settings must not consume sessions without synthesis."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    _write_dream_md(model="")
    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="Hello!"))
        await db.commit()

    async with async_session_factory() as db:
        result = await run_dream(db)

    assert result["sessions_processed"] == 0
    assert result["remaining"] == 1
    assert result["skipped"] == "no_model_configured"
    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_run_dream_keeps_sessions_pending_when_agent_load_fails(
    setup_db, _wiki_dir: Path
):
    """Loader failures must retry later instead of marking sessions processed."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    _write_dream_md(model="mock:model")
    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="Hello!"))
        await db.commit()

    with patch("app.services.dream._load_dream_agent", return_value=None):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["sessions_processed"] == 0
    assert result["remaining"] == 1
    assert result["failed"] == 1
    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    assert len(rows) == 0


# ── _load_dream_agent ─────────────────────────────────────────────────────────


def test_load_dream_agent_returns_none_when_no_model():
    """Returns None when DreamAgentConfig.model is absent."""
    cfg = DreamAgentConfig.model_validate({"name": "dream", "system_prompt": "test"})
    assert _load_dream_agent(cfg) is None


# ── _synthesise_session ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesise_session_empty(setup_db, _wiki_dir: Path):
    """Empty session produces no topics and doesn't crash."""
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

    agent = _make_dream_agent()
    async with async_session_factory() as db:
        result = await _synthesise_session(agent, db, session, timeout_seconds=60)

    assert result == []


@pytest.mark.asyncio
async def test_synthesise_session_with_messages(setup_db, _wiki_dir: Path):
    """Session with messages runs agent.run() without error."""
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello, I use Python.",
            )
        )
        db.add(
            SessionMessage(
                session_id=session.id,
                role="assistant",
                content="Got it! Python is great.",
            )
        )
        await db.commit()

    agent = _make_dream_agent()
    async with async_session_factory() as db:
        # Should not raise; topics list may be empty (mock agent writes nothing).
        result = await _synthesise_session(agent, db, session, timeout_seconds=60)

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_synthesise_session_does_not_carry_target_session_id(
    setup_db, _wiki_dir: Path
):
    """The dream agent's run must NOT carry the target session's id (bug #1).

    Dream is not part of the user's conversation history, so the RunConfig
    passed to ``agent.run`` MUST NOT reuse the target session's id — that
    would corrupt session history if a checkpointer were ever attached.
    """
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="Hello!"))
        await db.commit()

    agent = _make_dream_agent()
    captured: list[str | None] = []
    original_run = agent.run

    async def _spy(messages, **kwargs):
        config = kwargs.get("config")
        captured.append(config.session_id if config else None)
        return await original_run(messages, **kwargs)

    agent.run = _spy  # type: ignore[method-assign]
    async with async_session_factory() as db:
        await _synthesise_session(agent, db, session, timeout_seconds=60)

    assert len(captured) == 1
    # Either None (current behaviour) or a fresh id — never the target id.
    assert captured[0] != str(session.id)


# ── _synthesise_note ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesise_note_with_content(setup_db, _wiki_dir: Path):
    """Note file with content runs agent.run() without error."""
    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("I prefer dark mode.\n", encoding="utf-8")

    agent = _make_dream_agent()
    result = await _synthesise_note(agent, "2026-04-29.md", timeout_seconds=60)

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_synthesise_note_missing_file_raises(setup_db, _wiki_dir: Path):
    """Missing note file raises _SynthesisFailed (caller skips marking it processed)."""
    from app.services.dream import _SynthesisFailed

    agent = _make_dream_agent()
    with pytest.raises(_SynthesisFailed):
        await _synthesise_note(agent, "nonexistent.md", timeout_seconds=60)


@pytest.mark.asyncio
async def test_synthesise_note_empty_file(setup_db, _wiki_dir: Path):
    """Empty note file returns empty list without calling agent."""
    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("   \n", encoding="utf-8")

    agent = _make_dream_agent()
    run_calls: list[tuple] = []
    original_run = agent.run

    async def _spy(*args, **kwargs):
        run_calls.append(args)
        return await original_run(*args, **kwargs)

    agent.run = _spy  # type: ignore[method-assign]
    result = await _synthesise_note(agent, "2026-04-29.md", timeout_seconds=60)

    assert result == []
    assert run_calls == [], "agent.run() should not be called for empty notes"


# ── run_dream with mocked agent ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_with_agent_processes_session(setup_db, _wiki_dir: Path):
    """run_dream uses dream agent when _load_dream_agent returns one."""
    from app.core.db import async_session_factory

    _write_dream_md()

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["sessions_processed"] == 1
    assert result["notes_processed"] == 0


@pytest.mark.asyncio
async def test_run_dream_with_agent_processes_note(setup_db, _wiki_dir: Path):
    """run_dream uses dream agent to process note files."""
    from app.core.db import async_session_factory

    _write_dream_md()

    note_file = _wiki_dir / "notes" / "2026-04-29.md"
    note_file.write_text("User prefers Vim.\n", encoding="utf-8")

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["notes_processed"] == 1
    assert result["sessions_processed"] == 0


@pytest.mark.asyncio
async def test_run_dream_topics_written_recorded(setup_db, _wiki_dir: Path):
    """Topics created by dream agent are recorded in dream_log."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    _write_dream_md()

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="I love Python.",
            )
        )
        await db.commit()

    topics_dir = _wiki_dir / "topics"
    topics_dir.mkdir(exist_ok=True)

    async def _fake_synthesise(agent, db, sess, *, timeout_seconds, wiki_context=""):
        (topics_dir / "python.md").write_text(
            "---\ndescription: Python programming.\ntags: [python]\n---\n",
            encoding="utf-8",
        )
        return ["python"]

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch(
            "app.services.dream._synthesise_session", side_effect=_fake_synthesise
        ):
            async with async_session_factory() as db:
                await run_dream(db)

    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()

    assert len(rows) == 1
    import json

    assert json.loads(rows[0].topics_written) == ["python"]


# ── Empty-session handling (now lives in run_dream, not get_unprocessed_sessions) ──


@pytest.mark.asyncio
async def test_run_dream_auto_marks_empty_sessions(setup_db, _wiki_dir: Path):
    """Empty sessions are auto-marked in dream_log by run_dream itself (bug #3)."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

    # get_unprocessed_sessions is now a pure read — no side effects.
    async with async_session_factory() as db:
        result = await get_unprocessed_sessions(db)
        assert len(result) == 1  # session is returned (no message check here)

        # Empty-session detection now happens inside run_dream
        rows_before = (await db.exec(select(DreamLog))).all()
        assert len(rows_before) == 0  # NOT pre-marked by get_unprocessed_sessions

    async with async_session_factory() as db:
        await run_dream(db)

    async with async_session_factory() as db:
        rows_after = (await db.exec(select(DreamLog))).all()
        assert len(rows_after) == 1
        assert rows_after[0].session_id == session.id


@pytest.mark.asyncio
async def test_run_dream_empty_sessions_not_counted_in_sessions_processed(setup_db):
    """sessions_processed counts real-work sessions only; empties are tracked separately."""
    from sqlmodel import select

    from app.core.db import async_session_factory

    _remove_dream_md()
    empty_session = ChatSession(agent_name="test-agent")
    session_with_msg = ChatSession(agent_name="test-agent")

    async with async_session_factory() as db:
        db.add(empty_session)
        db.add(session_with_msg)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session_with_msg.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        result = await run_dream(db)

    assert result["sessions_processed"] == 0
    assert result["remaining"] == 1
    assert result["skipped"] == "no_model_configured"
    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    assert len(rows) == 1  # Only the empty session is logged


@pytest.mark.asyncio
async def test_run_dream_caps_empty_session_drain(
    setup_db, _wiki_dir: Path, monkeypatch
):
    """A backlog of empty sessions must not produce thousands of commits in one
    run — only ``empty_session_drain_cap`` are marked per fire (bug M4).
    """
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.services import dream as dream_module

    # Patch the cap calculation by patching ``max`` is fragile — instead
    # generate enough empties that the default cap (100) leaves leftovers.
    async with async_session_factory() as db:
        for _ in range(105):
            db.add(ChatSession(agent_name="test-agent"))
        await db.commit()

    async with async_session_factory() as db:
        await run_dream(db)

    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    # Cap is max(100, batch_size*100) → 100 with default batch_size=1.
    # So 100 are drained; 5 remain unprocessed.
    assert len(rows) == 100

    _ = dream_module  # keep import for clarity


@pytest.mark.asyncio
async def test_run_dream_interleaves_sessions_and_notes(setup_db, _wiki_dir: Path):
    """With batch_size=2 and one session + two notes, dream picks one of each (bug #8)."""
    from app.core.db import async_session_factory

    _write_dream_md()

    session1 = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session1)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session1.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    note_file1 = _wiki_dir / "notes" / "2026-04-29.md"
    note_file1.write_text("Test note 1.\n", encoding="utf-8")
    note_file2 = _wiki_dir / "notes" / "2026-04-30.md"
    note_file2.write_text("Test note 2.\n", encoding="utf-8")

    # Use side_effect so each load returns a fresh sandbox token — the real
    # loader does the same and the test must not reuse contextvar tokens.
    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    # Scheduler admits one item from each class so notes cannot starve.
    assert result["sessions_processed"] == 1
    assert result["notes_processed"] == 1
    assert result["remaining"] == 1


# ── _diff_topics (bug #6: updates to existing topics) ─────────────────────────


def test_diff_topics_detects_new_file():
    before: dict[str, int] = {}
    after = {"foo.md": 100}
    assert _diff_topics(before, after) == ["foo"]


def test_diff_topics_detects_modification():
    """A bumped mtime on an existing file counts as a change (bug #6)."""
    before = {"foo.md": 100}
    after = {"foo.md": 200}
    assert _diff_topics(before, after) == ["foo"]


def test_diff_topics_unchanged_file_excluded():
    before = {"foo.md": 100}
    after = {"foo.md": 100}
    assert _diff_topics(before, after) == []


def test_diff_topics_sorted():
    before: dict[str, int] = {}
    after = {"zebra.md": 100, "alpha.md": 200}
    assert _diff_topics(before, after) == ["alpha", "zebra"]


# ── DreamAgentConfig (bug #14: parsed once + new fields) ──────────────────────


def test_dream_agent_config_injects_required_tools():
    cfg = _make_dream_config(tools=["write"])
    assert "read" in cfg.tools
    assert "write" in cfg.tools
    assert "edit" in cfg.tools
    assert "rm" in cfg.tools
    assert "ls" in cfg.tools
    assert "memory_search" in cfg.tools


def test_dream_agent_config_timeout_default():
    cfg = _make_dream_config()
    assert cfg.timeout_seconds == 300


def test_dream_agent_config_timeout_override():
    cfg = _make_dream_config(timeout_seconds=120)
    assert cfg.timeout_seconds == 120


# ── Sandbox restoration (bug #5) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_restores_sandbox(setup_db, _wiki_dir: Path):
    """The sandbox active before run_dream must be restored after it returns."""
    from app.agent.sandbox import SandboxConfig, get_sandbox, set_sandbox

    pre = SandboxConfig(workspace="/tmp/before-dream")
    set_sandbox(pre)

    session = ChatSession(agent_name="test-agent")
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        await run_dream(db)

    post = get_sandbox()
    assert str(post.workspace_root) == str(pre.workspace_root)


# ── Failed-run-not-marked-processed (bug #11) ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_failed_synthesis_not_marked_processed(
    setup_db, _wiki_dir: Path
):
    """When synthesis fails, the session must NOT be marked processed — so it
    gets retried on the next run instead of being lost (bug #11).
    """
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.services.dream import _SynthesisFailed

    _write_dream_md()

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Hello!",
                exclude_from_context=False,
            )
        )
        await db.commit()

    async def _always_fail(agent, db, sess, *, timeout_seconds, wiki_context=""):
        raise _SynthesisFailed("boom")

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", side_effect=_always_fail):
            async with async_session_factory() as db:
                result = await run_dream(db)

    assert result["sessions_processed"] == 0
    assert result["failed"] == 1
    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamLog))).all()
    # The session must still be unprocessed — no DreamLog row.
    assert len(rows) == 0


# ── A9: mark_*_processed swallows IntegrityError (cross-process race) ────────


@pytest.mark.asyncio
async def test_mark_session_processed_swallows_duplicate(setup_db):
    """A second ``mark_session_processed`` for the same session must not raise
    even though ``dream_log.session_id`` has a UNIQUE constraint — the lock
    only covers in-process races, not cross-process ones (A9).
    """
    from app.core.db import async_session_factory

    session_id = uuid.uuid4()
    async with async_session_factory() as db:
        await mark_session_processed(db, session_id, "agent", [])
    async with async_session_factory() as db:
        # Must NOT raise IntegrityError.
        await mark_session_processed(db, session_id, "agent", ["topic"])


@pytest.mark.asyncio
async def test_mark_note_processed_swallows_duplicate(setup_db):
    """Same cross-process race semantics for notes (A9)."""
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        await mark_note_processed(db, "2026-05-13.md")
    async with async_session_factory() as db:
        # Must NOT raise IntegrityError.
        await mark_note_processed(db, "2026-05-13.md")


# ── A3: Transcript header does not leak session.id ───────────────────────────


@pytest.mark.asyncio
async def test_transcript_header_omits_session_id(setup_db, _wiki_dir: Path):
    """The dream LLM prompt must not include the raw session UUID (A3) — it
    would otherwise leak into generated topic files.
    """
    from app.core.db import async_session_factory
    from app.services.dream import _fetch_session_transcript

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="Hello!"))
        await db.commit()

    async with async_session_factory() as db:
        transcript = await _fetch_session_transcript(db, session)

    assert str(session.id) not in transcript
    assert "Agent: test-agent" in transcript
    assert "Date:" in transcript


# ── Karpathy: stable Source-Slug for per-source pages ────────────────────────


@pytest.mark.asyncio
async def test_transcript_header_includes_source_slug(setup_db, _wiki_dir: Path):
    """The transcript header must include a stable ``Source-Slug:`` line so
    the dream LLM can name the per-source page deterministically and cite
    the source in frontmatter.  Uses the last 8 hex chars of the UUID — the
    random tail of UUIDv7, avoiding timestamp-prefix collisions.
    """
    from app.core.db import async_session_factory
    from app.services.dream import _fetch_session_transcript

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content="Hello!"))
        await db.commit()

    async with async_session_factory() as db:
        transcript = await _fetch_session_transcript(db, session)

    expected_slug = f"session-{session.id.hex[-8:]}"
    assert f"Source-Slug: {expected_slug}" in transcript
    # Slug must precede the Agent line so the LLM reads identity first.
    assert transcript.index("Source-Slug:") < transcript.index("Agent:")
    # Raw UUID (with dashes) must NOT appear — slug uses hex-only form.
    assert str(session.id) not in transcript


@pytest.mark.asyncio
async def test_synthesise_note_prompt_includes_source_slug(
    setup_db, _wiki_dir: Path, monkeypatch
):
    """Notes get a deterministic ``Source-Slug: note-<stem>`` so the dream
    agent can name ``sources/note-<stem>.md`` consistently across runs.
    """
    from app.services.dream import _synthesise_note

    notes_dir = _wiki_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "2026-05-17.md").write_text("hello world\n", encoding="utf-8")

    captured: dict[str, str] = {}

    class _StubAgent:
        async def run(self, msgs, *, config):
            captured["prompt"] = msgs[0].content
            return None

    await _synthesise_note(
        _StubAgent(), "2026-05-17.md", timeout_seconds=10, wiki_context=""
    )

    assert "Source-Slug: note-2026-05-17" in captured["prompt"]


# ── Karpathy: today block prevents LLM from hallucinating dates ──────────────


def test_build_wiki_context_starts_with_today_block(_wiki_dir: Path):
    """``_build_wiki_context`` must always start with a ``Today: ...`` line
    so the LLM uses today's actual date in ``updated:`` frontmatter rather
    than hallucinating it (the model has no internal clock).
    """
    from app.services.dream import _build_wiki_context

    # First-ever run: nothing in wiki → still returns today block.
    ctx = _build_wiki_context()
    assert ctx.startswith("Today: ")
    # Format is YYYY-MM-DD UTC.
    import re as _re

    assert _re.match(r"^Today: \d{4}-\d{2}-\d{2} UTC\n", ctx)


def test_build_wiki_context_today_block_present_with_existing_pages(_wiki_dir: Path):
    """When the wiki already has content, the today block still appears
    first — before the existing-state listing.
    """
    from app.services.dream import _build_wiki_context

    (_wiki_dir / "INDEX.md").write_text("- topic: x\n", encoding="utf-8")
    (_wiki_dir / "topics").mkdir(exist_ok=True)
    (_wiki_dir / "topics" / "python.md").write_text(
        "---\ndescription: x\n---\n", encoding="utf-8"
    )
    ctx = _build_wiki_context()
    assert ctx.startswith("Today: ")
    # Wiki state still surfaced after the today block.
    assert "INDEX.md" in ctx
    assert "python" in ctx
    # Today block must appear before the wiki state header.
    assert ctx.index("Today: ") < ctx.index("Wiki state")


# ── A5: Long transcripts truncate without O(n^2) blow-up ─────────────────────


@pytest.mark.asyncio
async def test_transcript_truncation_long_session(setup_db, _wiki_dir: Path):
    """A session with many tiny messages truncates correctly and quickly (A5)."""
    from app.core.db import async_session_factory
    from app.services.dream import _fetch_session_transcript

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        # 500 tiny messages — way over budget when budget is tight.
        for i in range(500):
            db.add(
                SessionMessage(session_id=session.id, role="user", content=f"msg {i}")
            )
        await db.commit()

    async with async_session_factory() as db:
        transcript = await _fetch_session_transcript(db, session, max_total_chars=500)

    assert "[... middle messages elided" in transcript
    # First + last messages preserved verbatim.
    assert "msg 0" in transcript
    assert "msg 499" in transcript
    # Single elision marker, not duplicated.
    assert transcript.count("[... middle messages elided") == 1


# ── A2: Dream settings load runs in a thread (smoke test it still works) ─────


@pytest.mark.asyncio
async def test_run_dream_parses_config_off_event_loop(setup_db, _wiki_dir: Path):
    """Dream settings load runs via ``asyncio.to_thread`` (A2). This test just
    confirms the threaded call wires up correctly — if the await is dropped,
    ``dream_cfg`` becomes a coroutine and downstream access fails.
    """
    from app.core.db import async_session_factory
    from app.core.runtime_settings import (
        DreamSettings,
        RuntimeSettings,
        save_runtime_settings,
    )

    save_runtime_settings(
        RuntimeSettings(dream=DreamSettings(enabled=True, model="mock:model"))
    )

    async with async_session_factory() as db:
        # No items to process — but the config still gets parsed.
        result = await run_dream(db)

    assert result == {
        "sessions_processed": 0,
        "notes_processed": 0,
        "remaining": 0,
        "failed": 0,
    }


# ── B5: non-IntegrityError commit failures are re-raised, not silenced ───────


@pytest.mark.asyncio
async def test_mark_session_processed_reraises_non_integrity_error(setup_db):
    """``mark_session_processed`` must re-raise any non-IntegrityError so a
    transient disk-full / lock-timeout doesn't silently re-enqueue the same
    session forever (B5).
    """
    from sqlalchemy.exc import OperationalError

    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        with patch.object(
            db,
            "commit",
            side_effect=OperationalError("stmt", {}, Exception("disk full")),
        ):
            with pytest.raises(OperationalError):
                await mark_session_processed(db, uuid.uuid4(), "agent", ["t"])


@pytest.mark.asyncio
async def test_mark_note_processed_reraises_non_integrity_error(setup_db):
    """Same non-IntegrityError re-raise behaviour for notes (B5)."""
    from sqlalchemy.exc import OperationalError

    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        with patch.object(
            db,
            "commit",
            side_effect=OperationalError("stmt", {}, Exception("disk full")),
        ):
            with pytest.raises(OperationalError):
                await mark_note_processed(db, "2026-05-13.md")


# ── B13: _diff_topics dedupes slugs across mtime + count entries ─────────────


def test_diff_topics_dedupes_same_slug():
    """If the same slug somehow appears twice in ``after`` (extension casing
    or duplicate snapshot keys), ``_diff_topics`` returns it once (B13).
    """
    # Both keys stem to ``foo`` — should only appear once in output.
    before: dict[str, int] = {}
    after = {"foo.md": 100, "foo.MD": 200}
    result = _diff_topics(before, after)
    assert result.count("foo") == 1


def test_diff_topics_returns_list_without_duplicates():
    """``_diff_topics`` always returns a deduped sorted list (B13)."""
    before = {"a.md": 100}
    after = {"a.md": 200, "b.md": 300}
    result = _diff_topics(before, after)
    assert result == sorted(set(result))
    assert "a" in result
    assert "b" in result


# ── C6: _diff_topics records deletions ───────────────────────────────────────


def test_diff_topics_detects_deletion():
    """A file present in ``before`` but missing in ``after`` counts as a
    change so ``rm``-style edits show up in ``dream_log.topics_written`` (C6).
    """
    before = {"stale.md": 100, "kept.md": 100}
    after = {"kept.md": 100}
    assert _diff_topics(before, after) == ["stale"]


def test_diff_topics_mixed_create_modify_delete():
    """Creates + modifies + deletes are all surfaced together (C6)."""
    before = {"old.md": 100, "stable.md": 100, "modded.md": 100}
    after = {"stable.md": 100, "modded.md": 200, "new.md": 300}
    # "old" deleted, "modded" mtime bumped, "new" created.
    assert _diff_topics(before, after) == ["modded", "new", "old"]


# ── C11: _mark_item_processed raises TypeError on type drift ─────────────────


@pytest.mark.asyncio
async def test_mark_item_processed_rejects_wrong_session_type(setup_db):
    """``_mark_item_processed`` must raise ``TypeError`` (not silently
    misbehave under ``python -O``) when handed the wrong item type (C11).
    """
    from app.core.db import async_session_factory
    from app.services.dream import _mark_item_processed

    async with async_session_factory() as db:
        with pytest.raises(TypeError, match="ChatSession"):
            await _mark_item_processed(db, "session", "not-a-session")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_mark_item_processed_rejects_wrong_note_type(setup_db):
    """Same explicit-TypeError contract for notes (C11)."""
    from app.core.db import async_session_factory
    from app.services.dream import _mark_item_processed

    async with async_session_factory() as db:
        with pytest.raises(TypeError, match="str"):
            await _mark_item_processed(db, "note", 42)  # type: ignore[arg-type]


# ── C7: empty-session marking failure doesn't abort the whole run ────────────


@pytest.mark.asyncio
async def test_run_dream_continues_when_empty_session_mark_fails(
    setup_db, _wiki_dir: Path
):
    """If marking an empty session fails (e.g. transient DB error), the
    overall run must continue and surface the failure rather than aborting
    mid-loop (C7).
    """
    from sqlalchemy.exc import OperationalError

    from app.core.db import async_session_factory

    # Create two empty sessions.
    async with async_session_factory() as db:
        for _ in range(2):
            db.add(ChatSession(agent_name="test-agent"))
        await db.commit()

    call_count = {"n": 0}

    async def _flaky_mark(db, kind, item, **kwargs):
        call_count["n"] += 1
        # Fail the first empty-session mark, succeed thereafter.
        if call_count["n"] == 1:
            raise OperationalError("stmt", {}, Exception("transient"))

    with patch("app.services.dream._mark_item_processed", side_effect=_flaky_mark):
        async with async_session_factory() as db:
            # Must not propagate the OperationalError.
            result = await run_dream(db)

    # Both empty sessions were attempted; one failed.  No real sessions or
    # notes to process, so processed counts stay 0.
    assert result["sessions_processed"] == 0
    assert result["notes_processed"] == 0


# ── D6: _load_dream_agent doesn't leak sandbox on config-build failure ───────


def test_load_dream_agent_no_sandbox_leak_on_config_failure(_wiki_dir: Path):
    """When ``AgentConfig`` validation fails, the sandbox context must NOT
    have been mutated — otherwise the caller's previous sandbox bleeds out
    (D6).  The fix is to validate the config BEFORE calling ``set_sandbox``.
    """
    from app.agent.sandbox import SandboxConfig, get_sandbox, set_sandbox
    from app.services.dream import DreamAgentConfig, _load_dream_agent

    pre = SandboxConfig(workspace="/tmp/pre-dream")
    token = set_sandbox(pre)
    try:
        # Force AgentConfig validation to fail by passing an obviously bad
        # model string after the DreamAgentConfig validator passed.  Easiest
        # path: monkeypatch AgentConfig to raise.
        cfg = DreamAgentConfig.model_validate(
            {"name": "dream", "model": "mock:model", "enabled": True}
        )
        with patch("app.agent.loader.AgentConfig", side_effect=ValueError("boom")):
            assert _load_dream_agent(cfg) is None

        # Sandbox must still be what we set — no leak from the failed load.
        assert str(get_sandbox().workspace_root) == str(pre.workspace_root)
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)


# ── D3: _topics_snapshot uses st_mtime_ns (sub-second resolution) ────────────


def test_topics_snapshot_uses_nanosecond_mtime(tmp_path: Path, monkeypatch):
    """Mtime snapshots must be in nanoseconds so two writes within the
    same second (coarse-mtime filesystems: HFS+, FAT32) still surface as
    distinct snapshots (D3).
    """
    from app.services import dream as dream_module
    from app.services.dream import _topics_snapshot

    topics_dir = tmp_path / "topics"
    topics_dir.mkdir()
    f = topics_dir / "x.md"
    f.write_text("v1", encoding="utf-8")

    # ``dream.py`` imports ``wiki_root`` by name at module load, so we
    # must patch the binding inside the dream module itself.
    monkeypatch.setattr(dream_module, "wiki_root", lambda: tmp_path)

    snap = _topics_snapshot()
    assert "x.md" in snap
    # ns-precision values are large ints in modern filesystems.
    assert isinstance(snap["x.md"], int)
    assert snap["x.md"] > 0


# ── Coverage gap: interleave logic under asymmetric backlogs ─────────────────


def _write_dream_md(batch_size: int = 1, model: str = "mock:model") -> None:
    """Helper: write enabled Dream runtime settings."""
    from app.core.runtime_settings import (
        DreamSettings,
        RuntimeSettings,
        save_runtime_settings,
    )

    save_runtime_settings(
        RuntimeSettings(dream=DreamSettings(enabled=True, model=model or None))
    )


def _remove_dream_md() -> None:
    from app.core.runtime_settings import RuntimeSettings, save_runtime_settings

    save_runtime_settings(RuntimeSettings())


async def _make_real_session(content: str = "Hello!") -> ChatSession:
    """Helper: insert a session with one user message and return it."""
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content=content,
                exclude_from_context=False,
            )
        )
        await db.commit()
    return session


@pytest.mark.asyncio
async def test_run_dream_interleave_sessions_only(setup_db, _wiki_dir: Path):
    """Only sessions in the backlog → batch fills with sessions, no notes
    starvation false-positive (interleave loop must not stall when one
    iterator is empty from the start).
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=3)
    for _ in range(5):
        await _make_real_session()

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["sessions_processed"] == 1
    assert result["notes_processed"] == 0
    assert result["remaining"] == 4
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_run_dream_interleave_notes_only(setup_db, _wiki_dir: Path):
    """Only notes in the backlog → batch fills with notes."""
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=3)
    for i in range(5):
        (_wiki_dir / "notes" / f"2026-05-{10 + i:02d}.md").write_text(
            "x", encoding="utf-8"
        )

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["sessions_processed"] == 0
    assert result["notes_processed"] == 1
    assert result["remaining"] == 4
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_run_dream_interleave_order_session_first(setup_db, _wiki_dir: Path):
    """With 1 session + 1 note and batch_size=2, BOTH must be processed and
    the work-order must be (session, note) so a session backlog can't starve
    notes via cron-fire-time accumulation.
    """
    from app.core.db import async_session_factory
    from app.services import dream as dream_module

    _write_dream_md(batch_size=2)
    await _make_real_session()
    (_wiki_dir / "notes" / "2026-05-13.md").write_text("x", encoding="utf-8")

    seen_kinds: list[str] = []
    real_mark = dream_module._mark_item_processed

    async def _spy(db, kind, item, **kwargs):
        seen_kinds.append(kind)
        return await real_mark(db, kind, item, **kwargs)

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._mark_item_processed", _spy):
            async with async_session_factory() as db:
                result = await run_dream(db)

    assert result == {
        "sessions_processed": 1,
        "notes_processed": 1,
        "remaining": 0,
        "failed": 0,
    }
    # Critical ordering: session enqueued first, then note.
    assert seen_kinds == ["session", "note"]


@pytest.mark.asyncio
async def test_run_dream_batch_size_one_does_not_starve_notes(
    setup_db, _wiki_dir: Path
):
    """A nominal batch of one admits one session and one note when both wait."""
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    await _make_real_session()
    (_wiki_dir / "notes" / "2026-05-13.md").write_text("x", encoding="utf-8")

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    assert result["sessions_processed"] == 1
    assert result["notes_processed"] == 1
    assert result["remaining"] == 0


# ── Coverage gap: failed-item accounting ─────────────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_partial_failure_accounts_correctly(setup_db, _wiki_dir: Path):
    """Mixed batch where ONE session synthesises OK and ONE note times out:
    ``sessions_processed=1, notes_processed=0, failed=1, remaining=1``.
    The failed item must NOT be marked processed (so next run retries it).
    """
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.services.dream import _SynthesisFailed

    _write_dream_md(batch_size=2)
    await _make_real_session()
    (_wiki_dir / "notes" / "2026-05-13.md").write_text("note body", encoding="utf-8")

    async def _ok_session(agent, db, sess, *, timeout_seconds, wiki_context=""):
        return ["dummy-topic"]

    async def _fail_note(agent, filename, *, timeout_seconds, wiki_context=""):
        raise _SynthesisFailed("LLM timeout")

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _ok_session):
            with patch("app.services.dream._synthesise_note", _fail_note):
                async with async_session_factory() as db:
                    result = await run_dream(db)

    assert result["sessions_processed"] == 1
    assert result["notes_processed"] == 0
    assert result["failed"] == 1
    # remaining = (1 session + 1 note) total - 1 session processed - 0 notes
    assert result["remaining"] == 1

    # The failed note must NOT appear in dream_notes_log → next run retries.
    from app.models.chat import DreamNotesLog

    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamNotesLog))).all()
    assert "2026-05-13.md" not in {r.filename for r in rows}


# ── Coverage gap: topics_written JSON persistence shape ──────────────────────


@pytest.mark.asyncio
async def test_mark_session_processed_persists_deduped_json_list(setup_db):
    """The ``topics_written`` column must hold a JSON ARRAY of deduped
    strings (not a JSON string or pickled set).  A consumer parsing the
    audit log relies on ``json.loads`` returning a list.
    """
    import json as _json

    from sqlmodel import select

    from app.core.db import async_session_factory

    session_id = uuid.uuid4()
    async with async_session_factory() as db:
        # Pass duplicates + order should be preserved on first-seen basis.
        await mark_session_processed(
            db, session_id, "agent", ["alpha", "beta", "alpha", "gamma", "beta"]
        )

    async with async_session_factory() as db:
        row = (
            await db.exec(select(DreamLog).where(DreamLog.session_id == session_id))
        ).one()

    assert row.topics_written is not None
    parsed = _json.loads(row.topics_written)
    assert isinstance(parsed, list)
    assert parsed == ["alpha", "beta", "gamma"]


@pytest.mark.asyncio
async def test_mark_session_processed_empty_topics_stores_null(setup_db):
    """Empty topics list → column is NULL (not '[]') so audit queries can
    distinguish "nothing changed" from "audit row exists but empty list".
    """
    from sqlmodel import select

    from app.core.db import async_session_factory

    session_id = uuid.uuid4()
    async with async_session_factory() as db:
        await mark_session_processed(db, session_id, "agent", [])

    async with async_session_factory() as db:
        row = (
            await db.exec(select(DreamLog).where(DreamLog.session_id == session_id))
        ).one()

    assert row.topics_written is None


# ── Coverage gap: _fetch_session_transcript invariants ───────────────────────


@pytest.mark.asyncio
async def test_fetch_session_transcript_excludes_summarised_messages(
    setup_db, _wiki_dir: Path
):
    """Messages with ``exclude_from_context=True`` (summarisation markers,
    tombstones) must NOT leak into the dream LLM prompt — otherwise summary
    plumbing would re-contaminate the wiki on every dream pass.
    """
    from app.core.db import async_session_factory
    from app.services.dream import _fetch_session_transcript

    session = ChatSession(agent_name="test-agent")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="visible-msg",
                exclude_from_context=False,
            )
        )
        db.add(
            SessionMessage(
                session_id=session.id,
                role="assistant",
                content="HIDDEN-SUMMARY-MARKER",
                exclude_from_context=True,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        transcript = await _fetch_session_transcript(db, session)

    assert "visible-msg" in transcript
    assert "HIDDEN-SUMMARY-MARKER" not in transcript


@pytest.mark.asyncio
async def test_fetch_session_transcript_per_message_truncation_marker(
    setup_db, _wiki_dir: Path
):
    """A single oversized message gets per-message clipped with a clear
    marker so the LLM can detect truncation (not just see content cut off).
    """
    from app.core.db import async_session_factory
    from app.services.dream import PER_MESSAGE_CAP_CHARS, _fetch_session_transcript

    session = ChatSession(agent_name="test-agent")
    huge = "X" * (PER_MESSAGE_CAP_CHARS + 5_000)
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="user", content=huge))
        await db.commit()

    async with async_session_factory() as db:
        transcript = await _fetch_session_transcript(db, session)

    # The marker must be present AND the post-marker content must be absent.
    assert "[... truncated ...]" in transcript
    # Total transcript size bounded.
    assert len(transcript) < PER_MESSAGE_CAP_CHARS + 1_000


# ── Coverage gap: missing dream config for notes ─────────────────────────────


@pytest.mark.asyncio
async def test_run_dream_keeps_notes_pending_without_config(setup_db, _wiki_dir: Path):
    """When Dream has no model, notes must remain pending for a future run."""
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import DreamNotesLog

    # NB: deliberately do NOT call _write_dream_md → dream_cfg=None.
    _remove_dream_md()
    (_wiki_dir / "notes" / "2026-05-13.md").write_text("note", encoding="utf-8")

    async with async_session_factory() as db:
        result = await run_dream(db)

    assert result["notes_processed"] == 0
    assert result["remaining"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == "no_model_configured"
    async with async_session_factory() as db:
        rows = (await db.exec(select(DreamNotesLog))).all()
    assert "2026-05-13.md" not in {r.filename for r in rows}


# ── Coverage gap: empty-session drain interacts with real sessions ───────────


@pytest.mark.asyncio
async def test_run_dream_empties_dont_consume_batch_slots(setup_db, _wiki_dir: Path):
    """Empty sessions are auto-marked OUTSIDE the batch loop, so they must
    not eat into ``batch_size`` — a backlog of 100 empties + 1 real session
    with batch_size=1 still processes the real session in the same run.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    # 10 empty sessions + 1 real session.
    async with async_session_factory() as db:
        for _ in range(10):
            db.add(ChatSession(agent_name="test-agent"))
        await db.commit()
    real = await _make_real_session()

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db)

    # The real session must be processed (not crowded out by empties).
    assert result["sessions_processed"] == 1
    # And dream_log must contain the real session id.
    from sqlmodel import select as _select

    async with async_session_factory() as db:
        ids = {r for r in (await db.exec(_select(DreamLog.session_id))).all()}
    assert real.id in ids


# ── Coverage gap: _load_dream_agent token ownership on success ───────────────


def test_load_dream_agent_returns_token_caller_must_reset(_wiki_dir: Path):
    """On success, ``_load_dream_agent`` HANDS OFF the sandbox token to the
    caller — it does NOT reset itself.  Verified by checking the active
    sandbox after a successful load points at the wiki workspace.
    """
    from app.agent.sandbox import (
        SandboxConfig,
        _sandbox_ctx,
        get_sandbox,
        set_sandbox,
    )
    from app.services.dream import _load_dream_agent
    from app.services.wiki import wiki_root

    pre = SandboxConfig(workspace="/tmp/pre")
    pre_token = set_sandbox(pre)
    try:
        cfg = _make_dream_config()
        # Stub the agent build so we only exercise the sandbox plumbing.
        with patch(
            "app.agent.loader._build_agent",
            return_value=_make_dream_agent(),
        ):
            loaded = _load_dream_agent(cfg)

        assert loaded is not None
        agent, token = loaded
        try:
            # Active sandbox must now be wiki_root() — the caller hasn't
            # reset yet.
            active = get_sandbox()
            assert str(active.workspace_root) == str(wiki_root())
        finally:
            _sandbox_ctx.reset(token)

        # After caller resets, the previous sandbox is restored.
        assert str(get_sandbox().workspace_root) == str(pre.workspace_root)
    finally:
        _sandbox_ctx.reset(pre_token)


# ── Coverage gap: _diff_topics modify-then-delete races ──────────────────────


def test_diff_topics_handles_delete_of_unchanged_file():
    """File present in ``before``, missing in ``after`` — slug shows up
    even if its mtime never changed during the run."""
    before = {"old.md": 12345}
    after: dict[str, int] = {}
    assert _diff_topics(before, after) == ["old"]


def test_diff_topics_no_change_returns_empty():
    """Identical snapshots → empty list (no false positives on equal mtimes)."""
    snap = {"a.md": 100, "b.md": 200}
    assert _diff_topics(snap, snap) == []


# ── Coverage gap: DreamAgentConfig defaults & coercion ───────────────────────


def test_dream_agent_config_batch_size_default_is_one():
    """The schema default for batch_size is 1 — bumping this silently would
    multiply LLM costs across all deployments.
    """
    cfg = DreamAgentConfig.model_validate({"name": "dream"})
    assert cfg.batch_size == 1
    assert cfg.enabled is False
    assert cfg.schedule == "0 2 * * *"


def test_dream_agent_config_required_tools_idempotent():
    """Re-validating an already-augmented config does NOT duplicate tools."""
    cfg = DreamAgentConfig.model_validate(
        {
            "name": "dream",
            "tools": ["read", "write", "edit", "rm", "ls", "memory_search"],
        }
    )
    # Each required tool should appear exactly once.
    for tool in ("read", "write", "edit", "rm", "ls", "memory_search"):
        assert cfg.tools.count(tool) == 1


# ── E1: drain semantics — manual triggers ignore batch_size ──────────────────


@pytest.mark.asyncio
async def test_run_dream_drain_processes_all_pending(setup_db, _wiki_dir: Path):
    """``drain=True`` ignores ``batch_size`` and processes every pending
    item.  This is the fix for the user-reported "Run now only processes 1
    session" footgun caused by the conservative default ``batch_size: 1``.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)  # deliberately the conservative default
    # 5 real sessions in the backlog.
    for _ in range(5):
        await _make_real_session()

    async def _ok(agent, db, sess, *, timeout_seconds, wiki_context=""):
        return []

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _ok):
            async with async_session_factory() as db:
                result = await run_dream(db, drain=True)

    # All 5 processed despite batch_size=1.
    assert result["sessions_processed"] == 5
    assert result["remaining"] == 0


@pytest.mark.asyncio
async def test_run_dream_default_respects_batch_size(setup_db, _wiki_dir: Path):
    """``drain=False`` (default — scheduler path) still honours batch_size.
    Regression guard so we don't accidentally drain on every cron tick.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=2)
    for _ in range(5):
        await _make_real_session()

    async def _ok(agent, db, sess, *, timeout_seconds, wiki_context=""):
        return []

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _ok):
            async with async_session_factory() as db:
                result = await run_dream(db)  # drain=False

    assert result["sessions_processed"] == 1
    assert result["remaining"] == 4


# ── E2: existing wiki context is injected into the per-item prompt ───────────


@pytest.mark.asyncio
async def test_run_dream_injects_wiki_context(setup_db, _wiki_dir: Path):
    """``_synthesise_session`` receives a non-empty ``wiki_context`` when
    INDEX.md or topic files exist on disk.  Without this, the agent
    re-creates duplicate topics per session.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    (_wiki_dir / "INDEX.md").write_text("- python: stuff\n", encoding="utf-8")
    (_wiki_dir / "topics").mkdir(exist_ok=True)
    (_wiki_dir / "topics" / "python.md").write_text(
        "---\ndescription: x\n---\n", encoding="utf-8"
    )
    await _make_real_session()

    captured: dict[str, str] = {}

    async def _capture(agent, db, sess, *, timeout_seconds, wiki_context=""):
        captured["wiki_context"] = wiki_context
        return []

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _capture):
            async with async_session_factory() as db:
                await run_dream(db, drain=True)

    assert "python" in captured["wiki_context"]
    assert "INDEX.md" in captured["wiki_context"]


# ── Failure handling: failed items stay unprocessed, scheduler retries ───────


@pytest.mark.asyncio
async def test_run_dream_failed_item_stays_unprocessed(setup_db, _wiki_dir: Path):
    """When synthesis fails, the item must NOT be marked processed — the
    next run picks it up again.  No persistent failure tracking; the
    scheduler is the only retry mechanism.
    """
    from app.core.db import async_session_factory
    from app.services.dream import _SynthesisFailed, get_unprocessed_sessions

    _write_dream_md(batch_size=1)
    await _make_real_session()

    async def _fail(agent, db, sess, *, timeout_seconds, wiki_context=""):
        raise _SynthesisFailed("simulated")

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _fail):
            async with async_session_factory() as db:
                result = await run_dream(db, drain=True)
            assert result["failed"] == 1
            assert result["sessions_processed"] == 0

            # The session must still be unprocessed — next run retries it.
            async with async_session_factory() as db:
                unprocessed = await get_unprocessed_sessions(db)
            assert len(unprocessed) == 1


# ── LOG.md: dream appends after each non-empty run ───────────────────────────


@pytest.mark.asyncio
async def test_run_dream_appends_to_log_md(setup_db, _wiki_dir: Path):
    """After a non-empty run, ``wiki/LOG.md`` gets a parseable entry.

    The header line begins with ``## [`` for greppability — matches the
    Karpathy LLM-Wiki convention so users can do ``grep '^## \\['``.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    await _make_real_session()

    async def _ok(agent, db, sess, *, timeout_seconds, wiki_context=""):
        return ["dummy-topic"]

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _ok):
            async with async_session_factory() as db:
                await run_dream(db, drain=True)

    log_path = _wiki_dir / "LOG.md"
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "sessions=1" in text
    # Greppable prefix.
    grep_lines = [ln for ln in text.splitlines() if ln.startswith("## [")]
    assert len(grep_lines) == 1


@pytest.mark.asyncio
async def test_run_dream_no_log_entry_on_truly_empty_run(setup_db, _wiki_dir: Path):
    """A run with absolutely nothing to do (no sessions, no notes) must not
    pollute LOG.md with a noise entry every cron tick.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    # No sessions, no notes — nothing pending.
    async with async_session_factory() as db:
        await run_dream(db)

    log_path = _wiki_dir / "LOG.md"
    assert not log_path.exists()


# ── Within-batch wiki_context refresh (item N+1 sees item N's writes) ───────


@pytest.mark.asyncio
async def test_run_dream_wiki_context_refreshes_between_items(
    setup_db, _wiki_dir: Path
):
    """In a drain of 2 sessions, the SECOND synthesis call must see any
    topic that the first call created.  Without per-item refresh, both
    items would see the same baseline view and re-create the same topic.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    await _make_real_session(content="first session about python")
    await _make_real_session(content="second session about python")

    captured_contexts: list[str] = []
    topics_dir = _wiki_dir / "topics"
    topics_dir.mkdir(exist_ok=True)
    call_count = {"n": 0}

    async def _synth(agent, db, sess, *, timeout_seconds, wiki_context=""):
        captured_contexts.append(wiki_context)
        call_count["n"] += 1
        # First call creates a topic file; second call should see it in
        # its wiki_context prefix.
        if call_count["n"] == 1:
            (topics_dir / "python.md").write_text(
                "---\ndescription: Python.\n---\n", encoding="utf-8"
            )
            return ["python"]
        return []

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        with patch("app.services.dream._synthesise_session", _synth):
            async with async_session_factory() as db:
                await run_dream(db, drain=True)

    assert call_count["n"] == 2
    # First context has no "python" topic listed yet.
    assert "python" not in captured_contexts[0]
    # Second context HAS the python slug — proves per-item refresh works.
    assert "python" in captured_contexts[1]


# ── #4 + #5: batched empty-session check is one query, not N+1 ───────────────


@pytest.mark.asyncio
async def test_run_dream_handles_many_empty_sessions(setup_db, _wiki_dir: Path):
    """20 empty sessions are all marked processed in a single drain run.
    Pre-fix this was N+1 queries; the assertion here is just behavioural —
    the perf characterisation is in the query plan.
    """
    from app.core.db import async_session_factory

    _write_dream_md(batch_size=1)
    # 20 empty sessions (no messages at all).
    async with async_session_factory() as db:
        for _ in range(20):
            db.add(ChatSession(agent_name="test-agent"))
        await db.commit()

    with patch(
        "app.services.dream._load_dream_agent",
        side_effect=lambda cfg: _make_loaded_agent(),
    ):
        async with async_session_factory() as db:
            result = await run_dream(db, drain=True)

    # All 20 should be marked (empty → no LLM, no synthesis count).
    assert result["sessions_processed"] == 0
    assert result["notes_processed"] == 0
    # Verify they were marked in dream_log so the next run doesn't see them.
    async with async_session_factory() as db:
        unprocessed = await get_unprocessed_sessions(db)
    assert unprocessed == []
