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

    @pytest.mark.asyncio
    async def test_pptx_intent_outranks_generic_technical_verbs(self):
        """A slide request should not route by incidental design/test verbs."""
        hook = SkillAutoRoutingHook()
        state = _make_state(
            [
                HumanMessage(
                    content=(
                        "làm slide pptx giới thiệu EvoFlux, gồm các giai đoạn "
                        "Assess, Understand, Design, Convert, Test Compare và Cutover"
                    )
                )
            ]
        )

        await hook.before_agent(_make_ctx(), state)

        assert set(state.metadata.get("loaded_skills", {})) == {"pptx"}

    def test_explicit_description_triggers_are_extracted(self, tmp_path):
        skill_dir = tmp_path / "slides"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: slides
description: Create, design, and test a presentation. Triggers on PPTX, PowerPoint, or slide.
---
Body
""",
            encoding="utf-8",
        )

        assert extract_triggers(skill_dir) == ["pptx", "powerpoint", "slide"]

    def test_pptx_skill_routes_from_description(self):
        skill_dir = _builtin_skills_dir() / "pptx"

        assert extract_triggers(skill_dir) == ["pptx", "powerpoint", "slide"]

    @pytest.mark.parametrize(
        ("skill_name", "expected"),
        [
            ("docx", ["docx", "word document", "word template"]),
            ("xlsx", ["xlsx", "xlsm", "spreadsheet", "workbook", "csv", "tsv"]),
            (
                "doc-coauthoring",
                [
                    "co-author a document",
                    "co-write a proposal",
                    "draft a technical spec",
                ],
            ),
        ],
    )
    def test_builtin_skills_route_from_explicit_description_terms(
        self, skill_name, expected
    ):
        assert extract_triggers(_builtin_skills_dir() / skill_name) == expected

    def test_trigger_marker_does_not_match_whenever_prefix(self, tmp_path):
        skill_dir = tmp_path / "spreadsheet"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: spreadsheet
description: Trigger whenever a spreadsheet is the deliverable.
---
Body
""",
            encoding="utf-8",
        )

        assert extract_triggers(skill_dir) == []

    def test_description_prose_does_not_infer_action_triggers(self, tmp_path):
        skill_dir = tmp_path / "builder"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: builder
description: Create, design, build, and test production artifacts.
---
Body
""",
            encoding="utf-8",
        )

        assert extract_triggers(skill_dir) == []

    def test_score_message_basic(self):
        """Single-word alternatives produce a stable relevance score."""
        triggers = ["debug", "error", "bug", "fix"]
        score = SkillAutoRoutingHook._score_message("debug the error", triggers)
        assert score == 1.0

    def test_score_message_all_match(self):
        """Multiple synonyms do not inflate or dilute specificity."""
        triggers = ["test", "implement"]
        score = SkillAutoRoutingHook._score_message("test and implement", triggers)
        assert score == 1.0

    def test_score_message_prefers_specific_phrase(self):
        triggers = ["document", "draft a technical spec"]

        score = SkillAutoRoutingHook._score_message(
            "Please draft a technical specification for this API", triggers
        )

        assert score == 4.0

    def test_score_message_is_not_diluted_by_alternative_formats(self):
        triggers = ["xlsx", "xlsm", "spreadsheet", "workbook", "csv", "tsv"]

        assert SkillAutoRoutingHook._score_message("Analyze this CSV", triggers) == 1.0

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
        hook._trigger_data = {
            "test-skill": ["deploy", "launch", "release", "production"]
        }
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
            function=FunctionCall(name="skill", arguments='{"skill_name":"my-skill"}'),
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
            function=FunctionCall(name="skill", arguments='{"skill_name":"skill-a"}'),
        )
        tc2 = ToolCall(
            id="tc2",
            function=FunctionCall(name="skill", arguments='{"skill_name":"skill-b"}'),
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
