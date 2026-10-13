"""Tests for visualize tools."""

import pytest

from app.agent.tools.builtin.visualize.read_me import visualize_read_me
from app.agent.tools.builtin.visualize.show_widget import show_widget
from app.agent.tools.builtin.visualize.ui_block import ui_block


class TestVisualizeReadMe:
    """Test visualize_read_me tool."""

    @pytest.mark.asyncio
    async def test_single_module(self):
        result = await visualize_read_me(modules=["interactive"])
        assert isinstance(result, str)
        assert "Interactive Components" in result

    @pytest.mark.asyncio
    async def test_multiple_modules(self):
        result = await visualize_read_me(modules=["interactive", "chart"])
        assert isinstance(result, str)
        assert "Interactive Components" in result
        assert "Chart.js Integration" in result

    @pytest.mark.asyncio
    async def test_invalid_module(self):
        result = await visualize_read_me(modules=["invalid"])
        assert isinstance(result, str)
        assert "Invalid modules" in result
        assert "interactive" in result

    @pytest.mark.asyncio
    async def test_empty_modules(self):
        result = await visualize_read_me(modules=[])
        assert isinstance(result, str)
        # Empty modules returns invalid modules message
        assert "Invalid modules" in result

    @pytest.mark.asyncio
    async def test_gallery_module(self):
        result = await visualize_read_me(modules=["gallery"])
        assert isinstance(result, str)
        assert "Widget Gallery" in result
        assert "Metric Dashboard" in result


class TestShowWidget:
    """Test show_widget tool."""

    @pytest.mark.asyncio
    async def test_basic_widget(self):
        result = await show_widget(
            title="test_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=True,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["title"] == "test_widget"

    @pytest.mark.asyncio
    async def test_requires_read_me(self):
        result = await show_widget(
            title="test_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=False,
        )
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_custom_dimensions(self):
        result = await show_widget(
            title="custom_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=True,
            width=1000,
            height=500,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert result["width"] == 1000
        assert result["height"] == 500

    @pytest.mark.asyncio
    async def test_html_content_preserved(self):
        html = "<div class='test'><p>Hello World</p></div>"
        result = await show_widget(
            title="html_widget",
            loading_messages=["Loading..."],
            widget_code=html,
            i_have_seen_read_me=True,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert result["widget_code"] == html


class TestUiBlock:
    """Test ui_block tool (Feature B, spec §9.3)."""

    @staticmethod
    def _capture(monkeypatch):
        pushed: list = []

        async def capture(session_id, envelope):
            pushed.append((session_id, envelope))

        monkeypatch.setattr("app.services.memory_stream_store.push_event", capture)
        return pushed

    @pytest.mark.asyncio
    async def test_valid_blocks_push_single_envelope(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[
                {"type": "stat_cards", "cards": [{"label": "CPU", "value": 42}]},
                {"type": "progress", "label": "Upload", "value": 1, "max": 4},
            ],
            title="my_stats",
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-1",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert result["block_count"] == 2
        assert result["types"] == ["stat_cards", "progress"]

        assert len(pushed) == 1
        session_id, envelope = pushed[0]
        assert session_id == "sess-1"
        assert envelope.event == "ui_block"
        assert envelope.data["type"] == "ui_block"
        assert envelope.data["tool_call_id"] == "call-1"
        assert envelope.data["agent"] == "lead"
        assert envelope.data["is_final"] is True
        assert envelope.data["metadata"]["title"] == "my_stats"
        assert len(envelope.data["blocks"]) == 2

    @pytest.mark.asyncio
    async def test_blocks_as_json_string_is_normalized(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks='[{"type": "progress", "label": "l", "value": 1, "max": 2}]',
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-2",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert result["block_count"] == 1
        assert len(pushed) == 1
        assert pushed[0][1].data["blocks"][0]["type"] == "progress"

    @pytest.mark.asyncio
    async def test_malformed_json_string_returns_error(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks="{not json",
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-3",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is False
        assert "JSON array" in result["error"]
        assert pushed == []  # never raises, never pushes a broken frame

    @pytest.mark.asyncio
    async def test_unknown_block_type_lists_valid_types(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[{"type": "timeline", "entries": []}],
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-4",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is False
        assert "timeline" in result["error"]
        assert set(result["valid_types"]) == {
            "stat_cards",
            "chart",
            "steps",
            "table",
            "key_value",
            "callout",
            "buttons",
            "form",
            "progress",
            "flashcards",
            "checklist",
            "calculator",
        }
        assert pushed == []

    @pytest.mark.asyncio
    async def test_more_than_six_blocks_rejected(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        blocks = [
            {"type": "progress", "label": f"l{i}", "value": i, "max": 9}
            for i in range(7)
        ]
        result = await ui_block(
            blocks=blocks,
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-5",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is False
        assert "error" in result
        assert pushed == []

    @pytest.mark.asyncio
    async def test_over_limit_row_count_rejected(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        blocks = [
            {
                "type": "table",
                "columns": [{"k": "K"}],
                "rows": [{"k": str(i)} for i in range(201)],
            }
        ]
        result = await ui_block(
            blocks=blocks,
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-6",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is False
        assert "rows" in result["error"]
        assert pushed == []

    @pytest.mark.asyncio
    async def test_push_failure_is_logged_not_raised(self, monkeypatch):
        async def boom(session_id, envelope):
            raise RuntimeError("push exploded")

        monkeypatch.setattr("app.services.memory_stream_store.push_event", boom)
        result = await ui_block(
            blocks=[{"type": "callout", "tone": "success", "body": "done"}],
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-7",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert result["pushed"] is False

    @pytest.mark.asyncio
    async def test_missing_tool_call_id_still_pushes_one_envelope(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[{"type": "callout", "tone": "success", "body": "done"}],
            _injected={
                "agent_name": "lead",
                "tool_call_id": "",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert len(pushed) == 1
        assert pushed[0][1].data["tool_call_id"] == ""

    @pytest.mark.asyncio
    async def test_arun_merges_injected_context(self, monkeypatch):
        """Production path: Tool.arun merges the InjectedArg params."""
        pushed = self._capture(monkeypatch)
        result = await ui_block.arun(
            blocks=[{"type": "key_value", "pairs": [{"k": "v"}]}],
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-8",
                "session_id": "sess-9",
            },
        )
        assert result["success"] is True
        assert len(pushed) == 1
        assert pushed[0][0] == "sess-9"
        assert pushed[0][1].data["tool_call_id"] == "call-8"

    @pytest.mark.asyncio
    async def test_no_session_skips_push_without_crash(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[{"type": "steps", "steps": [{"title": "s"}]}],
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-9",
                "session_id": "",
            },
        )
        assert result["success"] is True
        assert result["pushed"] is False
        assert pushed == []

    @pytest.mark.asyncio
    async def test_guidance_fields_accepted(self, monkeypatch):
        """Form/steps description, field helper, and buttons hint validate and
        round-trip through the pushed envelope (all optional, spec §5.1)."""
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[
                {
                    "type": "steps",
                    "description": "Follow these four steps to launch your first project.",
                    "steps": [
                        {"title": "Create a project", "status": "done"},
                        {"title": "Add a repository", "status": "active"},
                    ],
                },
                {
                    "type": "form",
                    "title": "project_intake",
                    "description": (
                        "Your answers are sent to the agent as one message — "
                        "it replies right in this chat."
                    ),
                    "fields": [
                        {
                            "name": "goal",
                            "label": "Goal",
                            "helper": "One sentence: what should the agent build?",
                        }
                    ],
                    "submit_label": "Send answers",
                },
                {
                    "type": "buttons",
                    "buttons": [{"label": "Approve", "prompt": "approve"}],
                    "hint": "Each button sends that message to the agent.",
                },
            ],
            title="guided_demo",
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-10",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert result["types"] == ["steps", "form", "buttons"]
        assert len(pushed) == 1
        blocks = pushed[0][1].data["blocks"]
        assert blocks[0]["description"].startswith("Follow these four steps")
        assert blocks[1]["description"].startswith("Your answers are sent")
        assert blocks[1]["fields"][0]["helper"].startswith("One sentence")
        assert blocks[2]["hint"] == "Each button sends that message to the agent."

    @pytest.mark.asyncio
    async def test_guidance_fields_over_length_rejected(self, monkeypatch):
        """Each new guidance field is capped: 240 for block descriptions,
        160 for field helper / buttons hint."""
        pushed = self._capture(monkeypatch)
        overlong = [
            (
                {"type": "steps", "steps": [{"title": "s"}], "description": "x" * 241},
                "description",
            ),
            (
                {
                    "type": "form",
                    "fields": [{"name": "a", "label": "A"}],
                    "description": "x" * 241,
                },
                "description",
            ),
            (
                {
                    "type": "form",
                    "fields": [{"name": "a", "label": "A", "helper": "x" * 161}],
                },
                "helper",
            ),
            (
                {
                    "type": "buttons",
                    "buttons": [{"label": "Go", "prompt": "go"}],
                    "hint": "x" * 161,
                },
                "hint",
            ),
        ]
        for block, field_name in overlong:
            result = await ui_block(
                blocks=[block],
                _injected={
                    "agent_name": "lead",
                    "tool_call_id": "call-11",
                    "session_id": "sess-1",
                },
            )
            assert result["success"] is False, block["type"]
            assert field_name in result["error"]
        assert pushed == []

    @pytest.mark.asyncio
    async def test_interactive_blocks_accepted(self, monkeypatch):
        """flashcards / checklist / calculator round-trip through the pushed
        envelope (spec §5.1 catalog additions)."""
        pushed = self._capture(monkeypatch)
        result = await ui_block(
            blocks=[
                {
                    "type": "flashcards",
                    "title": "Quiz",
                    "cards": [
                        {
                            "front": "What does CPU throttling mean?",
                            "back": "The CPU reducing clock speed to stay cool.",
                        },
                        {
                            "front": "What is RAM?",
                            "back": "Fast, volatile working memory.",
                        },
                    ],
                },
                {
                    "type": "checklist",
                    "title": "Roast ingredients",
                    "description": "Everything you need before you start.",
                    "items": [
                        {
                            "label": "Lamb",
                            "detail": "shoulder, 3.6 kg",
                            "checked": True,
                        },
                        {"label": "Potatoes"},
                    ],
                },
                {
                    "type": "calculator",
                    "description": "Split the bill evenly.",
                    "inputs": [
                        {"name": "total", "label": "Total", "value": 90.0, "unit": "$"},
                        {
                            "name": "people",
                            "label": "People",
                            "value": 3,
                            "min": 1,
                            "step": 1,
                        },
                    ],
                    "outputs": [
                        {
                            "label": "Each pays",
                            "formula": "total / people",
                            "unit": "$",
                            "decimals": 2,
                        },
                    ],
                },
            ],
            title="interactive_demo",
            _injected={
                "agent_name": "lead",
                "tool_call_id": "call-20",
                "session_id": "sess-1",
            },
        )
        assert result["success"] is True
        assert result["types"] == ["flashcards", "checklist", "calculator"]
        assert len(pushed) == 1
        blocks = pushed[0][1].data["blocks"]
        assert blocks[0]["cards"][0]["front"].startswith("What does CPU")
        assert blocks[1]["items"][0]["checked"] is True
        assert blocks[2]["outputs"][0]["formula"] == "total / people"

    @pytest.mark.asyncio
    async def test_calculator_showcase_examples_validate(self, monkeypatch):
        """The two catalog examples — bill split and roast planner — pass."""
        self._capture(monkeypatch)
        examples = [
            # Bill split: total / people
            {
                "type": "calculator",
                "inputs": [
                    {"name": "total", "label": "Total", "value": 90},
                    {"name": "people", "label": "People", "value": 3},
                ],
                "outputs": [{"label": "Each", "formula": "total / people"}],
            },
            # Roast planner: per-guest amounts
            {
                "type": "calculator",
                "inputs": [{"name": "guests", "label": "Guests", "value": 8}],
                "outputs": [
                    {"label": "Lamb", "formula": "guests*0.45", "unit": "kg"},
                    {"label": "Potatoes", "formula": "guests * 0.5", "unit": "kg"},
                ],
            },
        ]
        for block in examples:
            result = await ui_block(
                blocks=[block],
                _injected={
                    "agent_name": "lead",
                    "tool_call_id": "call-21",
                    "session_id": "sess-1",
                },
            )
            assert result["success"] is True, block["outputs"]

    @pytest.mark.asyncio
    async def test_calculator_unsafe_formulas_rejected(self, monkeypatch):
        """Formulas outside the safe grammar (numbers, input names, + - * / ( ))
        are rejected server-side with a message naming the output."""
        pushed = self._capture(monkeypatch)
        bad_formulas = [
            "alert(1)",  # function call
            "eval(total)",  # function call
            "total ** 2",  # exponent operator not in grammar
            "__import__(total)",  # dunder call
            "total; people",  # statement separator
            "total, people",  # comma
            "tax * 2",  # unknown input reference
            "(total + 1",  # unbalanced parens
            "total /",  # trailing operator
            "",  # empty
            "`total`",  # backticks
            "total\t+ 1\n#",  # comment/hash
        ]
        for formula in bad_formulas:
            result = await ui_block(
                blocks=[
                    {
                        "type": "calculator",
                        "inputs": [
                            {"name": "total", "label": "T", "value": 1},
                            {"name": "people", "label": "P", "value": 2},
                        ],
                        "outputs": [{"label": "Bad", "formula": formula}],
                    }
                ],
                _injected={
                    "agent_name": "lead",
                    "tool_call_id": "call-22",
                    "session_id": "sess-1",
                },
            )
            assert result["success"] is False, repr(formula)
            # Field-level errors (e.g. empty formula) name the field path;
            # validator errors name the output label.
            assert "Bad" in result["error"] or "formula" in result["error"], repr(
                formula
            )
        assert pushed == []

    @pytest.mark.asyncio
    async def test_calculator_duplicate_and_bad_input_names_rejected(self, monkeypatch):
        pushed = self._capture(monkeypatch)
        blocks = [
            # Duplicate input names
            {
                "type": "calculator",
                "inputs": [
                    {"name": "x", "label": "A", "value": 1},
                    {"name": "x", "label": "B", "value": 2},
                ],
                "outputs": [{"label": "L", "formula": "x"}],
            },
            # Input name must be a lowercase identifier
            {
                "type": "calculator",
                "inputs": [{"name": "Total Amount!", "label": "T", "value": 1}],
                "outputs": [{"label": "L", "formula": "1"}],
            },
        ]
        for block in blocks:
            result = await ui_block(
                blocks=[block],
                _injected={
                    "agent_name": "lead",
                    "tool_call_id": "call-23",
                    "session_id": "sess-1",
                },
            )
            assert result["success"] is False, block
        assert pushed == []

    @pytest.mark.asyncio
    async def test_interactive_blocks_limits_enforced(self, monkeypatch):
        """Card/item caps and empty-list rejection match the catalog limits."""
        pushed = self._capture(monkeypatch)
        limited = [
            (
                {"type": "flashcards", "cards": [{"front": "f", "back": "b"}] * 21},
                "flashcards",
            ),
            (
                {"type": "checklist", "items": [{"label": "i"}] * 41},
                "checklist",
            ),
            (
                {"type": "checklist", "items": []},
                "checklist",
            ),
            (
                {
                    "type": "calculator",
                    "inputs": [{"name": "a", "label": "A", "value": 1}],
                    "outputs": [],
                },
                "calculator",
            ),
        ]
        for block, type_name in limited:
            result = await ui_block(
                blocks=[block],
                _injected={
                    "agent_name": "lead",
                    "tool_call_id": "call-24",
                    "session_id": "sess-1",
                },
            )
            assert result["success"] is False, type_name
        assert pushed == []
