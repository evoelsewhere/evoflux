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


async def test_a_turn_is_priced_per_call_not_from_its_totals() -> None:
    """Rates are per model, so a turn that switched models needs per-call pricing.

    An agent's turn routinely mixes an expensive main call with a cheap
    auxiliary one (title generation, memory extraction). Pricing the turn's
    summed tokens at either model's rate is wrong in both directions.
    """
    from app.agent.turn_usage import TurnUsageTracker
    from app.agent.usage import estimate_cost

    tracker = TurnUsageTracker("session-1", "lead")
    main = Usage(prompt_tokens=12_000, completion_tokens=800, cached_tokens=9_000)
    auxiliary = Usage(prompt_tokens=400, completion_tokens=60)
    tracker.record(main, phase="main", model_id="anthropic:claude-sonnet-4-5")
    tracker.record(auxiliary, phase="title", model_id="anthropic:claude-haiku-4-5")

    snapshot = tracker.snapshot()
    expected = sum(
        cost["estimated_usd"]
        for cost in (
            estimate_cost(
                "anthropic:claude-sonnet-4-5",
                input_tokens=12_000,
                output_tokens=800,
                cached_tokens=9_000,
            ),
            estimate_cost(
                "anthropic:claude-haiku-4-5",
                input_tokens=400,
                output_tokens=60,
            ),
        )
        if cost
    )
    assert snapshot["cost"]["estimated_usd"] == round(expected, 6)
    # Each phase keeps its own price, so a burn report can name the
    # auxiliary call that quietly costs more than the work it supports.
    assert snapshot["phases"]["title"]["cost"]["estimated_usd"] > 0
    assert (
        snapshot["phases"]["main"]["cost"]["estimated_usd"]
        > snapshot["phases"]["title"]["cost"]["estimated_usd"]
    )


async def test_cache_reads_are_not_billed_at_the_input_rate() -> None:
    """The component split is the point: cache traffic is what a caller can act on."""
    from app.agent.turn_usage import TurnUsageTracker

    tracker = TurnUsageTracker("session-1", "lead")
    tracker.record(
        Usage(prompt_tokens=10_000, completion_tokens=100, cached_tokens=9_500),
        phase="main",
        model_id="anthropic:claude-sonnet-4-5",
    )

    cost = tracker.snapshot()["cost"]
    assert cost["cache_read_usd"] > 0
    # 500 uncached input tokens against 9,500 cached ones: a flat input rate
    # would price this turn roughly ten times too high.
    assert cost["input_usd"] < cost["cache_read_usd"]


async def test_a_seat_billed_provider_reports_tokens_without_a_price() -> None:
    """Copilot and Codex bill a subscription; inventing a dollar figure lies."""
    from app.agent.turn_usage import TurnUsageTracker

    tracker = TurnUsageTracker("session-1", "lead")
    tracker.record(
        Usage(prompt_tokens=5_000, completion_tokens=500),
        phase="main",
        model_id="copilot:gpt-5",
    )

    snapshot = tracker.snapshot()
    assert snapshot["input"] == 5_000
    assert "cost" not in snapshot


async def test_published_totals_carry_the_price() -> None:
    token = begin_turn_usage("session-1", "lead")
    pushed = []
    try:
        with patch(
            "app.services.memory_stream_store.push_event",
            new_callable=AsyncMock,
            side_effect=lambda _session_id, event: pushed.append(event),
        ):
            await record_turn_usage(
                Usage(prompt_tokens=2_000, completion_tokens=300),
                phase="main",
                model_id="anthropic:claude-sonnet-4-5",
            )
    finally:
        end_turn_usage(token)

    assert len(pushed) == 1
    payload = pushed[0].model_dump()["data"]
    assert payload["cost"]["estimated_usd"] > 0
    assert payload["metadata"]["turn_total"] is True


class _FakeState:
    def __init__(
        self, active_model: str | None, effective_model: str | None = None
    ) -> None:
        self.metadata: dict[str, object] = {}
        if active_model is not None:
            self.metadata["active_model"] = active_model
        if effective_model is not None:
            self.metadata["effective_model"] = effective_model


def test_a_providers_own_model_name_is_qualified_before_pricing() -> None:
    """A stream chunk names the model the provider's way, not the catalog's.

    Xiaomi sends ``mimo-v2.5``; nothing in models.dev matches that, so a
    turn priced from it comes back free — and the main call holds nearly
    all of a turn's tokens, so the whole turn reads as costing nothing.
    """
    from app.agent.hooks.stream_publisher import _catalog_model_id
    from app.agent.usage import estimate_cost

    resolved = _catalog_model_id("mimo-v2.5", _FakeState("xiaomi:mimo-v2.5"))
    assert resolved == "xiaomi:mimo-v2.5"
    assert estimate_cost(resolved, input_tokens=100_000, output_tokens=500)
    assert estimate_cost("mimo-v2.5", input_tokens=100_000, output_tokens=500) is None


def test_a_bedrock_id_is_not_mistaken_for_a_qualified_one() -> None:
    """Bedrock model ids carry a colon of their own, in the version suffix."""
    from app.agent.hooks.stream_publisher import _catalog_model_id

    state = _FakeState("bedrock:us.anthropic.claude-sonnet-4-5-v1:0")
    assert (
        _catalog_model_id("us.anthropic.claude-sonnet-4-5-v1:0", state)
        == "bedrock:us.anthropic.claude-sonnet-4-5-v1:0"
    )


def test_an_already_qualified_id_is_left_alone() -> None:
    from app.agent.hooks.stream_publisher import _catalog_model_id

    state = _FakeState("xiaomi:mimo-v2.5")
    assert _catalog_model_id("xiaomi:mimo-v2.5", state) == "xiaomi:mimo-v2.5"
    assert _catalog_model_id(None, state) is None
    # Nothing to borrow a provider from: report what the provider said
    # rather than inventing a prefix that would price the wrong model.
    assert _catalog_model_id("mimo-v2.5", _FakeState(None)) == "mimo-v2.5"


def test_a_provider_fallback_prices_against_the_model_it_fell_back_to() -> None:
    """A run that switched providers must not be priced at the first one's rates."""
    from app.agent.hooks.stream_publisher import _catalog_model_id

    state = _FakeState("openai:gpt-5", effective_model="anthropic:claude-sonnet-4-5")
    assert _catalog_model_id("claude-sonnet-4-5", state) == (
        "anthropic:claude-sonnet-4-5"
    )
