"""Tests for SkillAutoRoutingHook."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.skill_auto_routing import SkillAutoRoutingHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from app.agent.state import AgentState
from app.agent.tools.builtin.skill import _builtin_skills_dir, extract_triggers


def _make_state(messages=None):
    return AgentState(messages=messages or [])


def _make_ctx(agent_name="test-agent"):
    return SimpleNamespace(agent_name=agent_name, session_id=None, run_id="r1")


class TestSkillAutoRoutingHook:
    """Tests for the SkillAutoRoutingHook class."""

    def test_score_message_basic(self):
        """Triggers found in message should increase score."""
        triggers = ["debug", "error", "bug", "fix"]
        score = SkillAutoRoutingHook._score_message("debug the error", triggers)
        assert score == 0.5  # 2/4

    def test_score_message_all_match(self):
        """All triggers matching should give score 1.0."""
        triggers = ["test", "implement"]
        score = SkillAutoRoutingHook._score_message("test and implement", triggers)
        assert score == 1.0

    def test_score_message_no_match(self):
        """No triggers matching should give score 0.0."""
        triggers = ["deploy", "launch"]
        score = SkillAutoRoutingHook._score_message("write documentation", triggers)
        assert score == 0.0

    def test_score_message_empty_triggers(self):
        """Empty triggers list should give score 0.0."""
        score = SkillAutoRoutingHook._score_message("anything", [])
        assert score == 0.0

    def test_score_message_prefix_matching(self):
        """Triggers should use prefix matching (test matches testing)."""
        triggers = ["test"]
        score = SkillAutoRoutingHook._score_message("testing the code", triggers)
        assert score == 1.0

    def test_score_message_no_false_positives(self):
        """Triggers should not match partial words (fix should not match suffix)."""
        triggers = ["fix"]
        score = SkillAutoRoutingHook._score_message("suffix of the string", triggers)
        assert score == 0.0

    @pytest.mark.parametrize(
        "message",
        [
            "show the code graph",
            "find callers of process_event",
            "run change impact analysis",
            "trace a dependency path through the code graph",
        ],
    )
    def test_code_graph_navigation_common_intents_clear_default_threshold(
        self, message
    ):
        """Keep the bundled skill's trigger list focused enough to auto-route."""
        skill_dir = _builtin_skills_dir() / "code-graph-navigation"
        triggers = extract_triggers(skill_dir)

        score = SkillAutoRoutingHook._score_message(message, triggers)

        assert score > 0.3

    @pytest.mark.asyncio
    async def test_no_injection_when_no_human_message(self):
        """Should not inject when there are no human messages."""
        hook = SkillAutoRoutingHook()
        # Mock trigger data
        hook._trigger_data = {"test-skill": ["test", "debug"]}
        state = _make_state([AssistantMessage(content="Hello")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # No new messages injected
        assert len(state.messages) == 1

    @pytest.mark.asyncio
    async def test_no_injection_when_no_trigger_data(self):
        """Should not inject when trigger data is empty."""
        hook = SkillAutoRoutingHook()
        hook._trigger_data = {}
        state = _make_state([HumanMessage(content="debug the bug")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # No new messages injected
        assert len(state.messages) == 1

    @pytest.mark.asyncio
    async def test_no_injection_when_below_threshold(self):
        """Should not inject when no skill scores above threshold."""
        hook = SkillAutoRoutingHook(threshold=0.5)
        hook._trigger_data = {"test-skill": ["deploy", "launch", "release", "production"]}
        state = _make_state([HumanMessage(content="debug the code")])
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # No new messages injected (only "debug" vs 4 triggers = 0.25)
        assert len(state.messages) == 1

    @pytest.mark.asyncio
    async def test_no_double_load(self):
        """Should not load skills already in message history."""
        hook = SkillAutoRoutingHook()
        hook._trigger_data = {"my-skill": ["test"]}

        existing_tc = ToolCall(
            id="old_1",
            function=FunctionCall(
                name="skill", arguments='{"skill_name":"my-skill"}'
            ),
        )
        state = _make_state(
            [
                HumanMessage(content="test the code"),
                AssistantMessage(content=None, tool_calls=[existing_tc]),
                ToolMessage(tool_call_id="old_1", name="skill", content="Body"),
            ]
        )
        ctx = _make_ctx()

        await hook.before_agent(ctx, state)

        # No new messages injected
        assert len(state.messages) == 3

    def test_loaded_from_messages(self):
        """Should extract skill names from message history."""
        tc1 = ToolCall(
            id="tc1",
            function=FunctionCall(
                name="skill", arguments='{"skill_name":"skill-a"}'
            ),
        )
        tc2 = ToolCall(
            id="tc2",
            function=FunctionCall(
                name="skill", arguments='{"skill_name":"skill-b"}'
            ),
        )
        tc3 = ToolCall(
            id="tc3",
            function=FunctionCall(name="other_tool", arguments="{}"),
        )
        state = _make_state(
            [
                AssistantMessage(content=None, tool_calls=[tc1, tc2, tc3]),
            ]
        )

        loaded = SkillAutoRoutingHook._loaded_from_messages(state)
        assert loaded == {"skill-a", "skill-b"}

    def test_loaded_from_messages_empty(self):
        """Should return empty set when no skill calls in history."""
        state = _make_state(
            [
                AssistantMessage(content="Hello", tool_calls=[]),
            ]
        )

        loaded = SkillAutoRoutingHook._loaded_from_messages(state)
        assert loaded == set()

    def test_find_insertion_index(self):
        """Should find index after first HumanMessage."""
        state = _make_state(
            [
                AssistantMessage(content="Hello"),
                HumanMessage(content="Hi there"),
                AssistantMessage(content="Response"),
            ]
        )

        idx = SkillAutoRoutingHook._find_insertion_index(state)
        assert idx == 2  # After the HumanMessage at index 1

    def test_find_insertion_index_no_human(self):
        """Should return None when no HumanMessage exists."""
        state = _make_state(
            [
                AssistantMessage(content="Hello"),
            ]
        )

        idx = SkillAutoRoutingHook._find_insertion_index(state)
        assert idx is None
