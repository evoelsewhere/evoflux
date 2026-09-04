from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.providers.model_metadata import (
    ModelCost,
    get_model_cost,
    get_model_mode,
)
from app.agent.schemas.chat import Usage


_NON_TOKEN_BILLED_PROVIDERS = frozenset({"codex", "copilot", "kimi", "ollama"})

#: Cost component -> span attribute. Kept flat so the aggregation query
#: can sum each one without parsing a nested value out of a span.
_COST_SPAN_ATTRIBUTES = {
    "input_usd": "gen_ai.usage.cost.input_usd",
    "output_usd": "gen_ai.usage.cost.output_usd",
    "cache_read_usd": "gen_ai.usage.cost.cache_read_usd",
    "cache_write_usd": "gen_ai.usage.cost.cache_write_usd",
    "reasoning_usd": "gen_ai.usage.cost.reasoning_usd",
}


def usage_to_dict(
    usage: Usage, model_id: str | None, service_tier: str | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": usage.prompt_tokens,
        "output": usage.completion_tokens,
    }
    if usage.cached_tokens is not None:
        result["cache"] = usage.cached_tokens
    if usage.cache_write_tokens is not None:
        result["cache_write"] = usage.cache_write_tokens
    if usage.thoughts_tokens is not None:
        result["thoughts"] = usage.thoughts_tokens
    if usage.tool_use_tokens is not None:
        result["tool_use"] = usage.tool_use_tokens

    cost = _estimate_cost(usage, model_id, service_tier)
    if cost:
        result["cost"] = cost
    return result


def set_usage_span_attributes(span: Any, usage: Mapping[str, Any]) -> None:
    input_tokens = usage.get("input", 0)
    output_tokens = usage.get("output", 0)
    cached_tokens = usage.get("cache", 0)
    cache_write_tokens = usage.get("cache_write", 0)
    thoughts_tokens = usage.get("thoughts", 0) or 0
    tool_use_tokens = usage.get("tool_use", 0) or 0

    if input_tokens:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    if cached_tokens:
        span.set_attribute("gen_ai.usage.cache_read.input_tokens", cached_tokens)
    if cache_write_tokens:
        span.set_attribute("gen_ai.usage.cache_write.input_tokens", cache_write_tokens)
    if thoughts_tokens:
        span.set_attribute("gen_ai.usage.reasoning_tokens", thoughts_tokens)
    if tool_use_tokens:
        span.set_attribute("gen_ai.usage.tool_use_tokens", tool_use_tokens)

    cost = usage.get("cost")
    if not isinstance(cost, dict):
        return
    estimated_cost = cost.get("estimated_usd")
    if isinstance(estimated_cost, int | float) and estimated_cost > 0:
        span.set_attribute("gen_ai.usage.estimated_cost_usd", estimated_cost)

    # Each component separately, not just the total. A burn report that says
    # only "this model cost $2,868" cannot tell you that $2,225 of it was
    # cache traffic — which is the half a caller can actually act on.
    for component, attribute in _COST_SPAN_ATTRIBUTES.items():
        value = cost.get(component)
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            span.set_attribute(attribute, float(value))


def _tiered_rates(
    prices: ModelCost, prompt_tokens: int, mode_cost: Mapping[str, float] | None
) -> dict[str, float | None]:
    """The rates that actually apply to this request.

    Three things can move a model off its headline price, and the catalog
    publishes all three:

    - **A long-context tier.** Beyond a threshold the provider bills every
      token of the request at a higher rate — not just the tokens past it.
      Pricing a 300K-token Sonnet turn at the headline rate understates it
      by roughly a third.
    - **An alternate service tier.** A ``fast`` lane bills at 2-2.5x, so a
      turn that used one costs that much more.
    - **Nothing.** The overwhelming majority of turns.

    The service tier wins where it publishes a rate, because it is a
    different product rather than a volume band.
    """
    rates: dict[str, float | None] = {
        "input": prices.input,
        "output": prices.output,
        "cache_read": prices.cache_read,
        "cache_write": prices.cache_write,
        "reasoning": prices.reasoning,
    }

    # Highest applicable threshold wins: a request over 400K is also over
    # 200K, and the provider bills the band it lands in.
    applicable = [
        tier
        for tier in prices.tiers
        if isinstance(tier.get("above_tokens"), int | float)
        and prompt_tokens > tier["above_tokens"]
    ]
    if applicable:
        tier = max(applicable, key=lambda item: item["above_tokens"])
        for field in rates:
            value = tier.get(field)
            if isinstance(value, int | float) and not isinstance(value, bool):
                rates[field] = float(value)

    if mode_cost:
        for field in rates:
            value = mode_cost.get(field)
            if isinstance(value, int | float) and not isinstance(value, bool):
                rates[field] = float(value)

    return rates


def _estimate_cost(
    usage: Usage, model_id: str | None, service_tier: str | None = None
) -> dict[str, float] | None:
    """Price one turn from the catalog's rates, in USD.

    Every rate is per million tokens. Components are kept separate so a
    burn report can show where the money went — cache reads and writes are
    the two that a caller can actually act on.
    """
    provider_id = model_id.partition(":")[0].lower() if model_id else ""
    if provider_id in _NON_TOKEN_BILLED_PROVIDERS:
        return None
    prices = get_model_cost(model_id)

    mode_cost: Mapping[str, float] | None = None
    if service_tier:
        patch = get_model_mode(model_id, service_tier)
        candidate = patch.get("cost") if isinstance(patch, dict) else None
        if isinstance(candidate, Mapping):
            mode_cost = candidate

    rates = _tiered_rates(prices, usage.prompt_tokens, mode_cost)

    components: dict[str, float] = {}
    cached_tokens = usage.cached_tokens or 0
    cache_write_tokens = usage.cache_write_tokens or 0
    input_tokens = usage.prompt_tokens

    if rates["cache_read"] is not None and cached_tokens > 0:
        components["cache_read_usd"] = cached_tokens * rates["cache_read"] / 1_000_000
        input_tokens = max(input_tokens - cached_tokens, 0)
    if rates["cache_write"] is not None and cache_write_tokens > 0:
        components["cache_write_usd"] = (
            cache_write_tokens * rates["cache_write"] / 1_000_000
        )
        input_tokens = max(input_tokens - cache_write_tokens, 0)

    if rates["input"] is not None and input_tokens > 0:
        components["input_usd"] = input_tokens * rates["input"] / 1_000_000

    # Reasoning tokens are part of the completion unless the provider meters
    # them on their own line, in which case billing them at the output rate
    # too would double-count.
    output_tokens = usage.completion_tokens
    thoughts = usage.thoughts_tokens or 0
    if rates["reasoning"] is not None and thoughts > 0:
        components["reasoning_usd"] = thoughts * rates["reasoning"] / 1_000_000
        output_tokens = max(output_tokens - thoughts, 0)
    if rates["output"] is not None and output_tokens > 0:
        components["output_usd"] = output_tokens * rates["output"] / 1_000_000

    if not components:
        return None
    return {"estimated_usd": sum(components.values()), **components}
