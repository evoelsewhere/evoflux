"""ui_block tool acceptance of layout/custom blocks (spec §2.4/§3.1, Stream 2).

The tool must accept the new `layout` and `custom` block types and push one
validated `ui_block` envelope. Server-side schema limits (invalid orientation,
too many sections/children, out-of-bounds html/height) surface as friendly
tool errors with no event pushed.
"""

from typing import Any

import pytest

from app.agent.tools.builtin.visualize.ui_block import ui_block


def _injected(call_id: str = "call-1") -> dict[str, str]:
    return {
        "agent_name": "lead",
        "tool_call_id": call_id,
        "session_id": "sess-1",
    }


class TestUiBlockComposition:
    @pytest.fixture
    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        pushed: list[Any] = []

        async def capture(session_id: str, envelope: Any) -> None:
            pushed.append((session_id, envelope))

        monkeypatch.setattr("app.services.memory_stream_store.push_event", capture)
        return pushed

    @pytest.mark.asyncio
    async def test_layout_accepted(self, monkeypatch: pytest.MonkeyPatch, _capture):
        result = await ui_block(
            blocks=[
                {
                    "type": "layout",
                    "orientation": "columns",
                    "sections": [
                        {
                            "title": "Left",
                            "children": [{"type": "callout", "body": "a"}],
                        },
                        {
                            "children": [
                                {"type": "progress", "label": "x", "value": 1, "max": 2}
                            ]
                        },
                    ],
                }
            ],
            _injected=_injected(),
        )
        assert result["success"] is True
        assert result["types"] == ["layout"]
        assert len(_capture) == 1

    @pytest.mark.asyncio
    async def test_custom_accepted(self, monkeypatch: pytest.MonkeyPatch, _capture):
        result = await ui_block(
            blocks=[{"type": "custom", "html": "<div>widget</div>", "height": 240}],
            _injected=_injected("call-2"),
        )
        assert result["success"] is True
        assert result["types"] == ["custom"]
        assert len(_capture) == 1

    @pytest.mark.asyncio
    async def test_layout_and_custom_mixed(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[
                {
                    "type": "layout",
                    "sections": [{"children": [{"type": "callout", "body": "a"}]}],
                },
                {"type": "custom", "html": "<span>ok</span>"},
            ],
            _injected=_injected("call-3"),
        )
        assert result["success"] is True
        assert result["types"] == ["layout", "custom"]

    @pytest.mark.asyncio
    async def test_invalid_orientation_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[
                {
                    "type": "layout",
                    "orientation": "rows",
                    "sections": [{"children": [{"type": "callout", "body": "a"}]}],
                }
            ],
            _injected=_injected("call-4"),
        )
        assert result["success"] is False
        assert "error" in result
        assert _capture == []

    @pytest.mark.asyncio
    async def test_too_many_sections_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[
                {
                    "type": "layout",
                    "sections": [
                        {"children": [{"type": "callout", "body": "a"}]}
                        for _ in range(5)
                    ],
                }
            ],
            _injected=_injected("call-5"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_too_many_children_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[
                {
                    "type": "layout",
                    "sections": [{"children": [{"type": "callout", "body": "a"}] * 9}],
                }
            ],
            _injected=_injected("call-6"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_over_depth_layout_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        node: dict[str, Any] = {"type": "callout", "body": "leaf"}
        for _ in range(4):
            node = {"type": "layout", "sections": [{"children": [node]}]}
        result = await ui_block(blocks=[node], _injected=_injected("call-7"))
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_empty_html_rejected(self, monkeypatch: pytest.MonkeyPatch, _capture):
        result = await ui_block(
            blocks=[{"type": "custom", "html": ""}],
            _injected=_injected("call-8"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_html_over_length_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[{"type": "custom", "html": "x" * 100_001}],
            _injected=_injected("call-9"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_height_below_min_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[{"type": "custom", "html": "<b>x</b>", "height": 63}],
            _injected=_injected("call-10"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_height_above_max_rejected(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[{"type": "custom", "html": "<b>x</b>", "height": 2001}],
            _injected=_injected("call-11"),
        )
        assert result["success"] is False
        assert _capture == []

    @pytest.mark.asyncio
    async def test_height_bounds_accepted(
        self, monkeypatch: pytest.MonkeyPatch, _capture
    ):
        result = await ui_block(
            blocks=[
                {"type": "custom", "html": "<b>lo</b>", "height": 64},
                {"type": "custom", "html": "<b>hi</b>", "height": 2000},
            ],
            _injected=_injected("call-12"),
        )
        assert result["success"] is True
        assert result["types"] == ["custom", "custom"]
