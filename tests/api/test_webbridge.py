"""WebBridge — manager, relay WS endpoints, auth, and tool-level tests.

The relay endpoints run in a real (in-process) app via ``TestClient``; the
manager is exercised directly with a fake ``send`` callable for the
correlation/timeout paths that are awkward to drive over the wire.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

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

            agent_ws.send_text(json.dumps({"action": "navigate", "url": "https://x.dev"}))
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
            agent_ws.send_text(json.dumps({"action": "navigate", "url": "https://x.dev"}))
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

    task = asyncio.create_task(manager.send_command("sess", "navigate", {"url": "https://x"}))
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


def test_ws_rejected_with_wrong_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"{_PREFIX}/relay?_token=nope"):
            pass
    assert exc_info.value.code == 4401


def test_ws_accepted_with_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with client.websocket_connect(f"{_PREFIX}/relay?_token=secret-token") as ws:
        assert _register(ws)["type"] == "registered"
    with client.websocket_connect(f"{_PREFIX}/agent/s1?_token=secret-token") as agent_ws:
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
    async def fake_send_command(session_id: str, action: str, params: dict | None = None):
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
    result = await webbridge(actions=[_action({"action": "navigate", "url": "https://example.com"})])
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
    assert text.text == f"Screenshot captured (png, {len(raw)} bytes)."


async def test_tool_aggregates_action_errors(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "click":
            return {"success": False, "data": None, "error": "boom"}
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "click", "x": 10, "y": 20}), _action({"action": "type", "text": "abc"})]
    )
    assert isinstance(result, str)
    assert "Click failed: boom" in result
    assert "Typed 3 characters" in result
    assert "\n---\n" in result
