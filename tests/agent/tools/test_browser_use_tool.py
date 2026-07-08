"""Tests for browser_use observability actions (no real Chromium).

Fakes stand in for the browser-use session/page objects; the real browser
paths (launch, CDP wiring) are exercised manually — these tests pin the
handler logic: snapshot formatting, console/network filtering, extract
truncation, index-based element resolution, and multimodal screenshot
assembly.
"""

from __future__ import annotations

import base64
from collections import deque
from types import SimpleNamespace

import pytest

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin import browser_use_tool as bt


class _FakeState:
    def __init__(self, sid: str = "test-sid") -> None:
        self.metadata = {"session_id": sid}


class _FakeElement:
    def __init__(self) -> None:
        self.clicked = False
        self.filled: str | None = None

    async def click(self) -> None:
        self.clicked = True

    async def fill(self, text: str, clear: bool = True) -> None:
        self.filled = text

    async def screenshot(self, format: str = "png", quality: int | None = None) -> str:
        return base64.b64encode(b"elem-bytes").decode()


class _FakePage:
    def __init__(self, *, elements: dict[str, list] | None = None) -> None:
        self._elements = elements or {}
        self.url = "http://localhost:5180/"

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return self._elements.get(selector, [])

    async def get_element(self, backend_node_id: int) -> _FakeElement:
        el = _FakeElement()
        el.backend_node_id = backend_node_id
        return el

    async def evaluate(self, script: str) -> str:
        return "x" * 50_000  # long page text for truncation tests

    async def get_url(self) -> str:
        return self.url

    async def screenshot(self, format: str = "png", quality: int | None = None) -> str:
        return base64.b64encode(b"page-bytes").decode()


class _FakeCdpClient:
    def __init__(self) -> None:
        self.emulated: list[dict] = []
        outer = self

        class _Emulation:
            async def setEmulatedMedia(self, params, session_id=None):
                outer.emulated.append(params)

        self.send = SimpleNamespace(Emulation=_Emulation())


class _FakeSession:
    def __init__(self, *, node: object | None = None) -> None:
        self._node = node
        self.stopped = False
        self.cdp_client_fake = _FakeCdpClient()

    async def get_dom_element_by_index(self, index: int):
        return self._node

    async def get_browser_state_summary(self, include_screenshot: bool = True):
        dom_state = SimpleNamespace(
            llm_representation=lambda: "[1]<button>Save</button>\n[2]<input placeholder=Name />"
        )
        return SimpleNamespace(
            dom_state=dom_state, url="http://localhost:5180/", title="Demo"
        )

    async def get_or_create_cdp_session(self):
        return SimpleNamespace(cdp_client=self.cdp_client_fake, session_id="cdp-1")

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
def _clean_buffers():
    yield
    bt._console_logs.clear()
    bt._network_events.clear()
    bt._sessions.pop("test-sid", None)


# ── console / network ────────────────────────────────────────────────────────


def test_console_filters_levels():
    state = _FakeState()
    bt._console_logs["test-sid"] = deque(
        [
            {"ts": 1, "level": "log", "text": "hello"},
            {"ts": 2, "level": "warning", "text": "deprecated"},
            {"ts": 3, "level": "error", "text": "boom"},
        ]
    )
    all_out = bt._handle_console(bt.ConsoleAction(action="console"), state)
    assert "hello" in all_out and "boom" in all_out

    err_out = bt._handle_console(
        bt.ConsoleAction(action="console", level="error"), state
    )
    assert "boom" in err_out and "hello" not in err_out and "deprecated" not in err_out

    warn_out = bt._handle_console(
        bt.ConsoleAction(action="console", level="warn"), state
    )
    assert "deprecated" in warn_out and "boom" in warn_out and "hello" not in warn_out


def test_console_empty_buffer():
    assert "no console messages" in bt._handle_console(
        bt.ConsoleAction(action="console"), _FakeState()
    )


def test_network_failed_filter():
    state = _FakeState()
    bt._network_events["test-sid"] = deque(
        [
            {"ts": 1, "method": "GET", "url": "http://x/ok", "status": 200},
            {"ts": 2, "method": "POST", "url": "http://x/api", "status": 500},
            {
                "ts": 3,
                "method": "GET",
                "url": "http://x/dead",
                "status": 0,
                "error": "net::ERR_CONNECTION_REFUSED",
            },
        ]
    )
    failed = bt._handle_network(
        bt.NetworkAction(action="network", filter="failed"), state
    )
    assert "http://x/api → 500" in failed
    assert "net::ERR_CONNECTION_REFUSED" in failed
    assert "http://x/ok" not in failed

    everything = bt._handle_network(bt.NetworkAction(action="network"), state)
    assert "http://x/ok → 200" in everything


# ── snapshot ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_renders_indexed_elements():
    out = await bt._handle_snapshot(
        bt.SnapshotAction(action="snapshot"), _FakeSession(), _FakePage()
    )
    assert "URL: http://localhost:5180/" in out
    assert "Title: Demo" in out
    assert "[1]<button>Save</button>" in out
    assert "click/fill" in out


# ── extract truncation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_truncates_long_page():
    out = await bt._handle_extract(
        bt.ExtractAction(action="extract", max_chars=1000), _FakePage()
    )
    assert len(out) < 1300
    assert "truncated" in out


# ── click / fill by index ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_click_by_index_resolves_via_selector_map():
    state = _FakeState()
    node = SimpleNamespace(backend_node_id=42)
    bt._sessions["test-sid"] = _FakeSession(node=node)
    out = await bt._handle_click(
        bt.ClickAction(action="click", index=7), _FakePage(), state
    )
    assert "Clicked: [7]" in out


@pytest.mark.asyncio
async def test_click_by_stale_index_asks_for_snapshot():
    state = _FakeState()
    bt._sessions["test-sid"] = _FakeSession(node=None)
    out = await bt._handle_click(
        bt.ClickAction(action="click", index=99), _FakePage(), state
    )
    assert "snapshot" in out


@pytest.mark.asyncio
async def test_click_requires_index_or_selector():
    out = await bt._handle_click(bt.ClickAction(action="click"), _FakePage(), _FakeState())
    assert "Provide either" in out


# ── screenshot → multimodal ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_returns_image_part():
    result = await bt._handle_screenshot(
        bt.ScreenshotAction(action="screenshot"), _FakePage()
    )
    assert isinstance(result, ToolResult)
    kinds = [type(p) for p in result.parts]
    assert TextBlock in kinds and ImageDataBlock in kinds
    img = next(p for p in result.parts if isinstance(p, ImageDataBlock))
    assert img.media_type == "image/jpeg"
    assert base64.b64decode(img.data) == b"page-bytes"


@pytest.mark.asyncio
async def test_batch_mixing_text_and_screenshot_folds_into_tool_result(monkeypatch):
    state = _FakeState()
    page = _FakePage()
    session = _FakeSession()

    async def fake_get_session(_state):
        return session, page

    monkeypatch.setattr(bt, "_get_session", fake_get_session)

    result = await bt.browser_use.arun(
        _injected={"_state": state},
        actions=[
            {"action": "extract", "max_chars": 200},
            {"action": "screenshot"},
        ],
    )
    assert isinstance(result, ToolResult)
    assert isinstance(result.parts[0], TextBlock)
    assert any(isinstance(p, ImageDataBlock) for p in result.parts)


@pytest.mark.asyncio
async def test_batch_text_only_returns_string(monkeypatch):
    state = _FakeState()

    async def fake_get_session(_state):
        return _FakeSession(), _FakePage()

    monkeypatch.setattr(bt, "_get_session", fake_get_session)

    result = await bt.browser_use.arun(
        _injected={"_state": state},
        actions=[{"action": "extract", "max_chars": 200}, {"action": "console"}],
    )
    assert isinstance(result, str)
    assert "no console messages" in result


# ── resize ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resize_preset_and_dark_mode():
    session = _FakeSession()
    page = _FakePage()
    sized: list[tuple[int, int]] = []

    async def set_viewport_size(w: int, h: int) -> None:
        sized.append((w, h))

    page.set_viewport_size = set_viewport_size

    out = await bt._handle_resize(
        bt.ResizeAction(action="resize", preset="mobile", color_scheme="dark"),
        session,
        page,
    )
    assert sized == [(375, 812)]
    assert session.cdp_client_fake.emulated == [
        {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}
    ]
    assert "viewport 375x812" in out and "dark" in out


@pytest.mark.asyncio
async def test_resize_without_params_hints():
    out = await bt._handle_resize(
        bt.ResizeAction(action="resize"), _FakeSession(), _FakePage()
    )
    assert "Nothing to change" in out


# ── cleanup ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idle_sessions_are_swept():
    stale = _FakeSession()
    bt._sessions["stale-sid"] = stale
    bt._last_used["stale-sid"] = -10_000.0  # long past the TTL

    await bt._sweep_idle_sessions(active_sid="other-sid")

    assert stale.stopped is True
    assert "stale-sid" not in bt._sessions
    assert "stale-sid" not in bt._last_used


@pytest.mark.asyncio
async def test_close_all_sessions_stops_everything():
    a, b = _FakeSession(), _FakeSession()
    bt._sessions.update({"sid-a": a, "sid-b": b})
    bt._console_logs["sid-a"] = deque([{"ts": 1, "level": "log", "text": "x"}])

    await bt.close_all_sessions()

    assert a.stopped and b.stopped
    assert not bt._sessions
    assert "sid-a" not in bt._console_logs
