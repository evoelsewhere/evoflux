"""Invariant tests for deterministic, explicit-only skill selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.explicit_skill_selection import ExplicitSkillSelectionHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
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
    state = _state(HumanMessage(content="/skill:work-writing Draft this memo"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"work-writing"}
    assert isinstance(state.messages[1], AssistantMessage)
    assert state.messages[1].tool_calls[0].id.startswith("explicit_")
    assert isinstance(state.messages[2], ToolMessage)


@pytest.mark.asyncio
async def test_codex_dollar_directive_loads_exact_selected_skill():
    state = _state(HumanMessage(content="$work-writing Draft this memo"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"work-writing"}
    assert isinstance(state.messages[1], AssistantMessage)
    assert isinstance(state.messages[2], ToolMessage)


@pytest.mark.asyncio
async def test_openai_default_prompt_dollar_mention_loads_selected_skill():
    state = _state(HumanMessage(content="Use $work-writing to draft this memo."))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"work-writing"}


@pytest.mark.asyncio
async def test_coding_investigation_default_prompt_loads_only_in_coding_mode():
    state = _state(
        HumanMessage(
            content=("Use $coding-investigation to find callers of calculate_total.")
        )
    )
    state.tool_names = ["code_context", "code_context"]

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)
    assert len(state.messages) == 1

    state.metadata["team_mode"] = "coding"
    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert set(state.metadata["loaded_skills"]) == {"coding-investigation"}


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
async def test_canonical_visible_activation_is_not_injected_twice():
    state = _state(
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="load_work_writing",
                    function=FunctionCall(
                        name="skill",
                        arguments='{"action":"load","skill_name":"work-writing"}',
                    ),
                )
            ],
        ),
        ToolMessage(
            tool_call_id="load_work_writing",
            name="skill",
            content='<skill_content name="work-writing">Instructions.</skill_content>',
        ),
        HumanMessage(content="/skill:work-writing Draft this memo"),
    )

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 3
    assert set(state.metadata["loaded_skills"]) == {"work-writing"}
    assert state.metadata["explicit_skill_selected"] == "work-writing"


@pytest.mark.asyncio
async def test_stale_loaded_metadata_does_not_suppress_explicit_activation():
    state = _state(HumanMessage(content="/skill:work-writing Draft this memo"))
    state.metadata["loaded_skills"] = {"work-writing": "stale activation"}

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 3
    assert "<skill_content" in (state.messages[2].content or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "result"),
    [
        (
            '{"action":"load","skill_name":"work-writing"}',
            "Could not load skill 'work-writing'.",
        ),
        (
            '{"action":"list","skill_name":"work-writing"}',
            "work-writing: Professional writing workflow",
        ),
        (
            '{"action":"read_resource","skill_name":"work-writing","resource_path":"x"}',
            '<skill_content name="work-writing">Not an activation result.</skill_content>',
        ),
    ],
)
async def test_irrelevant_skill_calls_do_not_suppress_explicit_activation(
    arguments, result
):
    state = _state(
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="irrelevant_work_writing",
                    function=FunctionCall(name="skill", arguments=arguments),
                )
            ],
        ),
        ToolMessage(
            tool_call_id="irrelevant_work_writing",
            name="skill",
            content=result,
        ),
        HumanMessage(content="/skill:work-writing Draft this memo"),
    )

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 5
    assert state.messages[3].tool_calls[0].id.startswith("explicit_")
    assert "<skill_content" in (state.messages[4].content or "")


@pytest.mark.asyncio
async def test_excluded_historical_activation_does_not_suppress_selection():
    old_call = AssistantMessage(
        content=None,
        tool_calls=[
            ToolCall(
                id="old_work_writing",
                function=FunctionCall(
                    name="skill",
                    arguments='{"action":"load","skill_name":"work-writing"}',
                ),
            )
        ],
        exclude_from_context=True,
    )
    old_result = ToolMessage(
        tool_call_id="old_work_writing",
        name="skill",
        content='<skill_content name="work-writing">Old instructions.</skill_content>',
        exclude_from_context=True,
    )
    state = _state(
        old_call,
        old_result,
        HumanMessage(content="/skill:work-writing Draft this memo"),
    )

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 5
    assert state.messages[3].tool_calls[0].id.startswith("explicit_")


@pytest.mark.asyncio
async def test_unknown_explicit_skill_is_non_destructive():
    state = _state(HumanMessage(content="/skill:no-such-skill do it"))

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)

    assert len(state.messages) == 1


@pytest.mark.asyncio
async def test_explicit_skill_respects_application_mode():
    state = _state(
        HumanMessage(content="/skill:coding-investigation Trace enable_webbridge")
    )
    state.tool_names = ["code_context", "code_context"]

    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)
    assert len(state.messages) == 1

    state.metadata["team_mode"] = "coding"
    await ExplicitSkillSelectionHook().before_agent(_ctx(), state)
    assert set(state.metadata["loaded_skills"]) == {"coding-investigation"}


def test_nested_selector_uses_settings_notation():
    discovered = {"git/commit": {"dir": "/tmp/git/commit"}}

    assert (
        ExplicitSkillSelectionHook._resolve_name("git:commit", discovered)
        == "git/commit"
    )
