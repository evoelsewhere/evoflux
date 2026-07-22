"""WebBridge — manager, relay WS endpoints, auth, and tool-level tests.

The relay endpoints run in a real (in-process) app via ``TestClient``; the
manager is exercised directly with a fake ``send`` callable for the
correlation/timeout paths that are awkward to drive over the wire.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from starlette.websockets import WebSocketDisconnect

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin.webbridge_tool import AnyAction, webbridge
from app.api.routes.team.webbridge import router
from app.services.webbridge_service import WebBridgeManager

_PREFIX = "/api/team/webbridge"

_ACTION = TypeAdapter(AnyAction)


def _action(payload: dict):
    """Build an action model the way the LLM-facing schema would."""
    return _ACTION.validate_python(payload)


def test_tool_and_extension_action_contracts_match():
    background = (
        Path(__file__).resolve().parents[2]
        / "extensions"
        / "webbridge"
        / "background.js"
    ).read_text(encoding="utf-8")
    command_switch = background[
        background.index("async function handleCommand") : background.index(
            "function sendResponse"
        )
    ]
    extension_actions = set(re.findall(r'case "([a-z_]+)":', command_switch))
    tool_actions = set(_ACTION.json_schema()["discriminator"]["mapping"])

    # crawl is a backend orchestration action composed from extension commands.
    assert tool_actions - {"crawl"} == extension_actions


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> WebBridgeManager:
    """Fresh manager per test, swapped into every module that holds a reference."""
    mgr = WebBridgeManager()
    monkeypatch.setattr("app.services.webbridge_service.webbridge_manager", mgr)
    monkeypatch.setattr("app.api.routes.team.webbridge.webbridge_manager", mgr)
    monkeypatch.setattr("app.agent.tools.builtin.webbridge_tool.webbridge_manager", mgr)
    return mgr


@pytest.fixture
def client(manager: WebBridgeManager) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=_PREFIX)
    return TestClient(app)


def _register(ws, extension_id: str = "ext-1") -> dict:
    ws.send_text(
        json.dumps(
            {
                "type": "register",
                "extension_id": extension_id,
                "browser": "chrome",
                "version": "120.0",
            }
        )
    )
    return json.loads(ws.receive_text())


# ── REST status + registration ────────────────────────────────────────────────


def test_register_then_status_shows_connected(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        ack = _register(ws)
        assert ack == {"type": "registered", "extension_id": "ext-1"}

        status = client.get(f"{_PREFIX}/status").json()
        assert status["connected"] is True
        [ext] = status["extensions"]
        assert ext["extension_id"] == "ext-1"
        assert ext["browser"] == "chrome"
        assert ext["version"] == "120.0"

    # After disconnect the status flips back.
    assert client.get(f"{_PREFIX}/status").json()["connected"] is False


def test_event_updates_extension_state(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        _register(ws)
        ws.send_text(
            json.dumps(
                {
                    "type": "event",
                    "event": "tab_updated",
                    "data": {
                        "url": "https://example.com",
                        "title": "Example",
                        "tabs": [{"index": 0, "title": "Example", "active": True}],
                    },
                }
            )
        )
        # Give the relay a beat to process the frame, then read status.
        for _ in range(50):
            ext = client.get(f"{_PREFIX}/status").json()["extensions"][0]
            if ext["current_url"]:
                break
            time.sleep(0.01)
        assert ext["current_url"] == "https://example.com"
        assert ext["current_title"] == "Example"
        assert ext["tabs"] == [{"index": 0, "title": "Example", "active": True}]


# ── Command roundtrip over the wire ───────────────────────────────────────────


def test_command_roundtrip_agent_ws(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)

            agent_ws.send_text(
                json.dumps({"action": "navigate", "url": "https://x.dev"})
            )
            command = json.loads(ext_ws.receive_text())
            assert command["type"] == "command"
            assert command["action"] == "navigate"
            assert command["params"] == {"url": "https://x.dev"}
            assert command["request_id"]

            ext_ws.send_text(
                json.dumps(
                    {
                        "type": "response",
                        "request_id": command["request_id"],
                        "success": True,
                        "data": {"url": "https://x.dev"},
                        "error": None,
                    }
                )
            )
            response = json.loads(agent_ws.receive_text())
            assert response["type"] == "response"
            assert response["request_id"] == command["request_id"]
            assert response["success"] is True
            assert response["data"] == {"url": "https://x.dev"}


def test_sequential_commands_correlate_by_request_id(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)
            seen_ids: list[str] = []

            for action in ("back", "forward"):
                agent_ws.send_text(json.dumps({"action": action}))
                command = json.loads(ext_ws.receive_text())
                assert command["action"] == action
                seen_ids.append(command["request_id"])
                ext_ws.send_text(
                    json.dumps(
                        {
                            "type": "response",
                            "request_id": command["request_id"],
                            "success": True,
                            "data": {"did": action},
                            "error": None,
                        }
                    )
                )
                response = json.loads(agent_ws.receive_text())
                assert response["request_id"] == command["request_id"]
                assert response["data"] == {"did": action}

            assert len(set(seen_ids)) == 2


def test_agent_ws_no_extension(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        agent_ws.send_text(json.dumps({"action": "navigate", "url": "https://x.dev"}))
        msg = json.loads(agent_ws.receive_text())
        assert msg["type"] == "no_extension"
        assert "no browser extension" in msg["error"].lower()


def test_extension_disconnect_fails_pending_command(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)
            agent_ws.send_text(
                json.dumps({"action": "navigate", "url": "https://x.dev"})
            )
            assert json.loads(ext_ws.receive_text())["type"] == "command"
        # Extension socket closed while the command is still pending.
        response = json.loads(agent_ws.receive_text())
        assert response["type"] == "response"
        assert response["success"] is False
        assert "disconnected" in response["error"]


# ── Heartbeat ─────────────────────────────────────────────────────────────────


def test_ping_refreshes_last_seen(client: TestClient, manager: WebBridgeManager):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        _register(ws)

        # Simulate an idle extension: status must report it as gone.
        conn = manager.get_extension("ext-1")
        assert conn is not None
        conn.last_seen = time.time() - 1000
        assert client.get(f"{_PREFIX}/status").json()["connected"] is False

        # A heartbeat brings it back and is answered with a pong.
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text()) == {"type": "pong"}
        assert client.get(f"{_PREFIX}/status").json()["connected"] is True


# ── Manager unit-level paths ──────────────────────────────────────────────────


async def test_manager_send_command_roundtrip(manager: WebBridgeManager):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )

    task = asyncio.create_task(
        manager.send_command("sess", "navigate", {"url": "https://x"})
    )
    await asyncio.sleep(0)

    command = json.loads(sent[0])
    assert command["type"] == "command"
    assert command["action"] == "navigate"
    assert command["params"] == {"url": "https://x"}
    assert command["request_id"]

    assert manager.handle_response(
        command["request_id"], success=True, data={"ok": 1}, error=None
    )
    result = await task
    assert result["request_id"] == command["request_id"]
    assert result["success"] is True
    assert result["data"] == {"ok": 1}


async def test_manager_commands_correlate_by_request_id(manager: WebBridgeManager):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )

    t1 = asyncio.create_task(manager.send_command("sess", "click", {"x": 1, "y": 2}))
    t2 = asyncio.create_task(manager.send_command("sess", "type", {"text": "hi"}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    id1 = json.loads(sent[0])["request_id"]
    id2 = json.loads(sent[1])["request_id"]
    assert id1 != id2

    # Answer out of order — each future must still get its own response.
    manager.handle_response(id2, success=True, data={"for": "type"}, error=None)
    manager.handle_response(id1, success=True, data={"for": "click"}, error=None)

    assert (await t1)["data"] == {"for": "click"}
    assert (await t2)["data"] == {"for": "type"}


async def test_manager_no_extension(manager: WebBridgeManager):
    result = await manager.send_command("sess", "navigate", {"url": "https://x"})
    assert result["success"] is False
    assert "no browser extension" in result["error"].lower()


async def test_manager_disconnect_fails_pending(manager: WebBridgeManager):
    async def fake_send(text: str) -> None:
        pass

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    task = asyncio.create_task(manager.send_command("sess", "click", {"x": 1, "y": 2}))
    await asyncio.sleep(0)

    manager.unregister_extension("e1")
    result = await asyncio.wait_for(task, timeout=1)
    assert result["success"] is False
    assert result["error"] == "extension disconnected"


async def test_manager_status_action_is_local(manager: WebBridgeManager):
    result = await manager.send_command("sess", "status")
    assert result["success"] is True
    assert result["data"] == {"connected": False, "extensions": []}


async def test_manager_cleanup_stale(manager: WebBridgeManager):
    async def fake_send(text: str) -> None:
        pass

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.last_seen = time.time() - 1000

    assert manager.cleanup_stale() == ["e1"]
    assert manager.get_extension("e1") is None


# ── WS token auth ─────────────────────────────────────────────────────────────


def test_ws_rejected_without_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    for path in (f"{_PREFIX}/relay", f"{_PREFIX}/agent/s1"):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(path):
                pass
        assert exc_info.value.code == 4401


def test_ws_rejected_with_wrong_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"{_PREFIX}/relay?_token=nope"):
            pass
    assert exc_info.value.code == 4401


def test_ws_accepted_with_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with client.websocket_connect(f"{_PREFIX}/relay?_token=secret-token") as ws:
        assert _register(ws)["type"] == "registered"
    with client.websocket_connect(
        f"{_PREFIX}/agent/s1?_token=secret-token"
    ) as agent_ws:
        agent_ws.send_text(json.dumps({"action": "status"}))
        msg = json.loads(agent_ws.receive_text())
        assert msg["type"] == "response"
        assert msg["success"] is True


def test_ws_open_when_no_token_configured(client: TestClient):
    # conftest deletes EVOFLUX_DESKTOP_TOKEN for the whole session.
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        assert _register(ws)["type"] == "registered"


# ── Tool-level (manager's send_command stubbed) ───────────────────────────────


def _stub_send(monkeypatch: pytest.MonkeyPatch, manager: WebBridgeManager, handler):
    async def fake_send_command(
        session_id: str, action: str, params: dict | None = None
    ):
        return handler(action, params or {})

    monkeypatch.setattr(manager, "send_command", fake_send_command)


async def test_tool_status_when_disconnected(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {"connected": False, "extensions": []},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "status"})])
    assert isinstance(result, str)
    assert "No browser extension connected" in result


async def test_tool_navigate_success_text(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "navigate", "url": "https://example.com"})]
    )
    assert result == "Navigated to https://example.com"
    assert seen == [("navigate", {"url": "https://example.com"})]


async def test_tool_screenshot_returns_image_block(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    raw = b"fake-png-bytes"
    b64 = base64.b64encode(raw).decode()
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {"data": b64, "format": "png"},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "screenshot"})])
    assert isinstance(result, ToolResult)
    image = next(p for p in result.parts if isinstance(p, ImageDataBlock))
    assert image.data == b64
    assert image.media_type == "image/png"
    text = next(p for p in result.parts if isinstance(p, TextBlock))
    assert "Screenshot captured" in text.text
    assert f"{len(raw)} bytes" in text.text
    assert "CSS pixels" in text.text


async def test_tool_aggregates_action_errors(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "click":
            return {"success": False, "data": None, "error": "boom"}
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "click", "x": 10, "y": 20}),
            _action({"action": "type", "text": "abc"}),
        ]
    )
    assert isinstance(result, str)
    assert "Click failed: boom" in result
    assert "Typed 3 characters" in result
    assert "\n---\n" in result


# ── Session routing ───────────────────────────────────────────────────────────


def _recorder_ext(manager: WebBridgeManager, ext_id: str) -> list[str]:
    """Register *ext_id* with a send() that records the wire commands it gets."""
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id=ext_id, browser="chrome", version="1", send=fake_send
    )
    return sent


async def _run(manager: WebBridgeManager, coro_factory, sent: list[str]):
    """Drive a send_command task: start it, answer the pending request, await."""
    task = asyncio.create_task(coro_factory())
    for _ in range(4):
        await asyncio.sleep(0)
        if sent:
            break
    request_id = json.loads(sent[-1])["request_id"]
    manager.handle_response(request_id, success=True, data={"ok": 1}, error=None)
    return await task


async def test_session_sticks_to_first_extension(manager: WebBridgeManager):
    s1 = _recorder_ext(manager, "e1")
    s2 = _recorder_ext(manager, "e2")  # e2 registered last → currently "active"

    # First command binds session "sess" to the active extension (e2).
    await _run(
        manager, lambda: manager.send_command("sess", "click", {"x": 1, "y": 2}), s2
    )
    assert len(s2) == 1 and len(s1) == 0

    # Make e1 look most-recently-seen; the session must still target e2.
    manager.get_extension("e1").last_seen = time.time() + 100
    await _run(
        manager, lambda: manager.send_command("sess", "click", {"x": 3, "y": 4}), s2
    )
    assert len(s2) == 2 and len(s1) == 0


async def test_explicit_extension_id_overrides_binding(manager: WebBridgeManager):
    s1 = _recorder_ext(manager, "e1")
    s2 = _recorder_ext(manager, "e2")

    await _run(
        manager,
        lambda: manager.send_command(
            "sess", "click", {"x": 1, "y": 2}, extension_id="e1"
        ),
        s1,
    )
    assert len(s1) == 1 and len(s2) == 0


async def test_explicit_unknown_extension_errors(manager: WebBridgeManager):
    _recorder_ext(manager, "e1")
    result = await manager.send_command("sess", "click", {"x": 1}, extension_id="ghost")
    assert result["success"] is False
    assert "no browser extension" in result["error"].lower()


def test_events_only_reach_bound_session(manager: WebBridgeManager):
    _recorder_ext(manager, "e1")
    _recorder_ext(manager, "e2")
    manager.resolve_target("s1", "e1")  # bind s1 → e1
    manager.resolve_target("s2", "e2")  # bind s2 → e2
    q1 = manager.subscribe_agent("s1")
    q2 = manager.subscribe_agent("s2")

    manager.handle_event("e1", "tab_updated", {"url": "https://a", "title": "A"})

    assert q1.qsize() == 1
    assert q2.qsize() == 0  # s2 is pinned to e2 — must not see e1's event


# ── Per-action timeouts ─────────────────────────────────────────────────────


def test_timeout_navigate_exceeds_extension_internal_wait(manager: WebBridgeManager):
    # Manager must wait longer than the extension's own 25s navigation wait.
    assert manager._timeout_for("navigate", {}) > 30.0
    assert manager._timeout_for("click", {}) == 30.0


def test_timeout_derives_from_caller_timeout_ms(manager: WebBridgeManager):
    assert manager._timeout_for("wait_for_selector", {"timeout_ms": 5000}) == 15.0


# ── Domain policy + evaluate gate ─────────────────────────────────────────────


def _set_policy(manager: WebBridgeManager, **kwargs) -> None:
    """Inject a WebBridge policy straight into the manager's in-memory cache.

    Mirrors what ``reload_policy()`` does at runtime, without the disk read —
    the command path only ever consults the cache.
    """
    from app.core.runtime_settings import WebBridgeSettings

    manager._policy_cache = WebBridgeSettings(**kwargs)


async def test_policy_blocks_navigate_to_blocked_domain(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    result = await manager.send_command(
        "sess", "navigate", {"url": "https://sub.evil.com/x"}
    )
    assert result["success"] is False
    assert "blocked" in result["error"].lower()


async def test_policy_allowlist_refuses_other_domains(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, allowed_domains=["example.com"])
    sent = _recorder_ext(manager, "e1")
    refused = await manager.send_command(
        "sess", "navigate", {"url": "https://other.com"}
    )
    assert refused["success"] is False and "allowlist" in refused["error"].lower()
    assert sent == []  # never reached the extension

    ok = await _run(
        manager,
        lambda: manager.send_command(
            "sess", "navigate", {"url": "https://example.com/p"}
        ),
        sent,
    )
    assert ok["success"] is True


async def test_policy_gates_page_action_by_current_url(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    manager.get_extension("e1").current_url = "https://evil.com/dashboard"
    result = await manager.send_command("sess", "click", {"x": 1, "y": 2})
    assert result["success"] is False and "blocked" in result["error"].lower()


async def test_policy_gates_page_action_by_target_tab_url(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    sent = _recorder_ext(manager, "e1")
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.current_url = "https://example.com/allowed-active-tab"
    conn.tabs = [
        {"id": 7, "url": "https://evil.com/private"},
        {"id": 8, "url": "https://example.com/other"},
    ]

    result = await manager.send_command(
        "sess", "extract", {"tab_id": 7, "format": "text"}
    )

    assert result["success"] is False
    assert "evil.com" in result["error"]
    assert sent == []


async def test_policy_fails_closed_for_unknown_target_tab(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    sent = _recorder_ext(manager, "e1")
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.current_url = "https://example.com/allowed-active-tab"

    result = await manager.send_command(
        "sess", "click_selector", {"tab_id": 999, "selector": "button"}
    )

    assert result["success"] is False
    assert "unknown" in result["error"].lower()
    assert sent == []


async def test_policy_disables_evaluate(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, allow_evaluate=False)
    _recorder_ext(manager, "e1")
    result = await manager.send_command("sess", "evaluate", {"script": "1+1"})
    assert result["success"] is False and "evaluate" in result["error"].lower()


async def test_policy_disabled_refuses_all(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, enabled=False)
    _recorder_ext(manager, "e1")
    result = await manager.send_command(
        "sess", "navigate", {"url": "https://example.com"}
    )
    assert result["success"] is False and "disabled" in result["error"].lower()


# ── Audit trail ───────────────────────────────────────────────────────────────


async def test_audit_records_refusals_and_endpoint(
    client: TestClient, manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    await manager.send_command("sess", "navigate", {"url": "https://evil.com"})

    entries = manager.audit_entries()
    assert entries and entries[0]["action"] == "navigate"
    assert entries[0]["success"] is False
    assert entries[0]["url"] == "https://evil.com"

    resp = client.get(f"{_PREFIX}/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"][0]["action"] == "navigate"
    assert body["entries"][0]["error"]


# ── Tool-level: new element/wait/tab actions ──────────────────────────────────


async def test_tool_snapshot_lists_elements(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {
                "title": "Account settings",
                "url": "https://example.com/settings",
                "viewport": {"width": 1280, "height": 720, "scrollX": 0, "scrollY": 40},
                "elements": [
                    {
                        "role": "checkbox",
                        "name": "Email alerts",
                        "selector": "#alerts",
                        "state": {"checked": False, "disabled": False},
                        "attributes": {"type": "checkbox"},
                        "box": {"x": 100, "y": 40},
                    },
                ],
            },
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "snapshot"})])
    assert isinstance(result, str)
    assert "Page snapshot: Account settings" in result
    assert "https://example.com/settings" in result
    assert "1280x720 css-px at (0, 40)" in result
    assert "Email alerts" in result and "#alerts" in result and "@(100,40)" in result
    assert "checked=false" in result and "type='checkbox'" in result


async def test_tool_click_selector_maps_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "click_selector", "selector": "#go", "index": 2})]
    )
    assert "Clicked '#go'" in result
    assert seen == [("click_selector", {"selector": "#go", "index": 2})]


async def test_tool_fill_submit_and_tab_id(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    await webbridge(
        actions=[
            _action(
                {
                    "action": "fill",
                    "selector": "#q",
                    "value": "hello",
                    "submit": True,
                    "tab_id": 7,
                }
            )
        ]
    )
    assert seen[0][0] == "fill"
    assert seen[0][1] == {
        "selector": "#q",
        "value": "hello",
        "clear": True,
        "submit": True,
        "tab_id": 7,
    }


async def test_tool_rich_interaction_actions_map_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        data = (
            {"selected": [{"value": "vn", "label": "Vietnam", "index": 1}]}
            if action == "select_option"
            else {}
        )
        return {"success": True, "data": data, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "hover", "selector": ".menu", "index": 1, "tab_id": 7}),
            _action({"action": "focus", "selector": "#search", "tab_id": 7}),
            _action(
                {
                    "action": "select_option",
                    "selector": "#country",
                    "values": ["Vietnam"],
                    "match": "label",
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "set_checked",
                    "selector": "#terms",
                    "checked": True,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "drag",
                    "source_selector": "#card",
                    "target_selector": "#done",
                    "steps": 12,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "wait_for_text",
                    "text": "Saved",
                    "selector": "#toast",
                    "exact": True,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "key",
                    "key": "a",
                    "modifiers": ["Meta", "Shift"],
                    "tab_id": 7,
                }
            ),
        ]
    )

    assert isinstance(result, str)
    assert "Hovered '.menu'" in result
    assert '"label": "Vietnam"' in result
    assert "Meta+Shift+a" in result
    assert seen == [
        ("hover", {"selector": ".menu", "index": 1, "tab_id": 7}),
        ("focus", {"selector": "#search", "index": 0, "tab_id": 7}),
        (
            "select_option",
            {
                "selector": "#country",
                "values": ["Vietnam"],
                "match": "label",
                "tab_id": 7,
            },
        ),
        (
            "set_checked",
            {"selector": "#terms", "checked": True, "index": 0, "tab_id": 7},
        ),
        (
            "drag",
            {
                "source_selector": "#card",
                "target_selector": "#done",
                "source_index": 0,
                "target_index": 0,
                "steps": 12,
                "tab_id": 7,
            },
        ),
        (
            "wait_for_text",
            {
                "text": "Saved",
                "selector": "#toast",
                "state": "visible",
                "exact": True,
                "timeout_ms": 10000,
                "tab_id": 7,
            },
        ),
        ("key", {"key": "a", "modifiers": ["Meta", "Shift"], "tab_id": 7}),
    ]


async def test_tool_open_and_close_tab(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 42}, "error": None}
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "open_tab", "url": "https://x.test"}),
            _action({"action": "close_tab", "id": 42}),
        ]
    )
    assert "id=42" in result
    assert "Closed tab" in result


async def test_tool_switch_tab_accepts_id_without_index(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: (
            seen.append((action, params))
            or {"success": True, "data": {}, "error": None}
        ),
    )

    result = await webbridge(actions=[_action({"action": "switch_tab", "id": 42})])

    assert result == "Switched to tab id=42"
    assert seen == [("switch_tab", {"id": 42})]


async def test_tool_tab_id_omitted_when_unset(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: (
            seen.append((a, p)) or {"success": True, "data": {}, "error": None}
        ),
    )
    await webbridge(actions=[_action({"action": "back"})])
    assert seen == [
        ("back", {})
    ]  # tab_id omitted entirely when the model didn't set one

    seen.clear()
    await webbridge(actions=[_action({"action": "extract"})])
    assert "tab_id" not in seen[0][1]  # still omitted; other extract params present
    assert seen[0][1]["format"] == "text"


# ── Tool-level: crawl actions ─────────────────────────────────────────────────


async def test_tool_extract_markdown_maps_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {"title": "T", "url": "u", "content": "# Hi", "format": "markdown"},
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "extract",
                    "format": "markdown",
                    "selector": "article",
                    "max_chars": 500,
                }
            )
        ]
    )
    assert seen[0][0] == "extract"
    assert seen[0][1] == {"format": "markdown", "selector": "article", "max_chars": 500}
    assert "# Hi" in result and "markdown" in result


async def test_tool_extract_elements_returns_records(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {
                "records": [
                    {"title": "A", "url": "https://x/a"},
                    {"title": "B", "url": "https://x/b"},
                ]
            },
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "extract_elements",
                    "selector": ".card",
                    "fields": {"title": "h3", "url": "a@href"},
                }
            )
        ]
    )
    assert seen[0][0] == "extract_elements"
    assert seen[0][1]["selector"] == ".card"
    assert seen[0][1]["fields"] == {"title": "h3", "url": "a@href"}
    assert "2 record" in result and "https://x/a" in result


async def test_tool_extract_elements_empty(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: {"success": True, "data": {"records": []}, "error": None},
    )
    result = await webbridge(
        actions=[_action({"action": "extract_elements", "selector": ".none"})]
    )
    assert "No elements matched" in result


async def test_tool_scroll_to_bottom(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {"scrolls": 3, "final_height": 4200, "at_bottom": True},
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "scroll_to_bottom", "max_scrolls": 5})]
    )
    assert seen[0][0] == "scroll_to_bottom"
    assert seen[0][1]["max_scrolls"] == 5
    assert "3 step" in result and "reached bottom" in result


# ── Tool-level: wait_for_network_idle + crawl ─────────────────────────────────


async def test_tool_wait_for_network_idle_reports_idle(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {"idle": True, "inflight": 0}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "wait_for_network_idle", "idle_ms": 800})]
    )
    assert seen[0] == ("wait_for_network_idle", {"idle_ms": 800, "timeout_ms": 20000})
    assert "Network idle" in result


async def test_tool_wait_for_network_idle_reports_timeout(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: {
            "success": True,
            "data": {"idle": False, "inflight": 2, "timed_out": True},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "wait_for_network_idle"})])
    assert "still active" in result and "2 request" in result


async def test_tool_crawl_requires_urls(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: (
            seen.append((a, p)) or {"success": True, "data": {}, "error": None}
        ),
    )
    result = await webbridge(actions=[_action({"action": "crawl", "urls": []})])
    assert "at least one URL" in result
    assert seen == []  # no commands issued for an empty url list


async def test_tool_crawl_runs_pages_concurrently(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    """The whole point of `crawl` is real overlap across tabs, not a serial

    loop dressed up as one — so this drives the semaphore with a handler that
    actually suspends (asyncio.sleep) and records the high-water mark of
    simultaneously in-flight ``wait_for_load`` calls.
    """
    tab_counter = 0
    concurrent = 0
    max_concurrent = 0

    async def fake_send_command(
        session_id: str, action: str, params: dict | None = None
    ):
        nonlocal tab_counter, concurrent, max_concurrent
        params = params or {}
        if action == "open_tab":
            tab_counter += 1
            return {"success": True, "data": {"tab_id": tab_counter}, "error": None}
        if action == "wait_for_load":
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1
            return {"success": True, "data": {}, "error": None}
        if action == "extract":
            return {
                "success": True,
                "data": {"title": "T", "content": f"body-{params['tab_id']}"},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}  # close_tab

    monkeypatch.setattr(manager, "send_command", fake_send_command)

    urls = [f"https://example.com/{i}" for i in range(6)]
    result = await webbridge(
        actions=[_action({"action": "crawl", "urls": urls, "concurrency": 3})]
    )

    assert (
        max_concurrent == 3
    )  # genuinely overlapped, capped exactly at the semaphore size
    assert "Crawled 6 URL(s) (3 at a time): 6 ok, 0 failed" in result
    # asyncio.gather preserves input order in the result regardless of completion order
    assert result.index(urls[0]) < result.index(urls[-1])
    for url in urls:
        assert url in result


async def test_tool_crawl_networkidle_and_elements_mode(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, dict(params)))
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 9}, "error": None}
        if action == "extract_elements":
            return {
                "success": True,
                "data": {"records": [{"title": "A"}]},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "crawl",
                    "urls": ["https://example.com/a"],
                    "wait": "networkidle",
                    "elements_selector": ".card",
                    "fields": {"title": "h3"},
                }
            )
        ]
    )
    actions_seen = [a for a, _ in seen]
    assert "wait_for_network_idle" in actions_seen
    assert "wait_for_load" not in actions_seen
    extract_elements_call = next(p for a, p in seen if a == "extract_elements")
    assert extract_elements_call == {
        "tab_id": 9,
        "selector": ".card",
        "fields": {"title": "h3"},
        "limit": 100,
    }
    assert "1 record" in result and '"title": "A"' in result


async def test_tool_crawl_isolates_per_page_errors(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "open_tab":
            if params["url"].endswith("/bad"):
                return {"success": False, "data": None, "error": "boom"}
            return {"success": True, "data": {"tab_id": 1}, "error": None}
        if action == "extract":
            return {
                "success": True,
                "data": {"title": "Good", "content": "all fine"},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "crawl", "urls": ["https://x/good", "https://x/bad"]})
        ]
    )
    assert "1 ok, 1 failed" in result
    assert "ERROR: open_tab failed: boom" in result
    assert "Title: Good" in result and "all fine" in result


async def test_tool_crawl_close_tabs_false_skips_close(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[str] = []

    def handler(action: str, params: dict):
        seen.append(action)
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 1}, "error": None}
        return {"success": True, "data": {"content": "ok"}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    await webbridge(
        actions=[
            _action({"action": "crawl", "urls": ["https://x/a"], "close_tabs": False})
        ]
    )
    assert "close_tab" not in seen


# ── POST /launch-browser ─────────────────────────────────────────────────────


class _PopenRecorder:
    """subprocess.Popen stand-in that records argv/kwargs, never spawns."""

    instances: list[dict] = []

    def __init__(self, argv, **kwargs):
        _PopenRecorder.instances.append({"argv": list(argv), "kwargs": kwargs})


@pytest.fixture
def ext_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the extension-dir override at a real (empty) tmp directory."""
    d = tmp_path / "webbridge-ext"
    d.mkdir()
    monkeypatch.setenv("EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(d))
    return d


class TestLaunchBrowser:
    @pytest.fixture(autouse=True)
    def _record_popen(self, monkeypatch: pytest.MonkeyPatch):
        _PopenRecorder.instances = []
        monkeypatch.setattr(subprocess, "Popen", _PopenRecorder)

    def test_darwin_argv(self, client, ext_dir, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["browser"] == "chrome"
        # Caveats the UI must surface.
        assert "FULLY quit" in data["message"]
        assert "developer-mode" in data["message"]
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "open",
            "-na",
            "Google Chrome",
            "--args",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]
        assert call["kwargs"]["start_new_session"] is True

    def test_linux_argv_google_chrome(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chrome"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "/usr/bin/google-chrome",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]

    def test_linux_argv_chromium_label(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/chromium" if name == "chromium" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chromium"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "/usr/bin/chromium",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]

    def test_linux_no_browser_500(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 500
        assert "google-chrome" in resp.json()["detail"]
        assert _PopenRecorder.instances == []

    def test_win32_argv_with_creationflags(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: r"C:\chrome\chrome.exe" if name == "chrome" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chrome"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            r"C:\chrome\chrome.exe",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]
        assert "creationflags" in call["kwargs"]

    def test_missing_extension_dir_404(
        self, client, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(
            "EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(tmp_path / "does-not-exist")
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "EVOFLUX_WEBBRIDGE_EXTENSION_DIR" in detail
        # Manual-install instructions are part of the pinned contract.
        assert "chrome://extensions" in detail
        assert _PopenRecorder.instances == []

    def test_popen_failure_500(self, client, ext_dir, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def _boom(*args, **kwargs):
            raise OSError("no opener")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 500
        assert "no opener" in resp.json()["detail"]


# ── GET /download (extension package) ─────────────────────────────────────────


def test_download_extension_zip(client: TestClient, ext_dir):
    (ext_dir / "manifest.json").write_text('{"name":"x"}', encoding="utf-8")
    (ext_dir / "background.js").write_text("// bg", encoding="utf-8")
    icons = ext_dir / "icons"
    icons.mkdir()
    (icons / "icon16.png").write_bytes(b"\x89PNG\r\n")
    (ext_dir / ".DS_Store").write_bytes(b"junk")  # must be skipped

    resp = client.get(f"{_PREFIX}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "evoflux-webbridge.zip" in resp.headers["content-disposition"]

    names = set(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())
    assert "webbridge/manifest.json" in names
    assert "webbridge/background.js" in names
    assert "webbridge/icons/icon16.png" in names
    assert not any(".DS_Store" in n for n in names)


def test_download_missing_dir_404(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(tmp_path / "nope"))
    resp = client.get(f"{_PREFIX}/download")
    assert resp.status_code == 404
