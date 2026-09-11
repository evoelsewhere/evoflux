"""Alternate service tiers — the same model, served differently.

A tier is selected by a small body patch, sometimes a header too, and bills
at its own rate. Those patches are the provider's own wire contract, so they
are carried verbatim from the catalog: nothing in EvoFlux knows what
``speed`` or ``service_tier`` mean, only where to put them. That is what
lets a tier work as soon as the catalog lists it.

The tests below feed synthetic catalog rows rather than asserting against
whatever models.dev says today, so they keep testing the plumbing.
"""

from __future__ import annotations

import pytest

from app.agent.providers import options as opts
from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.responses import ResponsesHandler
from app.agent.providers.registry import PROVIDER_MODES, provider_modes
from app.agent.schemas.chat import HumanMessage


def _pin_modes(monkeypatch: pytest.MonkeyPatch, modes: dict[str, object]) -> None:
    """Pin the catalog's tier table for one lookup."""
    monkeypatch.setattr(
        "app.agent.providers.model_metadata.get_model_modes", lambda _model: modes
    )


class TestServiceTierFields:
    def test_a_declared_tier_yields_its_body_and_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_modes(
            monkeypatch,
            {"fast": {"body": {"speed": "fast"}, "headers": {"x-beta": "on"}}},
        )
        body, headers = opts.service_tier_fields("anthropic", "claude-x", "fast")
        assert body == {"speed": "fast"}
        assert headers == {"x-beta": "on"}

    def test_a_tier_the_model_lacks_yields_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking for a tier a model has no lane for must not invent a field."""
        _pin_modes(monkeypatch, {})
        assert opts.service_tier_fields("anthropic", "claude-x", "fast") == ({}, {})

    @pytest.mark.parametrize("tier", [None, "", "   ", 3, True])
    def test_no_request_yields_nothing(self, tier: object) -> None:
        assert opts.service_tier_fields("openai", "gpt-x", tier) == ({}, {})

    def test_non_string_headers_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Header values reach an HTTP client; only strings may."""
        _pin_modes(
            monkeypatch,
            {"fast": {"body": {"a": 1}, "headers": {"ok": "v", "bad": 7}}},
        )
        _body, headers = opts.service_tier_fields("openai", "gpt-x", "fast")
        assert headers == {"ok": "v"}

    def test_the_tier_name_is_matched_case_insensitively(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_modes(monkeypatch, {"fast": {"body": {"speed": "fast"}}})
        assert opts.service_tier_fields("anthropic", "c", " FAST ")[0] == {
            "speed": "fast"
        }


class TestOpenAIShapedHandlers:
    @pytest.mark.parametrize("cls", [CompletionsHandler, ResponsesHandler])
    def test_a_declared_tier_is_applied_from_its_patch(
        self, cls: type, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_modes(monkeypatch, {"fast": {"body": {"service_tier": "priority"}}})
        handler = cls("gpt-x", "https://x/v1", {})
        handler.provider_id = "openai"
        body = handler.build_request(
            [HumanMessage(content="hi")], None, False, {"service_tier": "fast"}
        )
        assert body["service_tier"] == "priority"

    @pytest.mark.parametrize("cls", [CompletionsHandler, ResponsesHandler])
    def test_an_undeclared_tier_is_forwarded_verbatim(
        self, cls: type, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``service_tier`` is a real field here, so an explicit one is honoured.

        OpenAI documents ``flex`` and ``priority`` alongside the tiers a
        model advertises; dropping one the caller named would silently
        ignore them.
        """
        _pin_modes(monkeypatch, {})
        handler = cls("gpt-x", "https://x/v1", {})
        handler.provider_id = "openai"
        body = handler.build_request(
            [HumanMessage(content="hi")], None, False, {"service_tier": "flex"}
        )
        assert body["service_tier"] == "flex"

    @pytest.mark.parametrize("cls", [CompletionsHandler, ResponsesHandler])
    @pytest.mark.parametrize("tier", ["", "auto", "default", "none", "off", "standard"])
    def test_a_no_tier_sentinel_sends_nothing(
        self, cls: type, tier: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_modes(monkeypatch, {})
        handler = cls("gpt-x", "https://x/v1", {})
        handler.provider_id = "openai"
        body = handler.build_request(
            [HumanMessage(content="hi")], None, False, {"service_tier": tier}
        )
        assert "service_tier" not in body

    @pytest.mark.parametrize("cls", [CompletionsHandler, ResponsesHandler])
    def test_a_tier_header_does_not_leak_into_shared_state(
        self, cls: type, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The handler's header dict is shared across calls; a tier's is not."""
        _pin_modes(monkeypatch, {"fast": {"headers": {"x-beta": "on"}}})
        shared = {"Authorization": "Bearer x"}
        handler = cls("gpt-x", "https://x/v1", shared)
        handler.provider_id = "openai"
        assert handler._request_headers({"service_tier": "fast"})["x-beta"] == "on"
        assert "x-beta" not in shared
        assert "x-beta" not in handler._request_headers({})


class TestAnthropicHandler:
    def test_a_tier_supplies_both_body_and_beta_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anthropic's fast mode needs a field *and* a beta flag."""
        _pin_modes(
            monkeypatch,
            {
                "fast": {
                    "body": {"speed": "fast"},
                    "headers": {"anthropic-beta": "fast-mode-2026-02-01"},
                }
            },
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test",
            model="claude-x",
            model_kwargs={"service_tier": "fast"},
        )
        merged = provider._merged_kwargs()
        body = provider._payload([HumanMessage(content="hi")], None, dict(merged))
        headers = provider._request_headers(merged)
        assert body["speed"] == "fast"
        assert headers["anthropic-beta"] == "fast-mode-2026-02-01"

    def test_no_tier_leaves_the_payload_and_headers_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_modes(monkeypatch, {"fast": {"body": {"speed": "fast"}}})
        provider = AnthropicProvider(api_key="sk-ant-test", model="claude-x")
        merged = provider._merged_kwargs()
        body = provider._payload([HumanMessage(content="hi")], None, dict(merged))
        assert "speed" not in body

    def test_an_undeclared_tier_is_not_invented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike OpenAI, ``service_tier`` is not a field Anthropic accepts."""
        _pin_modes(monkeypatch, {})
        provider = AnthropicProvider(
            api_key="sk-ant-test",
            model="claude-x",
            model_kwargs={"service_tier": "flex"},
        )
        merged = provider._merged_kwargs()
        body = provider._payload([HumanMessage(content="hi")], None, dict(merged))
        assert "service_tier" not in body
        assert "speed" not in body


class TestProviderImplementedTiers:
    def test_codex_declares_the_wire_value_not_its_config_spelling(self) -> None:
        """Codex's config calls the tier "fast"; the field takes ``priority``.

        Keeping the translation in the table means the request builder, the
        composer and the model catalog all read one value.
        """
        assert provider_modes("codex") == {
            "fast": {"body": {"service_tier": "priority"}}
        }

    def test_every_declared_tier_carries_a_body_or_headers(self) -> None:
        """A tier with no patch would be a control that selects nothing."""
        for provider_id, modes in PROVIDER_MODES.items():
            for name, spec in modes.items():
                assert spec.get("body") or spec.get("headers"), (
                    f"{provider_id}:{name} declares no wire patch"
                )
