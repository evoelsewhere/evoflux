"""Tests for SkillPreloadHook."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.skill_preload import SkillPreloadHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.agent.state import AgentState


def _make_state(messages=None):
    return AgentState(messages=messages or [])


def _make_ctx(agent_name="test-agent"):
    return SimpleNamespace(agent_name=agent_name, session_id=None, run_id="r1")


class TestSkillPreloadHook:
    @pytest.mark.asyncio
    async def test_injects_after_first_human_message(self):
        hook = SkillPreloadHook({"my-skill": "Do the thing."})
        state = _make_state([HumanMessage(content="Hello")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # Should be: [HumanMessage, AssistantMessage(tool_calls), ToolMessage]
        assert len(state.messages) == 3
        assert isinstance(state.messages[0], HumanMessage)
        assert isinstance(state.messages[1], AssistantMessage)
        assert state.messages[1].tool_calls is not None
        assert len(state.messages[1].tool_calls) == 1
        assert state.messages[1].tool_calls[0].function.name == "skill"
        assert isinstance(state.messages[2], ToolMessage)
        assert state.messages[2].content == "Do the thing."
        assert state.messages[2].name == "skill"

    @pytest.mark.asyncio
    async def test_multiple_skills_single_assistant_message(self):
        hook = SkillPreloadHook({"a": "Body A", "b": "Body B"})
        state = _make_state([HumanMessage(content="Hi")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # [HumanMessage, AssistantMessage(2 tool_calls), ToolMessage, ToolMessage]
        assert len(state.messages) == 4
        assert isinstance(state.messages[1], AssistantMessage)
        assert len(state.messages[1].tool_calls) == 2
        assert isinstance(state.messages[2], ToolMessage)
        assert isinstance(state.messages[3], ToolMessage)
        bodies = {state.messages[2].content, state.messages[3].content}
        assert bodies == {"Body A", "Body B"}

    @pytest.mark.asyncio
    async def test_no_injection_when_skills_already_in_history(self):
        from app.agent.schemas.chat import FunctionCall, ToolCall

        hook = SkillPreloadHook({"my-skill": "Body"})
        existing_tc = ToolCall(
            id="old_1",
            function=FunctionCall(name="skill", arguments='{"skill_name":"my-skill"}'),
        )
        state = _make_state(
            [
                HumanMessage(content="Hi"),
                AssistantMessage(content=None, tool_calls=[existing_tc]),
                ToolMessage(tool_call_id="old_1", name="skill", content="Body"),
            ]
        )
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # No new messages injected
        assert len(state.messages) == 3

    @pytest.mark.asyncio
    async def test_no_injection_when_no_human_message(self):
        hook = SkillPreloadHook({"my-skill": "Body"})
        state = _make_state([])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        assert len(state.messages) == 0

    @pytest.mark.asyncio
    async def test_seeds_loaded_skills_metadata(self):
        hook = SkillPreloadHook({"my-skill": "Do stuff."})
        state = _make_state([HumanMessage(content="Hi")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        assert state.metadata.get("loaded_skills") == {"my-skill": "Do stuff."}

    @pytest.mark.asyncio
    async def test_noop_with_empty_skills(self):
        hook = SkillPreloadHook({})
        state = _make_state([HumanMessage(content="Hi")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        assert len(state.messages) == 1

    @pytest.mark.asyncio
    async def test_preserves_existing_messages_after_human(self):
        hook = SkillPreloadHook({"sk": "Body"})
        state = _make_state(
            [
                HumanMessage(content="First"),
                AssistantMessage(content="Reply"),
                HumanMessage(content="Second"),
            ]
        )
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # Injected after first HumanMessage
        assert isinstance(state.messages[0], HumanMessage)
        assert state.messages[0].content == "First"
        assert isinstance(state.messages[1], AssistantMessage)
        assert state.messages[1].tool_calls is not None  # synthetic
        assert isinstance(state.messages[2], ToolMessage)
        # Original messages follow
        assert isinstance(state.messages[3], AssistantMessage)
        assert state.messages[3].content == "Reply"
        assert isinstance(state.messages[4], HumanMessage)
        assert state.messages[4].content == "Second"
