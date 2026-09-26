from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

from app.services.direct_computer_bridge import (
    DirectComputerBridge,
    DirectComputerUnavailable,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.received: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.closed_with: int | None = None

    async def send_json(self, value: dict[str, Any]) -> None:
        await self.sent.put(value)

    async def receive_json(self) -> dict[str, Any]:
        value = await self.received.get()
        if value is None:
            raise WebSocketDisconnect()
        return value

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code
        await self.received.put(None)


@pytest.mark.asyncio
async def test_bridge_round_trip_and_error() -> None:
    bridge = DirectComputerBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put(
        {"type": "ready", "protocol_version": 1, "capabilities": {"commands": []}}
    )
    await asyncio.sleep(0)
    assert bridge.is_connected("session-1")

    request_task = asyncio.create_task(bridge.request("session-1", "list_windows", {}))
    command = await websocket.sent.get()
    assert command["action"] == "list_windows"
    await websocket.received.put(
        {"id": command["id"], "ok": True, "result": {"windows": []}}
    )
    assert await request_task == {"windows": []}

    failing = asyncio.create_task(bridge.request("session-1", "click", {"x": 1}))
    command = await websocket.sent.get()
    await websocket.received.put(
        {"id": command["id"], "ok": False, "error": "outside the screenshot"}
    )
    with pytest.raises(RuntimeError, match="outside the screenshot"):
        await failing

    await websocket.received.put(None)
    await attach_task
    assert not bridge.is_connected("session-1")


@pytest.mark.asyncio
async def test_a_command_waits_for_the_desktop_to_reconnect() -> None:
    bridge = DirectComputerBridge()
    websocket = _FakeWebSocket()
    request_task = asyncio.create_task(bridge.request("session-1", "status", {}))
    await asyncio.sleep(0.15)
    assert not request_task.done()

    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put({"type": "ready"})
    command = await websocket.sent.get()
    await websocket.received.put({"id": command["id"], "ok": True, "result": "ok"})
    assert await request_task == "ok"

    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_a_timed_out_command_is_cancelled_on_the_desktop() -> None:
    bridge = DirectComputerBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put({"type": "ready"})
    await asyncio.sleep(0)

    with pytest.raises(TimeoutError, match="told to stop it"):
        await bridge.request("session-1", "type", {"text": "x"}, timeout=0.05)

    command = await websocket.sent.get()
    assert command["action"] == "type"
    assert await websocket.sent.get() == {"type": "cancel"}

    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_bridge_rejects_commands_the_shell_does_not_advertise() -> None:
    bridge = DirectComputerBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put(
        {
            "type": "ready",
            "protocol_version": 1,
            "capabilities": {"commands": ["status"]},
        }
    )
    await asyncio.sleep(0)

    with pytest.raises(DirectComputerUnavailable, match="does not support 'drag'"):
        await bridge.request("session-1", "drag", {})
    assert websocket.sent.empty()

    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_newer_attach_displaces_older_socket() -> None:
    bridge = DirectComputerBridge()
    first = _FakeWebSocket()
    first_task = asyncio.create_task(bridge.attach("session-1", first))
    await first.received.put({"type": "ready"})
    await asyncio.sleep(0)
    pending = asyncio.create_task(bridge.request("session-1", "status", {}))
    await first.sent.get()

    second = _FakeWebSocket()
    second_task = asyncio.create_task(bridge.attach("session-1", second))
    await asyncio.sleep(0)

    assert first.closed_with == 4409
    with pytest.raises(DirectComputerUnavailable, match="reconnected"):
        await pending
    await first_task

    await second.received.put({"type": "ready"})
    await asyncio.sleep(0)
    assert bridge.is_connected("session-1")
    await second.received.put(None)
    with suppress(WebSocketDisconnect):
        await second_task


@pytest.mark.asyncio
async def test_request_requires_connected_desktop() -> None:
    bridge = DirectComputerBridge()
    bridge.reconnect_grace = 0.05

    with pytest.raises(
        DirectComputerUnavailable, match="EvoFlux Desktop on Windows or macOS"
    ):
        await bridge.request("missing", "status", {})
    assert await bridge.wait_connected("missing", timeout=0.05) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"attached": True}, ["status", "detach"]),
        # A stopped card must stay open, and nothing else is there to release.
        ({"attached": False, "stopped": True}, ["status"]),
    ],
)
async def test_a_finished_turn_hands_back_an_attached_app(
    monkeypatch, status: dict[str, Any], expected: list[str]
) -> None:
    bridge = DirectComputerBridge()
    sent: list[str] = []
    monkeypatch.setattr(bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, _params: dict, timeout: float = 60.0):
        sent.append(action)
        return status if action == "status" else {"detached": True}

    monkeypatch.setattr(bridge, "request", request)

    await bridge.release_after_turn("chat-in-background")

    assert sent == expected


@pytest.mark.asyncio
async def test_a_finished_turn_without_a_desktop_does_nothing() -> None:
    bridge = DirectComputerBridge()
    bridge.reconnect_grace = 5.0

    await asyncio.wait_for(bridge.release_after_turn("no-desktop"), timeout=0.5)


@pytest.mark.asyncio
async def test_turn_done_listeners_hear_every_finished_turn() -> None:
    from app.services import memory_stream_store as stream_store

    heard: list[str] = []

    async def listener(session_id: str) -> None:
        heard.append(session_id)

    stream_store.add_turn_done_listener(listener)
    try:
        await stream_store.init_turn("turn-done-test")
        await stream_store.mark_done("turn-done-test")
        await asyncio.sleep(0)
        assert heard == ["turn-done-test"]
    finally:
        stream_store._turn_done_listeners.remove(listener)
        await stream_store.clear("turn-done-test")
