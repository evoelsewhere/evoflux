from __future__ import annotations

import asyncio
import threading

import pytest

from app.remote.outbound import RemoteProjection
from tests.remote.test_outbound import FakeAdapter


@pytest.mark.asyncio
async def test_worker_thread_schedules_pending_delivery_on_owner_loop() -> None:
    adapter = FakeAdapter()
    projection = RemoteProjection()
    projection.set_adapter(adapter)
    projection._enqueue_send(destination_id="chat-1", text="Done")

    worker = threading.Thread(target=projection._schedule_drain)
    worker.start()
    worker.join()
    await asyncio.sleep(0.05)

    assert [message.text for message in adapter.sent] == ["Done"]
