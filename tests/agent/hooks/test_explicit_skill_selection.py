"""Invariant tests for deterministic, explicit-only skill selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.explicit_skill_selection import ExplicitSkillSelectionHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.agent.state import AgentState


def _state(*messages) -> AgentState:
    return AgentState(messages=list(messages))


def _ctx():
    return SimpleNamespace(agent_name="test-agent", session_id=None, run_id="run")


@pytest.mark.asyncio
async def test_normal_request_never_routes_by_keywords():
    state = _state(HumanMessage(content="Research and write a report with charts"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 1
    assert state.metadata.get("loaded_skills") is None


@pytest.mark.asyncio
async def test_explicit_directive_loads_selected_skill():
    state = _state(HumanMessage(content="/skill:pdf Inspect this PDF"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"pdf"}
    assert isinstance(state.messages[1], AssistantMessage)
    assert state.messages[1].tool_calls[0].id.startswith("explicit_")
    assert isinstance(state.messages[2], ToolMessage)


@pytest.mark.asyncio
async def test_directive_after_quote_context_uses_latest_user_message():
    state = _state(
        HumanMessage(content="Earlier"),
        AssistantMessage(content="Response"),
        HumanMessage(
            content="> quoted context\n\n/skill:self-healing Update the agent"
        ),
    )

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"self-healing"}
    assert isinstance(state.messages[3], AssistantMessage)
    assert isinstance(state.messages[4], ToolMessage)


@pytest.mark.asyncio
async def test_loaded_skill_is_not_injected_twice():
    state = _state(HumanMessage(content="/skill:pdf Inspect this PDF"))
    state.metadata["loaded_skills"] = {"pdf": "already loaded"}

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 1


@pytest.mark.asyncio
async def test_unknown_explicit_skill_is_non_destructive():
    state = _state(HumanMessage(content="/skill:no-such-skill do it"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 1


def test_nested_selector_uses_settings_notation():
    discovered = {"git/commit": {"dir": "/tmp/git/commit"}}

    assert (
        ExplicitSkillSelectionHook._resolve_name("git:commit", discovered)
        == "git/commit"
    )
