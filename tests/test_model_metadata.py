from __future__ import annotations

from app.agent.providers.model_metadata import (
    get_model_cost,
    get_model_features,
    get_model_limits,
    get_model_metadata,
    get_model_thinking_levels,
)
from app.agent.providers.model_registry import _thinking_from_model


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
    the native Anthropic provider.

    Levels now flow from models.dev's live `reasoning_options` (effort
    values pass through verbatim), with curated entries as fallback for
    models models.dev does not catalogue."""
    # Newer models route through anthropic.py's adaptive thinking mode
    # (output_config.effort); models.dev lists these exact effort values.
    assert get_model_thinking_levels("anthropic:claude-opus-4-7") == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    # models.dev lists effort low..high (plus budget_tokens) for opus-4-5.
    assert get_model_thinking_levels("anthropic:claude-opus-4-5") == (
        "low",
        "medium",
        "high",
    )
    # Pre-extended-thinking models must still report no levels at all.
    assert get_model_thinking_levels("anthropic:claude-3-5-haiku-latest") == ()


# ── _thinking_from_model (models.dev reasoning_options → thinking.levels) ─────


def test_thinking_from_model_maps_effort_values_verbatim() -> None:
    model = {
        "reasoning_options": [
            {"type": "effort", "values": ["low", "medium", "high", "high"]}
        ]
    }

    assert _thinking_from_model(model) == {"levels": ["low", "medium", "high"]}


def test_thinking_from_model_maps_toggle_to_none_only() -> None:
    model = {"reasoning_options": [{"type": "toggle"}]}

    assert _thinking_from_model(model) == {"levels": ["none"]}


def test_thinking_from_model_prefers_effort_over_other_options() -> None:
    model = {
        "reasoning_options": [
            {"type": "toggle"},
            {"type": "effort", "values": ["low", "high"]},
            {"type": "budget_tokens", "min": 1024},
        ]
    }

    assert _thinking_from_model(model) == {"levels": ["low", "high"]}


def test_thinking_from_model_skips_budget_tokens_only() -> None:
    """budget-only models stay on curated data: level→budget translation is
    provider-specific (only the anthropic handler implements it)."""
    model = {"reasoning_options": [{"type": "budget_tokens", "min": 1024}]}

    assert _thinking_from_model(model) is None


def test_thinking_from_model_empty_list_is_authoritative_none() -> None:
    """An explicit ``[]`` asserts "no reasoning controls" and must override
    stale curated levels on merge."""
    assert _thinking_from_model({"reasoning_options": []}) == {"levels": []}


def test_thinking_from_model_missing_or_null_preserves_curated() -> None:
    assert _thinking_from_model({}) is None
    assert _thinking_from_model({"reasoning_options": None}) is None


def test_thinking_from_model_tolerates_malformed_options() -> None:
    assert _thinking_from_model({"reasoning_options": "effort"}) is None
    assert _thinking_from_model({"reasoning_options": [{"type": "effort"}]}) is None
    assert (
        _thinking_from_model(
            {"reasoning_options": [{"type": "effort", "values": ["low", 5]}]}
        )
        is None
    )
    assert _thinking_from_model({"reasoning_options": [None, {"type": "toggle"}]}) == {
        "levels": ["none"]
    }
