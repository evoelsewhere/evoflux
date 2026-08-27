from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.agent.schemas.chat import Usage
from app.agent.turn_usage import (
    begin_turn_usage,
    current_turn_usage_snapshot,
    end_turn_usage,
    record_turn_usage,
)


async def test_turn_usage_aggregates_phases_and_publishes_totals() -> None:
    pushed = []
    token = begin_turn_usage("session-1", "lead")
    try:
        with patch(
            "app.services.memory_stream_store.push_event",
            new_callable=AsyncMock,
            side_effect=lambda _session_id, event: pushed.append(event),
        ):
            await record_turn_usage(
                Usage(
                    prompt_tokens=14_200,
                    completion_tokens=17,
                    total_tokens=14_217,
                    cached_tokens=2_000,
                    cache_write_tokens=1_000,
                ),
                phase="main",
                model_id="codex:gpt-test",
            )
            await record_turn_usage(
                {
                    "input": 2_800,
                    "output": 12,
                    "cache": 500,
                    "cache_write": 200,
                },
                phase="skill_resolver",
                model_id="codex:gpt-test",
            )

        snapshot = current_turn_usage_snapshot()
        assert snapshot == {
            "input": 17_000,
            "output": 29,
            "cache": 2_500,
            "cache_write": 1_200,
            "calls": 2,
            "models": ["codex:gpt-test"],
            "phases": {
                "main": {
                    "input": 14_200,
                    "output": 17,
                    "cache": 2_000,
                    "cache_write": 1_000,
                    "calls": 1,
                    "models": ["codex:gpt-test"],
                },
                "skill_resolver": {
                    "input": 2_800,
                    "output": 12,
                    "cache": 500,
                    "cache_write": 200,
                    "calls": 1,
                    "models": ["codex:gpt-test"],
                },
            },
        }
        assert len(pushed) == 2
        assert pushed[-1].data["prompt_tokens"] == 17_000
        assert pushed[-1].data["completion_tokens"] == 29
        assert pushed[-1].data["cache_write_tokens"] == 1_200
        assert pushed[-1].data["metadata"]["turn_total"] is True
        assert pushed[-1].data["metadata"]["calls"] == 2
    finally:
        end_turn_usage(token)


async def test_turn_usage_is_a_noop_without_bound_turn() -> None:
    assert (
        await record_turn_usage(
            {"input": 100, "output": 10},
            phase="title",
        )
        is None
    )


async def test_concurrent_auxiliary_usage_cannot_publish_stale_totals() -> None:
    pushed = []
    first_publish_started = asyncio.Event()
    release_first_publish = asyncio.Event()

    async def delayed_push(_session_id, event) -> None:
        if not pushed:
            first_publish_started.set()
            await release_first_publish.wait()
        pushed.append(event)

    token = begin_turn_usage("session-1", "lead")
    try:
        with patch(
            "app.services.memory_stream_store.push_event",
            new_callable=AsyncMock,
            side_effect=delayed_push,
        ):
            first = asyncio.create_task(
                record_turn_usage(
                    {"input": 100, "output": 10},
                    phase="title",
                )
            )
            await first_publish_started.wait()
            second = asyncio.create_task(
                record_turn_usage(
                    {"input": 50, "output": 5},
                    phase="main",
                )
            )
            await asyncio.sleep(0)
            release_first_publish.set()
            await asyncio.gather(first, second)
    finally:
        end_turn_usage(token)

    assert [event.data["prompt_tokens"] for event in pushed] == [100, 150]
    assert [event.data["metadata"]["calls"] for event in pushed] == [1, 2]
