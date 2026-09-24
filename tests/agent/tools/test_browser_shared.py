"""Shared browser result plumbing and provider-schema invariants."""

from __future__ import annotations

import hashlib
import json

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin.browser_shared import (
    DEFAULT_UNTRUSTED_BROWSER_NOTICE,
    combine_browser_results,
    mark_untrusted_browser_result,
)


def test_marks_text_as_untrusted() -> None:
    result = mark_untrusted_browser_result("page text")

    assert result == f"{DEFAULT_UNTRUSTED_BROWSER_NOTICE}\npage text"


def test_marks_first_text_block_and_preserves_mcp_app() -> None:
    result = mark_untrusted_browser_result(
        ToolResult(
            parts=[
                ImageDataBlock(data="aGVsbG8=", media_type="image/png"),
                TextBlock(text="screenshot"),
                TextBlock(text="details"),
            ],
            mcp_app={"name": "browser"},
        )
    )

    assert result.mcp_app == {"name": "browser"}
    assert isinstance(result.parts[0], ImageDataBlock)
    assert isinstance(result.parts[1], TextBlock)
    assert result.parts[1].text == (f"{DEFAULT_UNTRUSTED_BROWSER_NOTICE}\nscreenshot")
    assert isinstance(result.parts[2], TextBlock)
    assert result.parts[2].text == "details"


def test_marks_image_only_result_with_a_text_block() -> None:
    result = mark_untrusted_browser_result(
        ToolResult(parts=[ImageDataBlock(data="aGVsbG8=", media_type="image/png")])
    )

    assert isinstance(result.parts[0], TextBlock)
    assert result.parts[0].text == DEFAULT_UNTRUSTED_BROWSER_NOTICE
    assert isinstance(result.parts[1], ImageDataBlock)


def test_combines_empty_and_text_only_results() -> None:
    assert combine_browser_results([]) == "No actions executed."
    assert combine_browser_results(["first", "second"]) == "first\n---\nsecond"


def test_combines_mixed_results_without_flattening_media() -> None:
    result = combine_browser_results(
        [
            "first",
            "second",
            ToolResult(
                parts=[
                    TextBlock(text="screenshot"),
                    ImageDataBlock(data="aGVsbG8=", media_type="image/png"),
                ]
            ),
            "third",
        ]
    )

    assert isinstance(result, ToolResult)
    assert isinstance(result.parts[0], TextBlock)
    assert result.parts[0].text == "first\n---\nsecond"
    assert isinstance(result.parts[1], TextBlock)
    assert result.parts[1].text == "screenshot"
    assert isinstance(result.parts[2], ImageDataBlock)
    assert isinstance(result.parts[3], TextBlock)
    assert result.parts[3].text == "third"


def _definition_digest(tool) -> str:
    payload = json.dumps(
        tool.definition,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_browser_tool_definitions_are_unchanged() -> None:
    from app.agent.tools.builtin.browser_use_tool import browser_use
    from app.agent.tools.builtin.webbridge_tool import webbridge

    # Changed deliberately: `resize.orientation` no longer defaults to
    # "portrait", which was rotating every landscape viewport request.
    assert _definition_digest(browser_use) == (
        "a25995c3f20d22e35a1d24f9cc41f3763eb27dcf24fb1d0957dfb71b910fab1f"
    )
    # Changed deliberately: the tool guide (`_DESCRIPTION`) was defined but
    # never passed to `@tool`, so the model saw only the one-line docstring;
    # then console/network/network_body/debug_summary were added.
    assert _definition_digest(webbridge) == (
        "5e043485ed0c325f4b1ea25d429e727589846688727804a6d1bb904074cf4104"
    )
