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


class TestWhatThePickerOffers:
    """Which levels reach a user, as opposed to which a request may carry.

    Unlike the rest of this file these run against the real catalog, because
    what is pinned down *is* the reading of catalog data.

    The reference point is MiMo-Code's ``variants()``: it opens with
    ``if (!model.capabilities.reasoning) return {}``, returns ``{}`` for
    minimax/glm/kimi/qwen/mistral, and gives everything on
    ``@ai-sdk/openai-compatible`` — MiMo included — ``low``/``medium``/``high``.
    """

    def test_mimo_offers_what_its_own_client_offers(self) -> None:
        """models.dev calls MiMo a bare toggle; the budget dialect invented six.

        Budget dialects fell back to the whole vocabulary where every enum
        dialect falls back to three. EvoFlux's own Xiaomi handler already
        documents that the effort enum "stops at high".
        """
        assert th.offered_levels_for("xiaomi:mimo-v2.5") == (
            "none",
            "low",
            "medium",
            "high",
        )

    def test_a_model_that_does_not_reason_offers_nothing(self) -> None:
        """A text-to-speech model was being offered seven thinking levels.

        Its row carries no ``reasoning_options``, which reads as "unknown"
        rather than "none" — but it does carry ``reasoning: false``, which
        nothing consulted.
        """
        assert th.offered_levels_for("xiaomi:mimo-v2.5-tts") == ()
        assert th.offered_levels_for("opencode:claude-3-5-haiku") == ()

    def test_a_family_that_ignores_the_effort_offers_only_the_switch(self) -> None:
        """MiMo-Code returns no ladder for these ids whatever the transport.

        GLM on ``zai`` already behaved this way because its dialect is not
        level-sensitive; the same model through another OpenAI-compatible
        endpoint got three rungs, and minimax got six.
        """
        assert th.offered_levels_for("minimax:minimax-m3") == ("none",)
        assert th.offered_levels_for("302ai:glm-4.5") == ("none",)

    def test_the_catalog_still_outranks_the_family_list(self) -> None:
        """MiMo-Code's list is absolute; here it only speaks where data does not."""
        assert th.offered_levels_for("zai:glm-5.2") == ("none", "high", "max")

    def test_a_catalog_named_ladder_is_left_alone(self) -> None:
        assert th.offered_levels_for("anthropic:claude-opus-4-6") == (
            "none",
            "low",
            "medium",
            "high",
            "max",
        )
        assert th.offered_levels_for("openai:gpt-5.2") == (
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
        )

    def test_validation_still_accepts_a_level_the_picker_hides(self) -> None:
        """Narrowing the offer must not narrow what a request may carry."""
        honoured = th.honoured_levels_for("xiaomi:mimo-v2.5")
        assert set(th.offered_levels_for("xiaomi:mimo-v2.5")) <= set(honoured)
        assert "max" in honoured
        assert th.thinking_request_fields("xiaomi", "mimo-v2.5", "max") == {
            "thinking": {"type": "enabled", "budget_tokens": 31_999}
        }

    def test_a_google_model_newer_than_the_catalog_does_not_raise(self) -> None:
        """`can_disable` passed a model string where a contract was expected.

        Only the Google branch reads the contract, so it stayed hidden until
        a Gemini row newer than the bundled snapshot reached it — and the
        discovery filter passes those straight through to the picker.
        """
        assert th.offered_levels_for("googlegenai:gemini-4-pro") == (
            "none",
            "low",
            "medium",
            "high",
        )
        assert th.resolve_level("vertexai", "gemini-4-flash", "none") == "none"

    def test_a_provider_that_sends_no_thinking_field_offers_nothing(self) -> None:
        """FPT's gateway takes no reasoning parameter on either surface.

        Its API reference documents none, its ``/v1/models`` lists
        ``supported_parameters`` without a reasoning key, and both FCI
        handlers send nothing. Four picker entries, one request.
        """
        assert th.offered_levels_for("fci:DeepSeek-V4-Flash") == ()
        assert th.offered_levels_for("fci:Qwen3.6-27B") == ()
        # The dialect still has an opinion; the FCI handler is what drops it.
        assert th.thinking_request_fields("fci", "Qwen3.6-27B", "high") == {
            "reasoning_effort": "high"
        }

    def test_a_level_already_saved_against_that_provider_still_validates(
        self,
    ) -> None:
        """Silencing the offer must not start rejecting sessions that have one.

        Hence :func:`offered_levels` rather than ``_ADAPTER_CANNOT_STEER``,
        which would make the same request a 422.
        """
        assert th.accepts_thinking_level("fci:Qwen3.6-27B", "high") is True

    def test_no_catalog_row_raises(self) -> None:
        """The sweep that would have caught the above on the day it landed."""
        from app.agent.providers.model_registry import load_model_registry

        failures: list[str] = []
        for model_id in load_model_registry():
            if ":" not in model_id:
                continue
            try:
                th.offered_levels_for(model_id)
            except Exception as exc:  # noqa: BLE001 - the point is the sweep
                failures.append(f"{model_id}: {type(exc).__name__}: {exc}")
        assert failures[:5] == []

    def test_nothing_offered_is_ever_unhonoured(self) -> None:
        """The invariant the two functions exist to keep."""
        from app.agent.providers.model_registry import load_model_registry

        violations: list[str] = []
        for model_id in load_model_registry():
            if ":" not in model_id:
                continue
            offered = set(th.offered_levels_for(model_id))
            if not offered <= set(th.honoured_levels_for(model_id)):
                violations.append(model_id)
        assert violations[:5] == []


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
