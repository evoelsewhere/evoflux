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
