"""Tests for the Microsoft Foundry (Azure AI Foundry) provider.

Covers:
- foundry_base_url / foundry_anthropic_base_url: resource-or-URL parsing
- FoundryProvider.__init__: inherits OpenAIProvider, dual auth headers,
  keeps the thinking-level → /responses auto-routing
- FoundryClaudeProvider.__init__: Anthropic surface base URL + api-key header
- build_provider: foundry branch reads FOUNDRY_API_KEY/FOUNDRY_RESOURCE_NAME
  and routes claude deployments to the Anthropic surface
- Capabilities: foundry: prefix fallback → vision=True
- app/core/config.py: FOUNDRY_API_KEY / FOUNDRY_RESOURCE_NAME fields present
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.capabilities import get_capabilities
from app.agent.providers.foundry import (
    FoundryClaudeProvider,
    FoundryProvider,
    foundry_anthropic_base_url,
    foundry_base_url,
)
from app.agent.providers.openai import OpenAIProvider


# ============================================================================
# Class hierarchy
# ============================================================================


class TestFoundryProviderInheritance:
    def test_foundry_provider_is_subclass_of_openai_provider(self):
        assert issubclass(FoundryProvider, OpenAIProvider)

    def test_foundry_claude_provider_is_subclass_of_anthropic_provider(self):
        assert issubclass(FoundryClaudeProvider, AnthropicProvider)


# ============================================================================
# foundry_base_url — resource-or-URL normalisation
# ============================================================================


class TestFoundryBaseUrl:
    def test_bare_resource_name(self):
        assert (
            foundry_base_url("myres")
            == "https://myres.services.ai.azure.com/openai/v1"
        )

    def test_bare_hostname_is_not_suffixed(self):
        assert (
            foundry_base_url("myres.openai.azure.com")
            == "https://myres.openai.azure.com/openai/v1"
        )

    def test_sovereign_cloud_hostname(self):
        assert (
            foundry_base_url("myres.cognitiveservices.azure.us")
            == "https://myres.cognitiveservices.azure.us/openai/v1"
        )

    def test_full_url_without_path(self):
        assert (
            foundry_base_url("https://myres.services.ai.azure.com")
            == "https://myres.services.ai.azure.com/openai/v1"
        )

    def test_full_url_trailing_slash(self):
        assert (
            foundry_base_url("https://myres.services.ai.azure.com/")
            == "https://myres.services.ai.azure.com/openai/v1"
        )

    def test_full_url_already_v1(self):
        assert (
            foundry_base_url("https://myres.openai.azure.com/openai/v1")
            == "https://myres.openai.azure.com/openai/v1"
        )

    def test_full_url_already_v1_trailing_slash(self):
        assert (
            foundry_base_url("https://myres.openai.azure.com/openai/v1/")
            == "https://myres.openai.azure.com/openai/v1"
        )

    def test_full_url_ending_in_openai(self):
        assert (
            foundry_base_url("https://myres.openai.azure.com/openai")
            == "https://myres.openai.azure.com/openai/v1"
        )

    def test_surrounding_whitespace_stripped(self):
        assert (
            foundry_base_url("  myres  ")
            == "https://myres.services.ai.azure.com/openai/v1"
        )

    @pytest.mark.parametrize("value", ["", "   ", "/"])
    def test_empty_raises(self, value: str):
        with pytest.raises(ValueError, match="FOUNDRY_RESOURCE_NAME"):
            foundry_base_url(value)


class TestFoundryAnthropicBaseUrl:
    def test_bare_resource_name(self):
        assert (
            foundry_anthropic_base_url("myres")
            == "https://myres.services.ai.azure.com/anthropic"
        )

    def test_bare_hostname(self):
        assert (
            foundry_anthropic_base_url("myres.services.ai.azure.com")
            == "https://myres.services.ai.azure.com/anthropic"
        )

    def test_full_url_reduced_to_origin(self):
        # Users typically paste the OpenAI-surface target URI.
        assert (
            foundry_anthropic_base_url("https://myres.services.ai.azure.com/openai/v1")
            == "https://myres.services.ai.azure.com/anthropic"
        )

    def test_full_url_already_anthropic(self):
        assert (
            foundry_anthropic_base_url("https://myres.services.ai.azure.com/anthropic")
            == "https://myres.services.ai.azure.com/anthropic"
        )

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="FOUNDRY_RESOURCE_NAME"):
            foundry_anthropic_base_url("")


# ============================================================================
# FoundryProvider.__init__
# ============================================================================


class TestFoundryProviderInit:
    def _make_provider(self, **kwargs) -> FoundryProvider:
        """Helper — patch handlers so no real network calls are made."""
        with patch("app.agent.providers.openai.openai.CompletionsHandler"):
            with patch("app.agent.providers.openai.openai.ResponsesHandler"):
                return FoundryProvider(
                    api_key="foundry-test-key",
                    model="gpt-5.1",
                    resource="myres",
                    **kwargs,
                )

    def test_base_url_derived_from_resource(self):
        p = self._make_provider()
        assert p.base_url == "https://myres.services.ai.azure.com/openai/v1"

    def test_model_stored(self):
        p = self._make_provider()
        assert p.model == "gpt-5.1"

    def test_api_key_stored(self):
        p = self._make_provider()
        assert p.api_key == "foundry-test-key"

    def test_headers_carry_both_auth_forms(self):
        p = self._make_provider()
        headers = p._build_headers()
        assert headers["api-key"] == "foundry-test-key"
        assert headers["Authorization"] == "Bearer foundry-test-key"
        assert headers["Content-Type"] == "application/json"

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            FoundryProvider(api_key="", model="gpt-5.1", resource="myres")

    def test_empty_resource_raises(self):
        with pytest.raises(ValueError, match="FOUNDRY_RESOURCE_NAME"):
            FoundryProvider(api_key="foundry-test-key", model="gpt-5.1", resource="")

    def test_thinking_level_routes_to_responses(self):
        # Deliberate divergence from xai: the Foundry v1 surface
        # implements /responses, so the parent auto-routing stays.
        p = self._make_provider(model_kwargs={"thinking_level": "high"})
        assert p._use_responses is True

    def test_default_stays_on_chat_completions(self):
        p = self._make_provider()
        assert p._use_responses is False

    def test_model_kwargs_forwarded(self):
        p = self._make_provider(model_kwargs={"extra_param": "value"})
        assert p.model_kwargs.get("extra_param") == "value"


# ============================================================================
# FoundryClaudeProvider.__init__
# ============================================================================


class TestFoundryClaudeProviderInit:
    def test_base_url_is_anthropic_surface(self):
        p = FoundryClaudeProvider(
            api_key="foundry-test-key",
            model="claude-sonnet-4-6",
            resource="myres",
        )
        assert p.base_url == "https://myres.services.ai.azure.com/anthropic"

    def test_headers_carry_api_key_and_x_api_key(self):
        p = FoundryClaudeProvider(
            api_key="foundry-test-key",
            model="claude-sonnet-4-6",
            resource="myres",
        )
        assert p.headers["api-key"] == "foundry-test-key"
        assert p.headers["x-api-key"] == "foundry-test-key"
        assert "anthropic-version" in p.headers

    def test_empty_api_key_raises_foundry_message(self):
        with pytest.raises(ValueError, match="FOUNDRY_API_KEY"):
            FoundryClaudeProvider(
                api_key="", model="claude-sonnet-4-6", resource="myres"
            )


# ============================================================================
# Provider factory — foundry branch
# ============================================================================


class TestFoundryProviderFactory:
    def _settings_mock(self, mock_settings, *, key="foundry-secret", resource="myres"):
        mock_settings.FOUNDRY_API_KEY = MagicMock()
        mock_settings.FOUNDRY_API_KEY.get_secret_value.return_value = key
        mock_settings.FOUNDRY_RESOURCE_NAME = resource

    def test_factory_builds_foundry_provider(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        with patch(
            "app.agent.providers.factory.FoundryProvider", return_value=MagicMock()
        ) as MockFoundry:
            with patch("app.core.config.settings") as mock_settings:
                self._settings_mock(mock_settings)
                build_provider("foundry:gpt-5.1")

            MockFoundry.assert_called_once()
            call_kwargs = MockFoundry.call_args.kwargs
            assert call_kwargs.get("api_key") == "foundry-secret"
            assert call_kwargs.get("model") == "gpt-5.1"
            assert call_kwargs.get("resource") == "myres"

    def test_factory_routes_claude_deployment_to_anthropic_surface(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        with patch(
            "app.agent.providers.factory.FoundryClaudeProvider",
            return_value=MagicMock(),
        ) as MockClaude:
            with patch("app.core.config.settings") as mock_settings:
                self._settings_mock(mock_settings)
                build_provider("foundry:claude-sonnet-4-6")

            MockClaude.assert_called_once()
            assert MockClaude.call_args.kwargs.get("model") == "claude-sonnet-4-6"

    def test_factory_anthropic_api_flag_forces_claude_route(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        with patch(
            "app.agent.providers.factory.FoundryClaudeProvider",
            return_value=MagicMock(),
        ) as MockClaude:
            with patch("app.core.config.settings") as mock_settings:
                self._settings_mock(mock_settings)
                build_provider(
                    "foundry:my-renamed-deployment",
                    model_kwargs={"anthropic_api": True},
                )

            MockClaude.assert_called_once()

    def test_factory_anthropic_api_false_overrides_claude_heuristic(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        with patch(
            "app.agent.providers.factory.FoundryProvider", return_value=MagicMock()
        ) as MockFoundry:
            with patch("app.core.config.settings") as mock_settings:
                self._settings_mock(mock_settings)
                build_provider(
                    "foundry:claude-sonnet-4-6",
                    model_kwargs={"anthropic_api": False},
                )

            MockFoundry.assert_called_once()

    def test_factory_reads_resource_from_env_first(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.setenv("FOUNDRY_RESOURCE_NAME", "env-resource")
        with patch(
            "app.agent.providers.factory.FoundryProvider", return_value=MagicMock()
        ) as MockFoundry:
            with patch("app.core.config.settings") as mock_settings:
                self._settings_mock(mock_settings, resource="settings-resource")
                build_provider("foundry:gpt-5.1")

            assert MockFoundry.call_args.kwargs.get("resource") == "env-resource"

    def test_factory_raises_when_api_key_missing(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.FOUNDRY_API_KEY = None
            with pytest.raises(ValueError, match="FOUNDRY_API_KEY"):
                build_provider("foundry:gpt-5.1")

    def test_factory_raises_when_resource_missing(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        with patch("app.core.config.settings") as mock_settings:
            self._settings_mock(mock_settings, resource="")
            with pytest.raises(ValueError, match="FOUNDRY_RESOURCE_NAME"):
                build_provider("foundry:gpt-5.1")

    def test_foundry_in_supported_providers(self):
        from app.agent.providers.factory import SUPPORTED_PROVIDERS

        assert "foundry" in SUPPORTED_PROVIDERS


# ============================================================================
# Capabilities — foundry: fallback resolution
# ============================================================================


class TestFoundryCapabilities:
    def test_unknown_deployment_falls_back_to_vision(self):
        # Deployment names are user-chosen, so registry lookups will
        # frequently miss; foundry is in _VISION_PROVIDERS.
        caps = get_capabilities("foundry:my-custom-deploy")
        assert caps.input.vision is True

    def test_case_insensitive_lookup(self):
        caps_lower = get_capabilities("foundry:my-custom-deploy")
        caps_upper = get_capabilities("FOUNDRY:my-custom-deploy")
        assert caps_lower == caps_upper


# ============================================================================
# Settings — FOUNDRY_* fields
# ============================================================================


class TestFoundrySettings:
    def test_foundry_api_key_field_exists(self):
        from app.core.config import Settings

        s = Settings()
        assert hasattr(s, "FOUNDRY_API_KEY")

    def test_foundry_api_key_defaults_to_none(self, monkeypatch):
        from app.core.config import Settings

        monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.FOUNDRY_API_KEY is None

    def test_foundry_resource_name_defaults_to_empty(self, monkeypatch):
        from app.core.config import Settings

        monkeypatch.delenv("FOUNDRY_RESOURCE_NAME", raising=False)
        s = Settings(_env_file=None)
        assert s.FOUNDRY_RESOURCE_NAME == ""

    def test_foundry_api_key_accepts_string_via_env(self, monkeypatch):
        from app.core.config import Settings

        monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-test-value")
        s = Settings()
        assert s.FOUNDRY_API_KEY is not None
        assert s.FOUNDRY_API_KEY.get_secret_value() == "foundry-test-value"
