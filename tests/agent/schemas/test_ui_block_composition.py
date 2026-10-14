"""UiBlockEvent layout/custom composition limits (spec §2.1/§3.1, Stream 2).

Server-side caps: layout nesting depth <= 3 (root layout = 1), total nodes
per event <= 50, section title <= 80 chars, 1..8 children per section,
1..4 sections per layout. `custom` bounds html 1..100000 chars and height
64..2000. Both types must live inside the same discriminated ``UiBlockNode``
union as the original block types.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.schemas.events import (
    MAX_UI_BLOCK_DEPTH,
    MAX_UI_BLOCK_NODES,
    UiBlockEvent,
    UiCustomBlock,
    UiLayoutBlock,
)


def _as_layout(block: Any) -> UiLayoutBlock:
    assert isinstance(block, UiLayoutBlock)
    return block


def _as_custom(block: Any) -> UiCustomBlock:
    assert isinstance(block, UiCustomBlock)
    return block


def _payload(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"agent": "lead", "tool_call_id": "call-1", "blocks": blocks}


def _callout(body: str = "hello") -> dict[str, Any]:
    return {"type": "callout", "body": body}


def _nested_layout(depth: int) -> dict[str, Any]:
    """A layout chain ``depth`` levels deep with a callout leaf."""
    node: dict[str, Any] = _callout()
    for _ in range(depth):
        node = {
            "type": "layout",
            "orientation": "columns",
            "sections": [{"title": "group", "children": [node]}],
        }
    return node


class TestDepthCap:
    def test_depth_three_passes(self):
        event = UiBlockEvent.model_validate(_payload([_nested_layout(3)]))
        assert event.blocks[0].type == "layout"

    def test_depth_four_rejected(self):
        with pytest.raises(ValidationError, match="layout nesting deeper than 3"):
            UiBlockEvent.model_validate(_payload([_nested_layout(4)]))

    def test_non_layout_blocks_do_not_consume_depth(self):
        # A callout inside a layout is depth 2 but adds no layout nesting.
        payload = _payload(
            [
                {
                    "type": "layout",
                    "sections": [{"children": [_callout()]}],
                }
            ]
        )
        event = UiBlockEvent.model_validate(payload)
        assert event.blocks[0].type == "layout"

    def test_mixed_depth_boundary(self):
        # Two level-1 layouts each holding a level-2 layout: legal.
        inner = {"type": "layout", "sections": [{"children": [_callout()]}]}
        outer = {
            "type": "layout",
            "sections": [{"children": [inner]}],
        }
        event = UiBlockEvent.model_validate(_payload([outer, outer]))
        assert len(event.blocks) == 2


class TestNodeCap:
    def test_fifty_nodes_pass(self):
        # 2 root layouts x (1 root + 4 sections x 6 callouts) = 50 nodes.
        layout = {
            "type": "layout",
            "sections": [{"children": [_callout()] * 6} for _ in range(4)],
        }
        event = UiBlockEvent.model_validate(_payload([layout, layout]))
        assert len(event.blocks) == 2

    def test_fifty_one_nodes_rejected(self):
        layout = {
            "type": "layout",
            "sections": [{"children": [_callout()] * 6} for _ in range(4)],
        }
        # 25 + 25 + 1 = 51 nodes.
        with pytest.raises(ValidationError, match="total UI nodes"):
            UiBlockEvent.model_validate(_payload([layout, layout, _callout()]))

    def test_cap_constant(self):
        assert MAX_UI_BLOCK_NODES == 50
        assert MAX_UI_BLOCK_DEPTH == 3


class TestSectionCaps:
    def _layout(self, **section_overrides: Any) -> dict[str, Any]:
        section: dict[str, Any] = {"children": [_callout()]}
        section.update(section_overrides)
        return {"type": "layout", "sections": [section]}

    def test_title_eighty_chars_passes(self):
        event = UiBlockEvent.model_validate(_payload([self._layout(title="t" * 80)]))
        assert _as_layout(event.blocks[0]).sections[0].title == "t" * 80

    def test_title_eighty_one_chars_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(_payload([self._layout(title="t" * 81)]))

    def test_eight_children_pass(self):
        event = UiBlockEvent.model_validate(
            _payload([self._layout(children=[_callout()] * 8)])
        )
        assert len(_as_layout(event.blocks[0]).sections[0].children) == 8

    def test_nine_children_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload([self._layout(children=[_callout()] * 9)])
            )

    def test_zero_children_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(_payload([self._layout(children=[])]))

    def test_four_sections_pass(self):
        event = UiBlockEvent.model_validate(
            _payload(
                [
                    {
                        "type": "layout",
                        "sections": [{"children": [_callout()]} for _ in range(4)],
                    }
                ]
            )
        )
        assert len(_as_layout(event.blocks[0]).sections) == 4

    def test_five_sections_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload(
                    [
                        {
                            "type": "layout",
                            "sections": [{"children": [_callout()]} for _ in range(5)],
                        }
                    ]
                )
            )

    def test_zero_sections_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(_payload([{"type": "layout", "sections": []}]))

    def test_orientation_rows_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload(
                    [
                        {
                            "type": "layout",
                            "orientation": "rows",
                            "sections": [{"children": [_callout()]}],
                        }
                    ]
                )
            )


class TestUnionMembership:
    def test_layout_and_custom_inside_union(self):
        event = UiBlockEvent.model_validate(
            _payload(
                [
                    _nested_layout(1),
                    {"type": "custom", "html": "<div>hi</div>"},
                ]
            )
        )
        assert [block.type for block in event.blocks] == ["layout", "custom"]

    def test_custom_html_and_height_bounds(self):
        event = UiBlockEvent.model_validate(
            _payload([{"type": "custom", "html": "<p>x</p>", "height": 64}])
        )
        assert _as_custom(event.blocks[0]).height == 64

        event = UiBlockEvent.model_validate(
            _payload([{"type": "custom", "html": "<p>x</p>", "height": 2000}])
        )
        assert _as_custom(event.blocks[0]).height == 2000

    def test_custom_height_bounds_rejected(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload([{"type": "custom", "html": "<p>x</p>", "height": 63}])
            )
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload([{"type": "custom", "html": "<p>x</p>", "height": 2001}])
            )

    def test_custom_html_length_bounds(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(_payload([{"type": "custom", "html": ""}]))
        event = UiBlockEvent.model_validate(
            _payload([{"type": "custom", "html": "x" * 100_000}])
        )
        assert len(_as_custom(event.blocks[0]).html) == 100_000
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(
                _payload([{"type": "custom", "html": "x" * 100_001}])
            )

    def test_existing_blocks_cap_unchanged(self):
        with pytest.raises(ValidationError):
            UiBlockEvent.model_validate(_payload([_callout()] * 7))
