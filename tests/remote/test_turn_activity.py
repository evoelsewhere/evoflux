"""Tests for app/remote/turn_activity.py — turn tool-call activity summary.

``app.models.chat`` has no ``ChatMessage`` model (the brief's interface
section names one, but the real persisted-message table is
``SessionMessage`` — see ``app/models/chat.py``); its fields
(``session_id``, ``role``, ``tool_calls``, ``tool_call_id``, ``content``,
``created_at``) match what the brief's test exercises, so this test targets
the real model instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.chat import ChatSession, SessionMessage
from app.remote.turn_activity import load_turn_activity


@pytest_asyncio.fixture
async def db_session():
    async with db_module.async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def chat_session(db_session):
    session = ChatSession(title="Turn activity test session")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest.mark.asyncio
async def test_load_turn_activity_counts_tool_calls_and_builds_diff(
    db_session, chat_session
):
    since = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add_all(
        [
            SessionMessage(
                session_id=chat_session.id,
                role="assistant",
                tool_calls=[{"name": "write", "arguments": {"path": "a.py"}}],
                created_at=since + timedelta(milliseconds=10),
            ),
            SessionMessage(
                session_id=chat_session.id,
                role="tool",
                tool_call_id="1",
                content="wrote a.py (+5 -1)",
                created_at=since + timedelta(milliseconds=20),
            ),
            SessionMessage(
                session_id=chat_session.id,
                role="assistant",
                tool_calls=[{"name": "read", "arguments": {"path": "b.py"}}],
                created_at=since + timedelta(milliseconds=30),
            ),
        ]
    )
    await db_session.commit()

    activity = await load_turn_activity(db_session, str(chat_session.id), since=since)

    assert activity.tool_call_count == 2
    assert "write" in activity.diff_text
    assert "read" not in activity.diff_text
    assert "read" in activity.tool_log_text


@pytest.mark.asyncio
async def test_load_turn_activity_with_no_tool_calls_returns_placeholders(
    db_session, chat_session
):
    since = datetime.now(UTC) - timedelta(seconds=1)

    activity = await load_turn_activity(db_session, str(chat_session.id), since=since)

    assert activity.tool_call_count == 0
    assert activity.summary_lines == []
    assert activity.tool_log_text == "No tool calls."
    assert activity.diff_text == "No file changes."


@pytest.mark.asyncio
async def test_load_turn_activity_with_non_uuid_session_id_returns_placeholders(
    db_session,
):
    """A non-UUID session id (e.g. a test double's placeholder) can never
    match a persisted row, so this returns empty activity instead of
    raising — exercised because outbound.py's ``_finalize_turn`` calls this
    for every turn, including ones whose session_id isn't a real UUID."""
    since = datetime.now(UTC) - timedelta(seconds=1)

    activity = await load_turn_activity(db_session, "sess-1", since=since)

    assert activity.tool_call_count == 0
    assert activity.tool_log_text == "No tool calls."
    assert activity.diff_text == "No file changes."


@pytest.mark.asyncio
async def test_load_turn_activity_ignores_messages_before_since(
    db_session, chat_session
):
    since = datetime.now(UTC)
    db_session.add(
        SessionMessage(
            session_id=chat_session.id,
            role="assistant",
            tool_calls=[{"name": "write", "arguments": {"path": "old.py"}}],
            created_at=since - timedelta(seconds=10),
        )
    )
    await db_session.commit()

    activity = await load_turn_activity(db_session, str(chat_session.id), since=since)

    assert activity.tool_call_count == 0
