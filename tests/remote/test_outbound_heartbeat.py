from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

import app.remote.outbound as outbound
from app.remote.outbound import RemoteProjection
from tests.remote.test_outbound import FakeAdapter


@pytest.mark.asyncio
async def test_live_process_card_heartbeats_without_new_events(monkeypatch) -> None:
    monkeypatch.setattr(outbound, "_PROCESS_HEARTBEAT_SECONDS", 0.01)
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    connection_id = str(uuid4())
    projection.register_session(
        "heartbeat-session",
        connection_id=connection_id,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "heartbeat-session",
        connection_id=connection_id,
        destination_id="chat-1",
        principal_id="user-1",
        title="Long-running task",
        status="working",
        response_mode="live",
    )
    await projection.drain_pending()

    await asyncio.sleep(0.05)
    assert len(adapter.edited) >= 1

    projection.observe(
        "heartbeat-session",
        type("Envelope", (), {"event": "done", "data": {}})(),
    )
    await projection.drain_pending()
    await asyncio.sleep(0)
    assert projection._turns["heartbeat-session"].process_heartbeat_task is None
