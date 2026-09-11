"""Tests for build_summarization_hook() in app/agent/hooks/summarization.py.

The factory has no per-agent or file overrides — it just instantiates a
SummarizationHook from the module-level ``DEFAULT_*`` constants. The only
runtime input is ``mode``, which selects the summariser prompt.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent.hooks.summarization import (
    CHAT_SUMMARY_PROMPT,
    CODING_KEEP_LAST_ASSISTANTS,
    CODING_SUMMARY_PROMPT,
    DEFAULT_KEEP_LAST_ASSISTANTS,
    DEFAULT_MAX_TOKEN_LENGTH,
    MAX_PROMPT_TOKEN_THRESHOLD,
    PROMPT_TOKEN_THRESHOLD_CONTEXT_RATIO,
    SummarizationHook,
    build_summarization_hook,
    cost_optimal_prompt_token_threshold,
    prompt_token_threshold_for_model,
)
from app.core.runtime_settings import ContextSettings, RuntimeSettings


@pytest.fixture(autouse=True)
def _no_operator_override(monkeypatch):
    """Pin the global override off so a developer's settings.yaml cannot
    change what these tests measure."""
    import app.core.runtime_settings as rs

    monkeypatch.setattr(rs, "load_runtime_settings", lambda *a, **k: RuntimeSettings())


def _override(monkeypatch, tokens):
    import app.core.runtime_settings as rs

    monkeypatch.setattr(
        rs,
        "load_runtime_settings",
        lambda *a, **k: RuntimeSettings(
            context=ContextSettings(summary_trigger_tokens=tokens)
        ),
    )


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.stream = MagicMock()
    return provider


def test_builds_hook_with_module_defaults(mock_provider):
    """No mode → CHAT prompt + module-level numeric defaults."""
    result = build_summarization_hook(mock_provider)
    assert isinstance(result, SummarizationHook)
    assert result._prompt_token_threshold == cost_optimal_prompt_token_threshold()
    assert result._keep_last_assistants == DEFAULT_KEEP_LAST_ASSISTANTS
    assert result._max_token_length == DEFAULT_MAX_TOKEN_LENGTH
    assert result._summary_prompt == CHAT_SUMMARY_PROMPT
    # default_provider is reused — no separate summariser model resolution.
    assert result._llm_provider is mock_provider


def test_mode_coding_picks_coding_prompt_and_small_keep(mock_provider):
    """mode="coding" uses the structured Markdown template plus a small
    verbatim window so the latest diffs/errors survive compaction exactly."""
    result = build_summarization_hook(mock_provider, mode="coding")
    assert result is not None
    assert result._summary_prompt == CODING_SUMMARY_PROMPT
    assert result._keep_last_assistants == CODING_KEEP_LAST_ASSISTANTS == 2


def test_mode_normal_picks_chat_prompt_and_default_keep(mock_provider):
    """Any non-coding mode picks the prose chat prompt + the chat keep window."""
    result = build_summarization_hook(mock_provider, mode="work")
    assert result is not None
    assert result._summary_prompt == CHAT_SUMMARY_PROMPT
    assert result._keep_last_assistants == DEFAULT_KEEP_LAST_ASSISTANTS


def test_mode_none_picks_chat_prompt_and_default_keep(mock_provider):
    """mode=None (omitted) defaults to the prose chat prompt + chat keep window."""
    result = build_summarization_hook(mock_provider)
    assert result is not None
    assert result._summary_prompt == CHAT_SUMMARY_PROMPT
    assert result._keep_last_assistants == DEFAULT_KEEP_LAST_ASSISTANTS


def test_large_context_model_gets_cost_optimal_not_the_ceiling():
    """A big window no longer buys a big threshold.

    Carrying context costs the same per token whatever the window is, so the
    cost model — not ``MAX_PROMPT_TOKEN_THRESHOLD`` — sets the value here.
    """
    threshold = prompt_token_threshold_for_model("openai:gpt-4.1")
    assert threshold == cost_optimal_prompt_token_threshold()
    assert threshold < MAX_PROMPT_TOKEN_THRESHOLD


def test_prompt_token_threshold_for_model_uses_75_percent_context():
    assert prompt_token_threshold_for_model(
        "bedrock:mistral.voxtral-small-24b-2507"
    ) == int(32000 * PROMPT_TOKEN_THRESHOLD_CONTEXT_RATIO)


def test_prompt_token_threshold_for_model_unknown_uses_cost_optimal():
    assert (
        prompt_token_threshold_for_model("unknown:model")
        == cost_optimal_prompt_token_threshold()
    )


def test_operator_override_replaces_the_cost_optimal_default(monkeypatch):
    _override(monkeypatch, 120_000)
    assert prompt_token_threshold_for_model("openai:gpt-4.1") == 120_000


def test_operator_override_still_clamped_by_the_model_window(monkeypatch):
    """A 600K override on a 32K model must not disable compaction."""
    _override(monkeypatch, 600_000)
    assert prompt_token_threshold_for_model(
        "bedrock:mistral.voxtral-small-24b-2507"
    ) == int(32000 * PROMPT_TOKEN_THRESHOLD_CONTEXT_RATIO)


def test_cost_optimal_threshold_sits_between_the_floor_and_the_ceiling():
    value = cost_optimal_prompt_token_threshold()
    assert 60_000 < value < MAX_PROMPT_TOKEN_THRESHOLD


def test_builds_hook_with_model_threshold(mock_provider):
    result = build_summarization_hook(
        mock_provider,
        model_id="bedrock:mistral.voxtral-small-24b-2507",
    )

    assert result is not None
    assert result._prompt_token_threshold == 24000


def test_zero_threshold_returns_none(mock_provider, monkeypatch):
    """The module-level threshold acts as the only kill switch."""
    import app.agent.hooks.summarization as mod

    monkeypatch.setattr(mod, "DEFAULT_PROMPT_TOKEN_THRESHOLD", 0)
    assert build_summarization_hook(mock_provider) is None
