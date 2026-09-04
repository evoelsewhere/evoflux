"""How a named effort becomes a wire payload, and who decides what.

EvoFlux exposes one knob (``thinking_level``) and every provider spells it
differently. The split these tests pin down is:

- The *catalog* says what a model accepts — which named efforts, whether it
  has an off switch, what token budget bounds it enforces. That comes from
  models.dev's ``reasoning_options`` and is why there is no longer a table
  of model-name substrings deciding "is this a Gemini 3" or "is this an
  adaptive Claude".
- The *dialect* says how to spell it. That is genuine wire knowledge no
  catalog publishes, so it stays in code.

The tests below feed synthetic catalog rows rather than asserting against
whatever models.dev happens to say today, so they keep testing the mapping
and not the catalog's current contents.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.providers import thinking as th
from app.agent.providers.model_metadata import ModelThinking, qualified_model_id
from app.agent.providers.model_registry import _thinking_from_model
from app.agent.providers.registry import THINKING_ORDER
from app.agent.providers.thinking import Dialect, thinking_budget


# ---------------------------------------------------------------------------
# reasoning_options -> EvoFlux's thinking contract
# ---------------------------------------------------------------------------


class TestReasoningOptionsExtraction:
    def test_effort_values_become_the_ladder(self) -> None:
        entry = _thinking_from_model(
            {"reasoning_options": [{"type": "effort", "values": ["low", "high"]}]}
        )
        assert entry == {
            "levels": ["low", "high"],
            "control": "effort",
            "source": "models_dev",
        }

    def test_a_toggle_alongside_efforts_adds_the_off_switch(self) -> None:
        """The list composes; reading only its first entry loses the switch."""
        entry = _thinking_from_model(
            {
                "reasoning_options": [
                    {"type": "toggle"},
                    {"type": "effort", "values": ["low", "high", "max"]},
                ]
            }
        )
        assert entry is not None
        assert entry["levels"] == ["none", "low", "high", "max"]
        assert entry["control"] == "effort"

    def test_a_bare_toggle_offers_only_the_off_switch(self) -> None:
        entry = _thinking_from_model({"reasoning_options": [{"type": "toggle"}]})
        assert entry is not None
        assert entry["levels"] == ["none"]
        assert entry["control"] == "toggle"

    def test_a_budget_is_sampled_at_named_points(self) -> None:
        """A continuous knob still has to be offered as named levels."""
        entry = _thinking_from_model(
            {"reasoning_options": [{"type": "budget_tokens", "min": 1024}]}
        )
        assert entry is not None
        assert entry["levels"] == ["low", "medium", "high"]
        assert entry["control"] == "budget"
        assert entry["budget"] == {"min": 1024}

    def test_a_zero_budget_floor_is_an_off_switch(self) -> None:
        """Gemini says "thinking off" by accepting a budget of zero."""
        entry = _thinking_from_model(
            {"reasoning_options": [{"type": "budget_tokens", "min": 0, "max": 24576}]}
        )
        assert entry is not None
        assert entry["levels"] == ["none", "low", "medium", "high"]
        assert entry["budget"] == {"min": 0, "max": 24576}

    def test_efforts_outrank_a_budget_for_the_control_name(self) -> None:
        """Both are published; the named efforts are the finer control."""
        entry = _thinking_from_model(
            {
                "reasoning_options": [
                    {"type": "effort", "values": ["low", "medium", "high"]},
                    {"type": "budget_tokens", "min": 1024},
                ]
            }
        )
        assert entry is not None
        assert entry["control"] == "effort"
        assert entry["levels"] == ["low", "medium", "high"]
        assert entry["budget"] == {"min": 1024}

    def test_an_empty_list_asserts_no_controls(self) -> None:
        assert _thinking_from_model({"reasoning_options": []}) == {
            "levels": [],
            "control": "none",
            "source": "models_dev",
        }

    @pytest.mark.parametrize("payload", [{}, {"reasoning_options": None}])
    def test_silence_leaves_curated_data_alone(self, payload: dict[str, Any]) -> None:
        """ "Unknown" and "none" are different answers and must stay so."""
        assert _thinking_from_model(payload) is None


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class TestThinkingBudget:
    def test_the_published_cap_wins_over_the_product_ceiling(self) -> None:
        assert thinking_budget("max", 65_536, maximum=24_576) == 24_576

    def test_the_product_ceiling_applies_when_no_cap_is_published(self) -> None:
        assert thinking_budget("high", 64_000) == 16_000

    def test_a_small_output_allowance_shrinks_the_budget(self) -> None:
        """A flat budget on a 4k-output model would leave nothing to answer with."""
        assert thinking_budget("high", 4_096) < 4_096

    def test_a_budget_never_reaches_the_output_limit(self) -> None:
        """Anthropic rejects ``budget_tokens >= max_tokens`` outright."""
        assert thinking_budget("max", 2_000) < 2_000

    def test_a_published_floor_is_respected(self) -> None:
        assert thinking_budget("minimal", 200_000, minimum=8_192) >= 8_192

    def test_a_zero_floor_still_yields_a_usable_budget(self) -> None:
        """Zero means "zero turns it off", not "an enabled budget may be zero"."""
        assert thinking_budget("minimal", 65_536, minimum=0) > 0


# ---------------------------------------------------------------------------
# Wire payloads
# ---------------------------------------------------------------------------


def _pin(
    monkeypatch: pytest.MonkeyPatch,
    *,
    control: str,
    levels: tuple[str, ...],
    budget_min: int | None = None,
    budget_max: int | None = None,
    max_output: int | None = 64_000,
    family: str = "",
) -> None:
    """Pin the catalog's answer so the test exercises the mapping, not the data."""
    thinking = ModelThinking(
        levels=levels,
        control=control,
        source="test",
        budget_min=budget_min,
        budget_max=budget_max,
    )
    monkeypatch.setattr(th, "_catalog_thinking", lambda *_: thinking)

    def contract(
        provider_id: str, model: str, *, dialect: Dialect, max_output: int | None
    ) -> th._ModelContract:
        return th._ModelContract(
            control=control,
            levels=tuple(name for name in levels if name != "none"),
            budget_min=budget_min,
            budget_max=budget_max,
            max_output=max_output if max_output is not None else 64_000,
            family=family,
        )

    monkeypatch.setattr(th, "_model_contract", contract)
    _ = max_output


class TestAnthropicDialect:
    def test_named_efforts_select_the_adaptive_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, control="effort", levels=("low", "medium", "high", "max"))
        assert th.thinking_request_fields("anthropic", "claude-x", "high") == {
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": "high"},
        }

    def test_a_budget_control_selects_the_token_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(
            monkeypatch,
            control="budget",
            levels=("low", "medium", "high"),
            budget_min=1024,
        )
        payload = th.thinking_request_fields("anthropic", "claude-y", "high")
        assert payload["thinking"]["type"] == "enabled"
        assert payload["thinking"]["budget_tokens"] == 16_000

    def test_an_unknown_model_falls_back_to_the_older_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adaptive is newer; an unrecognised endpoint is likelier to take a budget."""
        _pin(monkeypatch, control=None, levels=("low", "medium", "high"))
        payload = th.thinking_request_fields("anthropic", "claude-unknown", "high")
        assert payload["thinking"]["type"] == "enabled"


class TestGoogleDialect:
    def test_a_budget_control_sends_thinking_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(
            monkeypatch,
            control="budget",
            levels=("none", "low", "medium", "high"),
            budget_min=0,
            budget_max=24_576,
        )
        payload = th.thinking_request_fields("googlegenai", "gemini-x", "max")
        assert payload["thinkingConfig"]["thinkingBudget"] == 16_000
        assert payload["thinkingConfig"]["includeThoughts"] is True

    def test_an_effort_control_sends_thinking_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gemini 3 dropped the budget field; the catalog is what says so."""
        _pin(monkeypatch, control="effort", levels=("low", "medium", "high"))
        payload = th.thinking_request_fields("googlegenai", "gemini-y", "high")
        assert payload["thinkingConfig"]["thinkingLevel"] == "high"
        assert "thinkingBudget" not in payload["thinkingConfig"]

    def test_the_off_switch_matches_the_control(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, control="budget", levels=("none", "low"), budget_min=0)
        assert th.thinking_request_fields("googlegenai", "gemini-x", "none") == {
            "thinkingConfig": {"thinkingBudget": 0}
        }
        _pin(monkeypatch, control="effort", levels=("none", "low"))
        assert th.thinking_request_fields("googlegenai", "gemini-y", "none") == {
            "thinkingConfig": {"thinkingLevel": "minimal"}
        }

    def test_an_unknown_model_still_answers_can_disable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A live-listed Gemini the catalog has no row for must not crash.

        The silent-catalog path in ``can_disable`` handed the raw model ID to
        ``_disable_fields`` where a ``_ModelContract`` belongs; Google's off
        switch reads the contract, so listing provider models 500'd with
        ``AttributeError: 'str' object has no attribute 'is_effort_control'``.
        """
        _pin(monkeypatch, control=None, levels=())
        assert th.can_disable("googlegenai", "gemini-future-preview") is True
        levels = th.offered_levels_for("googlegenai:gemini-future-preview")
        assert levels and levels[0] == "none"


class TestBedrockDialect:
    def test_anthropic_models_with_efforts_go_adaptive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(
            monkeypatch,
            control="effort",
            levels=("low", "medium", "high", "max"),
            family="claude-opus",
        )
        assert th.thinking_request_fields("bedrock", "x.anthropic.claude-z", "max") == {
            "reasoningConfig": {
                "type": "adaptive",
                "maxReasoningEffort": "max",
                "display": "summarized",
            }
        }

    def test_anthropic_models_with_a_budget_send_budget_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(
            monkeypatch,
            control="budget",
            levels=("low", "medium", "high"),
            budget_min=1024,
            family="claude-sonnet",
        )
        payload = th.thinking_request_fields("bedrock", "x.anthropic.claude-w", "high")
        assert payload["reasoningConfig"]["budgetTokens"] == 16_000

    def test_nova_models_take_a_named_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(
            monkeypatch,
            control="effort",
            levels=("none", "low", "medium", "high"),
            family="nova-lite",
        )
        assert th.thinking_request_fields("bedrock", "amazon.nova-2-lite", "high") == {
            "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "high"}
        }


class TestToggleOnlyModels:
    def test_an_active_level_still_switches_thinking_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model with only a switch must not silently ignore "think harder".

        The catalog is right that MiMo and GLM name no efforts. Refusing the
        request on that basis would leave the switch permanently off for
        anyone who picks a level instead of the bare default.
        """
        _pin(monkeypatch, control="toggle", levels=("none",))
        assert th.thinking_request_fields("zai", "glm-x", "high") == {
            "thinking": {"type": "enabled", "clear_thinking": False}
        }

    def test_no_effort_field_is_sent_for_a_model_that_names_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, control="toggle", levels=("none",))
        payload = th.thinking_request_fields("qwencloud", "qwen-x", "high")
        assert payload == {"enable_thinking": True}

    def test_an_effort_field_is_sent_when_the_model_names_efforts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, control="effort", levels=("none", "low", "high"))
        payload = th.thinking_request_fields("qwencloud", "qwen-y", "high")
        assert payload == {"enable_thinking": True, "reasoning_effort": "high"}


class TestNoControl:
    def test_a_model_the_catalog_says_has_no_control_sends_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, control="none", levels=())
        assert th.thinking_request_fields("openai", "gpt-x", "high") == {}

    def test_a_dialect_with_no_control_sends_nothing(self) -> None:
        assert th.thinking_request_fields("perplexity", "sonar", "high") == {}

    def test_no_request_sends_nothing(self) -> None:
        assert th.thinking_request_fields("openai", "gpt-5", None) == {}
        assert th.thinking_request_fields("openai", "gpt-5", "") == {}


# ---------------------------------------------------------------------------
# Model-ID qualification
# ---------------------------------------------------------------------------


class TestQualifiedModelId:
    def test_a_bare_model_gains_its_provider(self) -> None:
        assert qualified_model_id("openai", "gpt-5") == "openai:gpt-5"

    def test_an_already_qualified_id_is_left_alone(self) -> None:
        assert qualified_model_id("openai", "openai:gpt-5") == "openai:gpt-5"

    def test_a_model_id_containing_a_colon_is_still_qualified(self) -> None:
        """Every Bedrock model ID carries a version suffix after a colon.

        Treating any colon as "already qualified" parsed
        ``us.anthropic.claude-…-v1:0`` as provider ``us.anthropic.claude-…-v1``
        and model ``0``, so every Bedrock model missed the catalog entirely
        and fell back to generic defaults.
        """
        assert (
            qualified_model_id("bedrock", "us.anthropic.claude-sonnet-4-5-v1:0")
            == "bedrock:us.anthropic.claude-sonnet-4-5-v1:0"
        )


class TestEnumVocabularies:
    """No dialect may put an out-of-vocabulary name in an enum field.

    A budget field is a number: every level maps to one and the endpoint
    honours or clamps it. An *enum* rejects the whole request when it sees a
    name it does not know — which is how MiMo returned HTTP 400 for ``max``,
    losing the budget along with it.
    """

    #: Enum fields and what each accepts, by dotted path in the payload.
    ENUMS = {
        "reasoning_effort": {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        },
        "reasoning.effort": {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        },
        "output_config.effort": {"low", "medium", "high", "xhigh", "max"},
        "thinkingConfig.thinkingLevel": {"minimal", "low", "medium", "high"},
        "reasoningConfig.maxReasoningEffort": {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        },
    }

    NUMERIC = {
        "thinking.budget_tokens",
        "thinkingConfig.thinkingBudget",
        "reasoningConfig.budgetTokens",
    }

    @staticmethod
    def _flatten(payload: dict, prefix: str = "") -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in payload.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                out.update(TestEnumVocabularies._flatten(value, f"{path}."))
            else:
                out[path] = value
        return out

    def test_no_provider_emits_an_unknown_enum_value(self) -> None:
        """Sweeps every curated provider, model and level in the catalog.

        Two real bugs were found this way: Bedrock's fallback offered the
        whole vocabulary into an enum that stops at ``high``, and
        Claude-on-Vertex was handed Gemini's ``thinkingConfig`` because the
        per-model protocol override went unread.
        """
        from app.agent.providers.model_registry import load_model_registry
        from app.agent.providers.registry import PROVIDER_REGISTRY

        registry = load_model_registry()
        violations: list[str] = []
        for provider_id in sorted(PROVIDER_REGISTRY):
            prefix = f"{provider_id}:"
            models = sorted(
                key[len(prefix) :] for key in registry if key.startswith(prefix)
            )[:6] or ["model-absent-from-catalog"]
            for model in models:
                for level in ("none", *THINKING_ORDER):
                    payload = th.thinking_request_fields(provider_id, model, level)
                    for path, value in self._flatten(payload).items():
                        if path in self.ENUMS and value not in self.ENUMS[path]:
                            violations.append(
                                f"{provider_id}:{model} asked={level} {path}={value!r}"
                            )
                        elif path in self.NUMERIC and not isinstance(value, int):
                            violations.append(
                                f"{provider_id}:{model} asked={level} "
                                f"{path}={value!r} is not an int"
                            )
        assert violations == []

    def test_a_per_model_protocol_override_selects_the_dialect(self) -> None:
        """Claude on Vertex is Anthropic Messages, not Gemini.

        models.dev flags it with ``npm`` on the model. Reading the provider's
        default instead sent the wrong *field*, not merely a wrong value.
        """
        assert (
            th.dialect_for("vertexai", "claude-opus-4-6@default")
            is Dialect.ANTHROPIC_THINKING
        )
        assert (
            th.dialect_for("vertexai", "gemini-2.5-pro")
            is Dialect.GOOGLE_THINKING_CONFIG
        )
