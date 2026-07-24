from __future__ import annotations

import json

import pytest

from scripts.webbridge_office_smoke import exchange


class FakeWebSocket:
    def __init__(self, frames: list[dict]) -> None:
        self.frames = [json.dumps(frame) for frame in frames]
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        return self.frames.pop(0)


@pytest.mark.asyncio
async def test_exchange_uses_flat_agent_protocol_and_skips_events():
    ws = FakeWebSocket(
        [
            {"type": "event", "event": "tab_updated", "data": {}},
            {"type": "response", "success": True, "data": {"status": "ok"}},
        ]
    )
    response = await exchange(
        ws,
        "semantic_read",
        {"target": {"kind": "active_text", "scope": "selection"}},
    )
    assert ws.sent == [
        {
            "action": "semantic_read",
            "target": {"kind": "active_text", "scope": "selection"},
        }
    ]
    assert response["data"]["status"] == "ok"
