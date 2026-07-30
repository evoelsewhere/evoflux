"""Interactive terminal WebSocket endpoint — in-process integration test of
the ws ↔ PTY bridge (the seam a browser click would exercise)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.team.terminal import router
from app.services.terminal_service import terminal_manager


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/team")
    return TestClient(app)


def test_terminals_list_and_delete(client):
    sid = "ws-term-tabs"
    # Opening then closing the socket leaves the PTY alive (reconnect
    # semantics), so it shows up in the list.
    with client.websocket_connect(f"/api/team/{sid}/terminal?tid=1"):
        pass
    listed = client.get(f"/api/team/{sid}/terminals").json()
    assert {"id": "1"} in listed["terminals"]

    assert client.delete(f"/api/team/{sid}/terminals/1").status_code == 204
    assert client.get(f"/api/team/{sid}/terminals").json()["terminals"] == []


def test_terminal_ws_echo_roundtrip(client):
    sid = "ws-term-1"
    try:
        with client.websocket_connect(
            f"/api/team/{sid}/terminal?cols=80&rows=24"
        ) as ws:
            ws.send_text(
                json.dumps({"type": "input", "data": "echo WS_MARKER_$((2*3))\n"})
            )
            got = b""
            for _ in range(80):
                message = ws.receive()
                if message.get("bytes") is not None:
                    got += message["bytes"]
                elif message.get("text") is not None:
                    payload = json.loads(message["text"])
                    if payload.get("type") == "exit":
                        break
                if b"WS_MARKER_6" in got:
                    break
            assert b"WS_MARKER_6" in got
            # Resize control frame must be accepted without tearing down.
            ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
    finally:
        # The PTY outlives the socket (reconnect semantics) — clean it up.
        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            terminal_manager.close(sid)
        )
