from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.easd_event_stream import (
    publish_run_event,
    reset_for_tests,
    subscribe_run,
)


@pytest.fixture(autouse=True)
def _reset_broker():
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_broker_isolates_runs_and_broadcasts_presence_and_events():
    run_id = uuid4()
    other_run_id = uuid4()
    async with subscribe_run(run_id, "client-a") as first:
        assert (await first.get())["count"] == 1
        async with subscribe_run(run_id, "client-b") as second:
            assert (await first.get())["count"] == 2
            assert (await second.get())["count"] == 2
            async with subscribe_run(other_run_id, "other") as other:
                assert (await other.get())["count"] == 1
                publish_run_event(
                    run_id,
                    {"sequence": 8, "event": "review_retried"},
                )
                await asyncio.sleep(0)
                assert (await first.get())["sequence"] == 8
                assert (await second.get())["event"]["event"] == "review_retried"
                assert other.empty()
        assert (await first.get())["count"] == 1


@pytest.mark.asyncio
async def test_broker_overflow_requires_durable_resync():
    run_id = uuid4()
    async with subscribe_run(run_id, "slow-client") as queue:
        await queue.get()
        for sequence in range(1, 258):
            publish_run_event(
                run_id,
                {"sequence": sequence, "event": "mission_updated"},
            )
        await asyncio.sleep(0)

        assert queue.qsize() == 1
        payload = await queue.get()
        assert payload["type"] == "easd_resync_required"
        assert payload["reason"] == "subscriber_queue_overflow"
