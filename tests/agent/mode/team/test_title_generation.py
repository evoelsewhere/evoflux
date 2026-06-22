"""Tests for title generation in team chat mode."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid7

import pytest

from app.agent.agent_loop import Agent
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam
from app.agent.schemas.chat import HumanMessage
from app.models.chat import ChatSession
from tests.agent.mode.team.conftest import MockTeamProvider


def _make_db_factory_with_session(session_row: ChatSession):
    """Create a mock async session factory that returns the given session row."""
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.get = AsyncMock(return_value=session_row)
    mock_db.exec = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_db.add = MagicMock()

    @asynccontextmanager
    async def factory():
        yield mock_db

    return factory, mock_db


@pytest.mark.asyncio
async def test_ensure_db_session_sets_title_when_existing_session_is_empty():
    """If the session row exists but has no title, _ensure_db_session fills it."""
    session_uuid = uuid7()
    session_row = ChatSession(id=session_uuid, title="", agent_name="lead")
    db_factory, mock_db = _make_db_factory_with_session(session_row)

    lead = TeamLead(
        Agent(name="lead", llm_provider=MockTeamProvider("OK")),
        db_factory=db_factory,
    )
    lead.session_id = str(session_uuid)

    await lead._ensure_db_session(title="Plan a trip to Japan", mode="normal")

    assert session_row.title == "Plan a trip to Japan"
    assert session_row.mode == "normal"
    mock_db.add.assert_called()
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_title_hook_is_added_for_lead_on_first_turn(monkeypatch):
    """The lead's hook list includes TitleGenerationHook on the first turn."""
    session_uuid = uuid7()
    session_id = str(session_uuid)
    session_row = ChatSession(id=session_uuid, title="", agent_name="lead")
    db_factory, _ = _make_db_factory_with_session(session_row)
    provider = MockTeamProvider("OK lead")
    captured_hooks: list = []

    async def fake_run(*_args, **kwargs):
        captured_hooks.extend(kwargs.get("hooks", []))
        return []

    lead = TeamLead(Agent(name="lead", llm_provider=provider), db_factory=db_factory)
    lead.session_id = session_id
    team = AgentTeam(
        lead=lead, provider_factory=lambda m, **_: provider, db_factory=db_factory
    )
    lead.register(team)

    # Seed history with a single user message so before_agent sees a first turn.
    monkeypatch.setattr(
        "app.agent.mode.team.member.get_messages_for_llm",
        AsyncMock(return_value=[HumanMessage(content="Write a sorting algorithm")]),
    )
    monkeypatch.setattr(lead.agent, "run", fake_run)

    await lead._handle_messages()

    from app.agent.hooks.title_generation import TitleGenerationHook

    assert any(isinstance(h, TitleGenerationHook) for h in captured_hooks)


@pytest.mark.asyncio
async def test_title_generation_spawns_for_first_user_message():
    """TitleGenerationHook.before_agent spawns generate_and_save_title on first turn."""
    from app.agent.hooks.title_generation import TitleGenerationHook

    provider = MockTeamProvider("title response")
    hook = TitleGenerationHook(
        provider=provider,
        db_factory=MagicMock(),
        system_prompt="Generate a title",
    )

    from app.agent.state import AgentState, RunContext

    ctx = RunContext(session_id=str(uuid7()), run_id="r1", agent_name="lead")
    state = AgentState(messages=[HumanMessage(content="Write a sorting algorithm")])

    with patch(
        "app.services.title_service.generate_and_save_title",
        new_callable=AsyncMock,
    ) as mock_gen:
        await hook.before_agent(ctx, state)
        assert hook._task is not None
        await hook._task

        mock_gen.assert_awaited_once()
        assert mock_gen.call_args.kwargs["user_message"] == "Write a sorting algorithm"
        assert mock_gen.call_args.kwargs["provider"] is provider
