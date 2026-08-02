"""Focused tests for direct desktop browser routes."""

from __future__ import annotations

import pytest

from app.api.routes.team import browser as browser_route
from app.services.direct_browser_bridge import direct_browser_bridge


@pytest.mark.asyncio
async def test_browser_status_is_inactive_without_desktop(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: False)

    response = await browser_route.get_browser_session("session-1")

    assert response.active is False
    assert response.cdp_url is None
    assert response.tabs == []


@pytest.mark.asyncio
async def test_browser_status_projects_direct_tab_metadata(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, params: dict):
        assert (action, params) == ("status", {})
        return {
            "url": "https://example.com",
            "title": "Example",
            "tabs": [{"index": 0, "url": "https://example.com", "title": "Example"}],
        }

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    response = await browser_route.get_browser_session("session-1")

    assert response.active is True
    assert response.current_url == "https://example.com"
    assert response.current_title == "Example"
    assert response.tabs[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_command_mounts_browser_before_dispatch(monkeypatch) -> None:
    connected = False
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: connected)

    async def request_mount(_sid: str) -> bool:
        return True

    async def wait_connected(_sid: str) -> bool:
        nonlocal connected
        connected = True
        return True

    async def request(_sid: str, action: str, params: dict):
        return {"action": action, "params": params}

    monkeypatch.setattr(direct_browser_bridge, "request_mount", request_mount)
    monkeypatch.setattr(direct_browser_bridge, "wait_connected", wait_connected)
    monkeypatch.setattr(direct_browser_bridge, "request", request)

    response = await browser_route.run_direct_browser_agent_command(
        "session-1",
        browser_route.DirectBrowserCommandRequest(
            action="extract", params={"selector": "main"}
        ),
    )

    assert response.result == {"action": "extract", "params": {"selector": "main"}}
