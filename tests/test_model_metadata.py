from __future__ import annotations

from app.agent.providers.model_metadata import (
    get_model_cost,
    get_model_features,
    get_model_limits,
    get_model_metadata,
    get_model_thinking_levels,
)


def test_get_model_limits_returns_known_limits() -> None:
    limits = get_model_limits("openai:gpt-5")

    assert limits.context_length == 400000
    assert limits.max_completion_tokens == 128000


def test_get_model_limits_returns_codex_registry_limits() -> None:
    limits = get_model_limits("codex:gpt-5.2-codex")

    assert limits.context_length == 400000
    assert limits.max_completion_tokens == 128000


def test_get_model_metadata_is_case_insensitive() -> None:
    metadata = get_model_metadata("OPENAI:GPT-5")

    assert metadata.limits.context_length == 400000


def test_get_model_limits_unknown_model_returns_none_limits() -> None:
    limits = get_model_limits("unknown:model")

    assert limits.context_length is None
    assert limits.max_completion_tokens is None


def test_get_model_cost_unknown_model_returns_none_cost() -> None:
    cost = get_model_cost("unknown:model")

    assert cost.input is None
    assert cost.output is None


def test_get_model_features_unknown_model_returns_none_features() -> None:
    features = get_model_features("unknown:model")

    assert features.tool_call is None
    assert features.status is None


def test_get_model_thinking_levels_returns_known_levels() -> None:
    assert get_model_thinking_levels("openai:gpt-5") == (
        "minimal",
        "low",
        "medium",
        "high",
    )


def test_get_model_thinking_levels_unknown_model_returns_empty_tuple() -> None:
    assert get_model_thinking_levels("unknown:model") == ()


def test_get_model_thinking_levels_covers_native_anthropic_reasoning_models() -> None:
    """Regression test: the direct `anthropic:` provider models were missing
    `thinking.levels` in the registry even though anthropic.py has always
    known how to apply a thinking level to them — only the AWS Bedrock
    listing of the same models (e.g. bedrock:anthropic.claude-opus-4-7) had
    the data, so the frontend's ThinkingPill silently never appeared for
    the native Anthropic provider."""
    # Newer models route through anthropic.py's adaptive thinking mode
    # (output_config.effort) and additionally support "minimal".
    assert get_model_thinking_levels("anthropic:claude-opus-4-7") == (
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    # Older reasoning-capable models use the budget_tokens mode instead.
    assert get_model_thinking_levels("anthropic:claude-opus-4-5") == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    # Pre-extended-thinking models must still report no levels at all.
    assert get_model_thinking_levels("anthropic:claude-3-5-haiku-latest") == ()
