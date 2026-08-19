from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

from app.services.direct_browser_bridge import (
    DirectBrowserBridge,
    DirectBrowserUnavailable,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.received: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def send_json(self, value: dict[str, Any]) -> None:
        await self.sent.put(value)

    async def receive_json(self) -> dict[str, Any]:
        value = await self.received.get()
        if value is None:
            raise WebSocketDisconnect()
        return value

    async def receive_text(self) -> str:
        value = await self.received.get()
        if value is None:
            raise WebSocketDisconnect()
        return str(value)


@pytest.mark.asyncio
async def test_bridge_round_trip() -> None:
    bridge = DirectBrowserBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await asyncio.sleep(0)
    await websocket.received.put({"type": "ready", "version": 1})
    await asyncio.sleep(0)

    request_task = asyncio.create_task(
        bridge.request("session-1", "navigate", {"url": "https://example.com"})
    )
    command = await websocket.sent.get()
    await websocket.received.put(
        {"id": command["id"], "ok": True, "result": "Navigated"}
    )

    assert await request_task == "Navigated"
    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_bridge_serializes_concurrent_browser_commands() -> None:
    bridge = DirectBrowserBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put({"type": "ready", "version": 1})
    await asyncio.sleep(0)

    first = asyncio.create_task(
        bridge.request("session-1", "navigate", {"url": "https://a.test"})
    )
    second = asyncio.create_task(bridge.request("session-1", "click", {"index": 1}))
    first_command = await websocket.sent.get()
    await asyncio.sleep(0)
    assert websocket.sent.empty()

    await websocket.received.put(
        {"id": first_command["id"], "ok": True, "result": "first"}
    )
    assert await first == "first"
    second_command = await websocket.sent.get()
    assert second_command["action"] == "click"
    await websocket.received.put(
        {"id": second_command["id"], "ok": True, "result": "second"}
    )
    assert await second == "second"

    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_bridge_negotiates_capabilities_and_rejects_unknown_command() -> None:
    bridge = DirectBrowserBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach("session-1", websocket))
    await websocket.received.put(
        {
            "type": "ready",
            "protocol_version": 2,
            "capabilities": {"commands": ["snapshot"], "features": ["multi_tab"]},
        }
    )
    await asyncio.sleep(0)

    assert bridge.connection_info("session-1") == (
        2,
        {"commands": ["snapshot"], "features": ["multi_tab"]},
    )
    with pytest.raises(DirectBrowserUnavailable, match="does not support 'download'"):
        await bridge.request("session-1", "download", {"url": "https://example.com"})
    assert websocket.sent.empty()

    await websocket.received.put(None)
    await attach_task


@pytest.mark.asyncio
async def test_bridge_requires_connected_browser() -> None:
    bridge = DirectBrowserBridge()

    with pytest.raises(DirectBrowserUnavailable, match="Open the Browser panel"):
        await bridge.request("missing", "snapshot", {})


@pytest.mark.asyncio
async def test_presence_requests_browser_mount() -> None:
    bridge = DirectBrowserBridge()
    websocket = _FakeWebSocket()
    attach_task = asyncio.create_task(bridge.attach_presence("session-1", websocket))
    await asyncio.sleep(0)

    assert bridge.is_available("session-1") is True
    assert await bridge.request_mount("session-1") is True
    assert await websocket.sent.get() == {"action": "open"}

    await websocket.received.put(None)
    await attach_task
    assert bridge.is_available("session-1") is False
