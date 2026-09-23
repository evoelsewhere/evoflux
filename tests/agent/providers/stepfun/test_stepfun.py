"""Tests for the StepFun provider.

Covers:
- StepFunProvider.__init__: inherits ChatCompletionsOnlyProvider
- the factory branch reads STEPFUN_API_KEY and the catalogue base URL
- ``reasoning_format`` is always on the wire, so the trace arrives as
  ``reasoning_content`` rather than StepFun's default ``reasoning``
- ``max_tokens`` rather than ``max_completion_tokens``
- thinking_level -> ``reasoning_effort``, clamped to the levels the
  catalogue names and dropped when it would be a value StepFun never
  published (``none``)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.stepfun import StepFunProvider
from app.agent.providers.stepfun.stepfun import _StepFunCompletionsHandler
from app.agent.schemas.chat import HumanMessage

STEPFUN_API_BASE = "https://api.stepfun.ai/v1"


def _build_body(
    model: str = "step-3.7-flash",
    model_kwargs: dict | None = None,
    **call_kwargs: object,
) -> dict:
    """Build one request body the way the provider would send it."""
    provider = StepFunProvider(
        api_key="stepfun-test-key",
        model=model,
        base_url=STEPFUN_API_BASE,
        model_kwargs=model_kwargs,
    )
    return provider._completions.build_request(
        [HumanMessage(content="hi")],
        None,
        stream=False,
        merged=provider._merged_kwargs(**call_kwargs),
    )


# ============================================================================
# Class hierarchy
# ============================================================================


class TestStepFunProviderInheritance:
    """StepFun speaks Chat Completions only — never OpenAI's /responses."""

    def test_provider_is_a_chat_completions_only_provider(self) -> None:
        assert issubclass(StepFunProvider, ChatCompletionsOnlyProvider)

    def test_provider_uses_the_stepfun_handler(self) -> None:
        with patch("app.agent.providers.openai.openai.ResponsesHandler"):
            provider = StepFunProvider(
                api_key="stepfun-test-key",
                model="step-3.7-flash",
                base_url=STEPFUN_API_BASE,
            )
        assert isinstance(provider._completions, _StepFunCompletionsHandler)

    def test_thinking_level_stays_on_chat_completions(self) -> None:
        with patch("app.agent.providers.openai.openai.ResponsesHandler"):
            provider = StepFunProvider(
                api_key="stepfun-test-key",
                model="step-3.7-flash",
                base_url=STEPFUN_API_BASE,
                model_kwargs={"thinking_level": "high"},
            )
        assert provider._use_responses is False


# ============================================================================
# Reasoning trace spelling
# ============================================================================


class TestReasoningFormat:
    """StepFun returns ``reasoning`` unless asked for the other spelling.

    ``OpenAIStreamDelta`` parses ``reasoning_content`` and ignores unknown
    fields, so without this the whole trace is dropped in silence.
    """

    def test_every_request_asks_for_reasoning_content(self) -> None:
        assert _build_body()["reasoning_format"] == "deepseek-style"

    def test_a_request_without_thinking_still_asks_for_it(self) -> None:
        # The format is about where the trace lands, not whether one is
        # requested: StepFun reasons by default.
        body = _build_body(model_kwargs={"thinking_level": "none"})
        assert body["reasoning_format"] == "deepseek-style"

    def test_an_explicit_format_is_honoured(self) -> None:
        body = _build_body(model_kwargs={"reasoning_format": "general"})
        assert body["reasoning_format"] == "general"


# ============================================================================
# Output cap
# ============================================================================


class TestMaxTokensField:
    """StepFun documents ``max_tokens`` and no ``max_completion_tokens``."""

    def test_the_legacy_field_carries_the_cap(self) -> None:
        body = _build_body(model_kwargs={"max_tokens": 512})
        assert body["max_tokens"] == 512
        assert "max_completion_tokens" not in body


# ============================================================================
# thinking_level -> reasoning_effort
# ============================================================================


class TestStepFunThinking:
    """StepFun takes OpenAI's ``reasoning_effort``, with no off switch.

    The levels come from the model catalogue: ``step-3.7-flash`` publishes
    low/medium/high, ``step-3.5-flash`` only low/high. A stronger request is
    clamped down rather than sent.
    """

    @pytest.mark.parametrize(
        ("level", "expected"),
        [("low", "low"), ("medium", "medium"), ("high", "high")],
    )
    def test_named_levels_reach_the_wire(self, level: str, expected: str) -> None:
        body = _build_body(model_kwargs={"thinking_level": level})
        assert body["reasoning_effort"] == expected

    def test_a_level_above_the_enum_is_clamped(self) -> None:
        body = _build_body(model_kwargs={"thinking_level": "max"})
        assert body["reasoning_effort"] == "high"

    def test_a_level_the_model_skips_is_clamped_down(self) -> None:
        # step-3.5-flash publishes low and high, nothing between them.
        body = _build_body(
            model="step-3.5-flash", model_kwargs={"thinking_level": "medium"}
        )
        assert body["reasoning_effort"] == "low"

    @pytest.mark.parametrize("level", ["none", "off"])
    def test_disabling_sends_no_effort_at_all(self, level: str) -> None:
        """StepFun publishes no ``none`` effort, so nothing is sent.

        The shared dialect emits ``reasoning_effort: "none"`` as the
        OpenAI-shaped off switch. StepFun documents low/medium/high only and,
        probed live, answers ``none`` with a 200 and reasons anyway — so the
        request is not improved by carrying a value StepFun never published,
        and thinking stays on at its own default either way.
        """
        body = _build_body(model_kwargs={"thinking_level": level})
        assert "reasoning_effort" not in body

    def test_no_level_sends_no_effort(self) -> None:
        assert "reasoning_effort" not in _build_body()


# ============================================================================
# Pricing identity
# ============================================================================


class TestStepFunPricing:
    """One price per model, whichever of StepFun's four rows serves it.

    A plan user configures this provider with a plan base URL, so their
    turns resolve under ``stepfun:`` and are priced from the open-platform
    row. Selecting a ``step_plan`` row directly now prices the same — see
    the Step Plan note in ``documents/features/models-and-providers.md``.
    """

    def test_open_platform_models_are_priced(self) -> None:
        from app.agent.usage import estimate_cost

        cost = estimate_cost(
            "stepfun:step-3.7-flash", input_tokens=10_000, output_tokens=500
        )
        assert cost is not None
        assert cost["estimated_usd"] > 0

    def test_a_cache_hit_is_billed_at_the_cache_rate(self) -> None:
        """StepFun's ``prompt_tokens`` includes its cached tokens.

        Verified live: a repeated prefix came back as
        ``prompt_tokens: 4431`` with ``prompt_tokens_details.cached_tokens:
        4224``, so the cached share has to be taken out of the input line
        rather than added to it.
        """
        from app.agent.usage import estimate_cost

        cold = estimate_cost(
            "stepfun:step-3.7-flash", input_tokens=4431, output_tokens=72
        )
        warm = estimate_cost(
            "stepfun:step-3.7-flash",
            input_tokens=4431,
            output_tokens=72,
            cached_tokens=4224,
        )
        assert cold is not None and warm is not None
        assert warm["cache_read_usd"] > 0
        assert warm["input_usd"] < cold["input_usd"]
        assert warm["estimated_usd"] < cold["estimated_usd"]

    def test_a_plan_row_costs_what_the_open_platform_charges(self) -> None:
        """The endpoint must not decide whether a turn has a price.

        models.dev publishes no rates for the ``step_plan`` rows, because a
        plan bills a subscription rather than a token. Read literally that
        leaves identical tokens against identical weights priced on one row
        and blank on the other, so a plan row inherits the open platform's
        rates — which is the number EvoFlux already promises for every
        subscription provider.
        """
        from app.agent.usage import estimate_cost

        payg = estimate_cost(
            "stepfun:step-3.7-flash", input_tokens=10_000, output_tokens=500
        )
        for plan in ("stepfun-ai-step-plan", "stepfun-step-plan"):
            priced = estimate_cost(
                f"{plan}:step-3.7-flash", input_tokens=10_000, output_tokens=500
            )
            assert priced == payg

    def test_a_model_only_a_plan_row_lists_stays_unpriced(self) -> None:
        """No open-platform row prices ``step-router-v1``, so nothing does.

        Borrowing a sibling model's rates would state a price as fact. The
        model still resolves — it reaches the curated provider with its
        limits — it just reports no cost.
        """
        from app.agent.providers.model_metadata import get_model_limits
        from app.agent.usage import estimate_cost

        assert (
            estimate_cost(
                "stepfun:step-router-v1", input_tokens=10_000, output_tokens=500
            )
            is None
        )
        assert get_model_limits("stepfun:step-router-v1").context_length == 256000


# ============================================================================
# Registry wiring
# ============================================================================


class TestStepFunRegistryEntry:
    """The curated row points at the global open platform."""

    def test_endpoint_comes_from_the_catalogue(self) -> None:
        from app.agent.providers.registry import resolve_base_url, resolve_provider

        config = resolve_provider("stepfun")
        assert config is not None
        assert resolve_base_url(config) == STEPFUN_API_BASE

    def test_metadata_is_read_under_the_global_catalogue_row(self) -> None:
        from app.agent.providers.registry import resolve_provider

        config = resolve_provider("stepfun")
        assert config is not None
        assert config.models_dev_provider_id == "stepfun-ai"

    def test_the_base_url_override_is_declared(self) -> None:
        from app.agent.providers.registry import resolve_provider

        config = resolve_provider("stepfun")
        assert config is not None
        assert config.env_var == "STEPFUN_API_KEY"
        assert config.base_url_env_var == "STEPFUN_BASE_URL"

    def test_the_settings_row_is_an_api_key_form(self) -> None:
        from app.agent.providers.catalog import find

        row = find("stepfun")
        assert row is not None
        assert row["kind"] == "api_key"
        assert row["env_var"] == "STEPFUN_API_KEY"
        assert row["description"]


# ============================================================================
# Provider factory — stepfun branch
# ============================================================================


class TestStepFunProviderFactory:
    """build_provider resolves ``stepfun:`` models to StepFunProvider."""

    def test_factory_passes_the_key_and_catalogue_base_url(self) -> None:
        from app.agent.providers.factory import build_provider

        with patch(
            "app.agent.providers.factory.StepFunProvider",
            return_value=MagicMock(),
        ) as MockStepFun:
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.STEPFUN_API_KEY = MagicMock()
                mock_settings.STEPFUN_API_KEY.get_secret_value.return_value = (
                    "stepfun-secret"
                )
                mock_settings.STEPFUN_BASE_URL = ""
                build_provider("stepfun:step-3.7-flash")

        call_kwargs = MockStepFun.call_args.kwargs
        assert call_kwargs.get("api_key") == "stepfun-secret"
        assert call_kwargs.get("model") == "step-3.7-flash"
        assert call_kwargs.get("base_url") == STEPFUN_API_BASE

    def test_factory_respects_a_custom_base_url(self, monkeypatch) -> None:
        """A Step Plan or China key is a base-URL change, not a new provider."""
        from app.agent.providers.factory import build_provider

        monkeypatch.setenv("STEPFUN_BASE_URL", "https://api.stepfun.com/step_plan/v1")
        with patch(
            "app.agent.providers.factory.StepFunProvider",
            return_value=MagicMock(),
        ) as MockStepFun:
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.STEPFUN_API_KEY = MagicMock()
                mock_settings.STEPFUN_API_KEY.get_secret_value.return_value = "key"
                build_provider("stepfun:step-5-preview")

        assert (
            MockStepFun.call_args.kwargs.get("base_url")
            == "https://api.stepfun.com/step_plan/v1"
        )

    def test_factory_raises_when_the_key_is_missing(self, monkeypatch) -> None:
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.STEPFUN_API_KEY = None
            with pytest.raises(ValueError, match="STEPFUN_API_KEY"):
                build_provider("stepfun:step-3.7-flash")
