"""Focused tests for browser viewer WebSocket controls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools.builtin import browser_use_tool as browser_tool
from app.api.routes.team import browser as browser_route


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self._target_id = "target-1"
        self.evaluated: list[str] = []

    async def goto(self, url: str) -> None:
        self.url = url

    async def get_url(self) -> str:
        return self.url

    async def get_title(self) -> str:
        return ""

    async def evaluate(self, script: str) -> None:
        self.evaluated.append(script)


class _FakeCdpSend:
    def __init__(self) -> None:
        self.zoom: list[tuple[dict, str | None]] = []
        self.cache_cleared = False
        self.cookies_cleared = False
        self.inserted_text: list[tuple[dict, str | None]] = []
        self.brought_to_front: list[str | None] = []
        self.storage: list[tuple[dict, str | None]] = []
        self.Emulation = SimpleNamespace(setPageScaleFactor=self.set_page_scale_factor)
        self.Network = SimpleNamespace(clearBrowserCache=self.clear_browser_cache)
        self.Storage = SimpleNamespace(
            clearCookies=self.clear_cookies,
            clearDataForOrigin=self.clear_data_for_origin,
        )
        self.Input = SimpleNamespace(insertText=self.insert_text)
        self.Page = SimpleNamespace(bringToFront=self.bring_to_front)

    async def set_page_scale_factor(
        self, *, params: dict, session_id: str | None = None
    ) -> None:
        self.zoom.append((params, session_id))

    async def clear_browser_cache(self, *, session_id: str | None = None) -> None:
        self.cache_cleared = True

    async def clear_cookies(self, *, session_id: str | None = None) -> None:
        self.cookies_cleared = True

    async def clear_data_for_origin(
        self, *, params: dict, session_id: str | None = None
    ) -> None:
        self.storage.append((params, session_id))

    async def insert_text(self, *, params: dict, session_id: str | None = None) -> None:
        self.inserted_text.append((params, session_id))

    async def bring_to_front(self, *, session_id: str | None = None) -> None:
        self.brought_to_front.append(session_id)


class _FakeSession:
    def __init__(self) -> None:
        self.pages = [_FakePage("https://example.com/start")]
        self.closed: list[_FakePage] = []
        self.send = _FakeCdpSend()

    async def get_pages(self) -> list[_FakePage]:
        return self.pages

    async def get_current_page(self) -> _FakePage | None:
        return self.pages[0] if self.pages else None

    async def new_page(self, url: str) -> _FakePage:
        page = _FakePage(url)
        self.pages.append(page)
        return page

    async def close_page(self, page: _FakePage) -> None:
        self.closed.append(page)
        self.pages.remove(page)

    async def get_or_create_cdp_session(self, **_kwargs):
        return SimpleNamespace(
            cdp_client=SimpleNamespace(send=self.send), session_id="cdp-1"
        )


@pytest.fixture
def browser_session(monkeypatch):
    session = _FakeSession()
    browser_tool._sessions["browser-test"] = session
    browser_tool._pages["browser-test"] = session.pages[0]
    browser_tool._cdp_info["browser-test"] = {
        "cdp_url": "ws://browser",
        "cdp_http": "http://browser",
        "current_url": "about:blank",
        "current_title": "stale",
        "tabs": [],
    }

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(browser_tool, "_attach_observability", noop)
    monkeypatch.setattr(browser_tool, "_refresh_cdp_info", noop)
    yield session
    browser_tool._sessions.pop("browser-test", None)
    browser_tool._pages.pop("browser-test", None)
    browser_tool._cdp_info.pop("browser-test", None)


@pytest.mark.asyncio
async def test_tab_controls_keep_an_active_page(browser_session) -> None:
    new_tab_result = await browser_route._handle_client_message(
        '{"action":"new_tab","url":"https://example.com/next"}', "browser-test"
    )
    assert len(browser_session.pages) == 2
    assert browser_tool._pages["browser-test"].url == "https://example.com/next"
    assert new_tab_result == {
        "type": "action_result",
        "action": "new_tab",
        "ok": True,
        "error": None,
    }

    await browser_route._handle_client_message(
        '{"action":"close_tab","index":1}', "browser-test"
    )
    assert len(browser_session.pages) == 1
    assert browser_tool._pages["browser-test"].url == "https://example.com/start"

    await browser_route._handle_client_message(
        '{"action":"close_tab","index":0}', "browser-test"
    )
    assert len(browser_session.pages) == 1
    assert browser_session.pages[0].url == "about:blank"


@pytest.mark.asyncio
async def test_navigate_recovers_missing_active_page_pointer(browser_session) -> None:
    browser_tool._pages.pop("browser-test")

    result = await browser_route._handle_client_message(
        '{"action":"navigate","url":"https://example.com/recovered"}',
        "browser-test",
    )

    assert browser_tool._pages["browser-test"] is browser_session.pages[0]
    assert browser_session.pages[0].url == "https://example.com/recovered"
    assert result == {
        "type": "action_result",
        "action": "navigate",
        "ok": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_status_recovers_page_and_uses_live_metadata(browser_session) -> None:
    browser_tool._pages.pop("browser-test")

    response = await browser_route.get_browser_session("browser-test")

    assert response.active is True
    assert response.current_url == "https://example.com/start"
    assert response.current_title == ""
    assert [tab.url for tab in response.tabs] == ["https://example.com/start"]


@pytest.mark.asyncio
async def test_page_controls_use_cdp_and_current_origin(browser_session) -> None:
    find_result = await browser_route._handle_client_message(
        '{"action":"find","query":"invoice"}', "browser-test"
    )
    assert "window.find" in browser_session.pages[0].evaluated[0]
    assert find_result == {
        "type": "action_result",
        "action": "find",
        "ok": True,
        "error": None,
    }

    await browser_route._handle_client_message(
        '{"action":"zoom","percent":125}', "browser-test"
    )
    assert browser_session.send.zoom == [({"pageScaleFactor": 1.25}, "cdp-1")]

    result = await browser_route._handle_client_message(
        '{"action":"clear_data"}', "browser-test"
    )
    assert browser_session.send.cookies_cleared is True
    assert browser_session.send.cache_cleared is True
    assert browser_session.send.storage == [
        (
            {"origin": "https://example.com", "storageTypes": "all"},
            "cdp-1",
        )
    ]
    assert result == {
        "type": "action_result",
        "action": "clear_data",
        "ok": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_type_inserts_text_into_focused_page(browser_session) -> None:
    result = await browser_route._handle_client_message(
        '{"action":"type","text":"hello evoflux"}', "browser-test"
    )

    assert browser_session.send.inserted_text == [({"text": "hello evoflux"}, "cdp-1")]
    assert result == {
        "type": "action_result",
        "action": "type",
        "ok": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_start_launches_only_when_session_is_inactive(monkeypatch) -> None:
    launched: list[tuple[str, bool]] = []

    async def fake_launch(session_id: str, *, headless: bool = True) -> None:
        launched.append((session_id, headless))

    monkeypatch.setattr(browser_tool, "_launch_session", fake_launch)
    browser_tool._sessions.pop("browser-new", None)

    result = await browser_route._handle_client_message(
        '{"action":"start"}', "browser-new"
    )

    assert launched == [("browser-new", True)]
    assert result == {
        "type": "action_result",
        "action": "start",
        "ok": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_start_returns_launch_error(monkeypatch) -> None:
    async def fail_launch(_session_id: str, *, headless: bool = True) -> None:
        raise RuntimeError("profile unavailable")

    monkeypatch.setattr(browser_tool, "_launch_session", fail_launch)
    browser_tool._sessions.pop("browser-fail", None)

    result = await browser_route._handle_client_message(
        '{"action":"start"}', "browser-fail"
    )

    assert result == {
        "type": "action_result",
        "action": "start",
        "ok": False,
        "error": "profile unavailable",
    }
