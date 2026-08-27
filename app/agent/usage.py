from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.providers.model_metadata import get_model_cost
from app.agent.schemas.chat import Usage


_NON_TOKEN_BILLED_PROVIDERS = frozenset({"codex", "copilot", "kimi", "ollama"})


def usage_to_dict(usage: Usage, model_id: str | None) -> dict[str, Any]:
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

    cost = _estimate_cost(usage, model_id)
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
    estimated_cost = cost.get("estimated_usd") if isinstance(cost, dict) else None
    if isinstance(estimated_cost, int | float) and estimated_cost > 0:
        span.set_attribute("gen_ai.usage.estimated_cost_usd", estimated_cost)


def _estimate_cost(usage: Usage, model_id: str | None) -> dict[str, float] | None:
    provider_id = model_id.partition(":")[0].lower() if model_id else ""
    if provider_id in _NON_TOKEN_BILLED_PROVIDERS:
        return None
    prices = get_model_cost(model_id)
    components: dict[str, float] = {}
    cached_tokens = usage.cached_tokens or 0
    cache_write_tokens = usage.cache_write_tokens or 0
    input_tokens = usage.prompt_tokens

    if prices.cache_read is not None and cached_tokens > 0:
        components["cache_read_usd"] = cached_tokens * prices.cache_read / 1_000_000
        input_tokens = max(input_tokens - cached_tokens, 0)
    if prices.cache_write is not None and cache_write_tokens > 0:
        components["cache_write_usd"] = (
            cache_write_tokens * prices.cache_write / 1_000_000
        )
        input_tokens = max(input_tokens - cache_write_tokens, 0)

    if prices.input is not None and input_tokens > 0:
        components["input_usd"] = input_tokens * prices.input / 1_000_000
    if prices.output is not None and usage.completion_tokens > 0:
        components["output_usd"] = usage.completion_tokens * prices.output / 1_000_000

    if not components:
        return None
    return {"estimated_usd": sum(components.values()), **components}
