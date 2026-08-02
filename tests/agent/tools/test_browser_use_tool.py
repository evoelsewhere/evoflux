"""Tests for EvoFlux's direct in-app browser tool."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin import browser_use_tool as browser_tool
from app.services.direct_browser_bridge import direct_browser_bridge


def _state(session_id: str = "desktop-session") -> SimpleNamespace:
    return SimpleNamespace(metadata={"session_id": session_id})


@pytest.mark.asyncio
async def test_browser_use_requires_evoflux_desktop(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: False)
    monkeypatch.setattr(direct_browser_bridge, "is_available", lambda _sid: False)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()}, actions=[{"action": "snapshot"}]
    )

    assert isinstance(result, str)
    assert "EvoFlux Desktop" in result


@pytest.mark.asyncio
async def test_browser_use_mounts_panel_and_runs_actions(monkeypatch) -> None:
    connected = False
    requests: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(direct_browser_bridge, "is_available", lambda _sid: True)
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: connected)

    async def request_mount(_sid: str) -> bool:
        return True

    async def wait_connected(_sid: str) -> bool:
        nonlocal connected
        connected = True
        return True

    async def request(sid: str, action: str, params: dict):
        requests.append((sid, action, params))
        return f"direct:{action}"

    monkeypatch.setattr(direct_browser_bridge, "request_mount", request_mount)
    monkeypatch.setattr(direct_browser_bridge, "wait_connected", wait_connected)
    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "snapshot"},
            {"action": "press", "index": 2, "key": "Enter"},
        ],
    )

    assert isinstance(result, str)
    assert "direct:navigate" in result
    assert "Untrusted browser content" in result
    assert requests == [
        ("desktop-session", "navigate", {"url": "https://example.com"}),
        ("desktop-session", "snapshot", {"max_chars": 15_000}),
        ("desktop-session", "press", {"index": 2, "key": "Enter"}),
    ]


@pytest.mark.asyncio
async def test_screenshot_becomes_multimodal_tool_result(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, params: dict):
        assert action == "screenshot"
        assert params == {"index": 4}
        return {
            "kind": "image",
            "media_type": "image/png",
            "data": "aGVsbG8=",
            "text": "[In-app browser screenshot]",
        }

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[{"action": "screenshot", "index": 4}],
    )

    assert isinstance(result, ToolResult)
    assert any(isinstance(part, TextBlock) for part in result.parts)
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)


@pytest.mark.asyncio
async def test_direct_errors_are_action_scoped(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, _params: dict):
        raise RuntimeError(f"failed {action}")

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()}, actions=[{"action": "console"}]
    )

    assert result == "Error (console): failed console"


@pytest.mark.asyncio
async def test_expanded_control_and_debug_actions_are_forwarded(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    requests: list[tuple[str, dict]] = []

    async def request(_sid: str, action: str, params: dict):
        requests.append((action, params))
        return {"action": action, "ok": True}

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "query", "selector": "[data-testid]"},
            {"action": "inspect", "index": 3, "styles": ["display", "opacity"]},
            {"action": "type", "index": 4, "text": "hello"},
            {"action": "dispatch_event", "index": 4, "event": "blur"},
            {
                "action": "wait",
                "selector": "#result",
                "state": "visible",
                "text": "Saved",
            },
            {"action": "performance", "include_resources": False},
            {
                "action": "http",
                "method": "POST",
                "url": "/api/debug",
                "body": "{}",
            },
            {
                "action": "evaluate",
                "script": "Promise.resolve(42)",
                "await_promise": True,
            },
        ],
    )

    assert isinstance(result, str)
    assert [action for action, _params in requests] == [
        "query",
        "inspect",
        "type",
        "dispatch_event",
        "wait",
        "performance",
        "http",
        "evaluate",
    ]
    assert requests[0][1] == {
        "selector": "[data-testid]",
        "limit": 50,
        "include_hidden": False,
    }
    assert requests[4][1] == {
        "selector": "#result",
        "state": "visible",
        "text": "Saved",
        "seconds": 2.0,
    }
    assert requests[6][1]["timeout_ms"] == 15_000
    assert requests[7][1] == {
        "script": "Promise.resolve(42)",
        "await_promise": True,
        "timeout_ms": 15_000,
    }
