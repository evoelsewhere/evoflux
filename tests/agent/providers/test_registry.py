"""Provider resolution, and how much of it the model catalog owns.

The point of these tests is the *boundary*: which facts EvoFlux states in
code and which it reads from models.dev. A provider's endpoint, credential
names, display name and documentation are catalog data; the wire dialect,
attribution headers and plan-level service tiers are not, because no catalog
publishes them. Tests that pin a base URL to a literal string would defeat
the whole arrangement, so these assert the *source* of each value instead.
"""

from __future__ import annotations

import pytest

from app.agent.providers import registry as reg
from app.agent.providers.registry import (
    PROVIDER_REGISTRY,
    ProviderConfig,
    Transport,
    catalog_base_url,
    catalog_docs_url,
    catalog_env_vars,
    clamp_thinking_level,
    config_from_models_dev,
    custom_provider,
    normalize_thinking_level,
    provider_ids,
    provider_label,
    provider_modes,
    request_headers,
    resolve_api_key,
    resolve_base_url,
    resolve_provider,
    transport_for_npm,
    with_overrides,
)


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------


class TestBaseUrlResolution:
    def test_every_provider_resolves_to_an_endpoint(self) -> None:
        """No provider may be left without a way to reach it.

        A provider whose ``base_url`` is empty is not broken — it is one
        whose endpoint the catalog publishes. This is the test that keeps
        that promise honest: if models.dev ever drops a provider EvoFlux
        stopped restating a URL for, this fails rather than the provider
        silently becoming unreachable at runtime.
        """
        unreachable = [
            pid
            for pid, config in PROVIDER_REGISTRY.items()
            # Cloud providers reach their SDK without a URL at all.
            if config.auth != "cloud" and not resolve_base_url(config)
        ]
        assert unreachable == []

    def test_curated_url_is_an_override_not_a_restatement(self) -> None:
        """A hardcoded URL must differ from the catalog, or not exist.

        Restating a URL the catalog already publishes is exactly the
        duplication that goes stale when a provider moves its API, so a
        curated ``base_url`` is only allowed where EvoFlux deliberately
        diverges or the catalog has no endpoint at all.
        """
        redundant = [
            pid
            for pid, config in PROVIDER_REGISTRY.items()
            if config.base_url
            and (catalog := catalog_base_url(config))
            and catalog.rstrip("/") == config.base_url.rstrip("/")
        ]
        assert redundant == []

    def test_catalog_supplies_the_url_when_curated_is_empty(self) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        assert config.base_url == ""
        assert resolve_base_url(config) == catalog_base_url(config)

    def test_env_override_beats_the_catalog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:9/v1  ")
        assert resolve_base_url(config) == "http://localhost:9/v1"

    def test_explicit_value_beats_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://from-env/v1")
        assert (
            resolve_base_url(config, explicit="http://explicit/v1")
            == "http://explicit/v1"
        )

    def test_templated_catalog_url_is_not_an_endpoint(self) -> None:
        """``https://${AZURE_RESOURCE_NAME}...`` is a shape, not an address."""
        config = ProviderConfig(id="fake", label="Fake", models_dev_id="azure")
        assert "${" in (reg.catalog_entry(config).get("api") or "${x}")
        assert catalog_base_url(config) == ""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    def test_evoflux_variable_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = PROVIDER_REGISTRY["kimi"]
        monkeypatch.setenv("MOONSHOT_API_KEY", "ours")
        monkeypatch.setenv("KIMI_API_KEY", "theirs")
        assert resolve_api_key(config) == "ours"

    def test_catalog_variable_is_read_as_a_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A user who set the conventional variable should just work.

        EvoFlux renames Kimi's key to keep it apart from the Moonshot
        platform's; every other tool calls it ``KIMI_API_KEY``. Reading the
        catalog's names too means an existing environment needs no edit.
        """
        config = PROVIDER_REGISTRY["kimi"]
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        monkeypatch.setenv("KIMI_API_KEY", "theirs")
        assert "KIMI_API_KEY" in catalog_env_vars(config)
        assert resolve_api_key(config) == "theirs"

    def test_explicit_credential_short_circuits_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        assert resolve_api_key(config, explicit="explicit") == "explicit"

    def test_placeholder_credential_is_the_last_resort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ollama wants the header present and does not care what is in it."""
        config = PROVIDER_REGISTRY["ollama"]
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        assert resolve_api_key(config) == "ollama"

    def test_missing_credential_resolves_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert resolve_api_key(config) is None


# ---------------------------------------------------------------------------
# Catalog-backed presentation
# ---------------------------------------------------------------------------


class TestCatalogPresentation:
    def test_label_falls_back_to_the_catalog_name(self) -> None:
        config = ProviderConfig(id="groq", label="", models_dev_id="groq")
        assert provider_label(config) == "Groq"

    def test_label_falls_back_to_the_id_when_unlisted(self) -> None:
        config = ProviderConfig(id="nowhere", label="", models_dev_id="nowhere")
        assert provider_label(config) == "nowhere"

    def test_catalog_docs_are_separate_from_the_key_page(self) -> None:
        """Two different links, both useful, neither a substitute.

        ``docs_url`` is where a user creates an API key; the catalog's
        ``doc`` is where they read what the models do.
        """
        config = PROVIDER_REGISTRY["anthropic"]
        assert config.docs_url.startswith("https://console.anthropic.com")
        assert catalog_docs_url(config).startswith("https://docs.anthropic.com")


# ---------------------------------------------------------------------------
# Offline behaviour
# ---------------------------------------------------------------------------


class TestOfflineColdStart:
    def test_bundled_envelopes_cover_every_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An install that has never reached the network still resolves.

        The provider envelopes ship with the package precisely so dropping
        the curated URLs did not trade a stale constant for an install that
        cannot reach anything until it downloads a catalog.
        """
        from app.agent.providers import model_registry

        monkeypatch.setattr(
            model_registry, "_load_models_dev_data", lambda: None, raising=True
        )
        model_registry._models_dev_providers.cache_clear()
        try:
            unreachable = [
                pid
                for pid, config in PROVIDER_REGISTRY.items()
                if config.auth != "cloud" and not resolve_base_url(config)
            ]
        finally:
            model_registry._models_dev_providers.cache_clear()
        assert unreachable == []


# ---------------------------------------------------------------------------
# Long-tail providers
# ---------------------------------------------------------------------------


class TestCatalogOnlyProviders:
    def test_a_provider_with_no_curated_entry_still_resolves(self) -> None:
        """The long tail is reachable from its catalog row alone."""
        assert "cerebras" in PROVIDER_REGISTRY
        config = resolve_provider("chutes")
        assert config is not None
        assert config.id == "chutes"
        assert resolve_base_url(config)
        assert config.env_var

    def test_unknown_provider_resolves_to_none(self) -> None:
        assert resolve_provider("not-a-real-provider") is None
        assert resolve_provider("") is None

    def test_catalog_config_needs_both_an_endpoint_and_a_credential(self) -> None:
        assert config_from_models_dev("x", {"env": ["K"], "api": ""}) is None
        assert config_from_models_dev("x", {"env": [], "api": "https://x/v1"}) is None
        assert (
            config_from_models_dev("x", {"env": ["K"], "api": "https://${Y}/v1"})
            is None
        )

    def test_catalog_config_derives_a_base_url_override_name(self) -> None:
        config = config_from_models_dev(
            "my-host", {"env": ["K"], "api": "https://x/v1", "name": "My Host"}
        )
        assert config is not None
        assert config.base_url_env_var == "MY_HOST_BASE_URL"
        assert config.label == "My Host"


# ---------------------------------------------------------------------------
# Wire shape
# ---------------------------------------------------------------------------


class TestTransportMapping:
    @pytest.mark.parametrize(
        ("npm", "expected"),
        [
            ("@ai-sdk/openai-compatible", Transport.OPENAI_COMPLETIONS),
            ("@ai-sdk/openai", Transport.OPENAI_RESPONSES),
            ("@ai-sdk/anthropic", Transport.ANTHROPIC),
            ("@ai-sdk/google", Transport.GOOGLE_GENAI),
            ("@ai-sdk/amazon-bedrock", Transport.BEDROCK),
        ],
    )
    def test_known_adapters_map_to_a_transport(
        self, npm: str, expected: Transport
    ) -> None:
        assert transport_for_npm(npm) is expected

    def test_unknown_adapter_defaults_to_chat_completions(self) -> None:
        """The safe guess for an unrecognised host, and usually the right one."""
        assert transport_for_npm("@someone/brand-new") is Transport.OPENAI_COMPLETIONS
        assert transport_for_npm(None) is Transport.OPENAI_COMPLETIONS

    def test_responses_routing_is_per_model_where_it_has_to_be(self) -> None:
        config = PROVIDER_REGISTRY["openai"]
        assert config.uses_responses_api("gpt-5") is True

    def test_completions_provider_routes_no_model_to_responses(self) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        assert config.uses_responses_api("deepseek-v4-pro") is False


# ---------------------------------------------------------------------------
# Service tiers
# ---------------------------------------------------------------------------


class TestProviderModes:
    def test_codex_fast_lane_is_declared_not_inferred(self) -> None:
        """Codex's fast lane belongs to a plan, so no catalog publishes it.

        It is declared here instead, in the same shape the catalog uses, so
        that every consumer asks "does this model have a fast tier?" rather
        than testing for a ``codex:`` prefix. The patch holds the *wire*
        value: Codex's own config spells the tier "fast", OpenAI's field
        takes ``priority``, and keeping the translation here means nothing
        downstream repeats it.
        """
        assert provider_modes("codex") == {
            "fast": {"body": {"service_tier": "priority"}}
        }

    def test_providers_without_a_declared_tier_have_none(self) -> None:
        assert provider_modes("anthropic") == {}
        assert provider_modes("") == {}


# ---------------------------------------------------------------------------
# Headers and overrides
# ---------------------------------------------------------------------------


class TestHeadersAndOverrides:
    def test_gateways_carry_attribution(self) -> None:
        headers = request_headers(PROVIDER_REGISTRY["openrouter"])
        assert headers["HTTP-Referer"]
        assert headers["X-Title"] == "EvoFlux"

    def test_first_party_providers_carry_no_attribution(self) -> None:
        assert request_headers(PROVIDER_REGISTRY["anthropic"]) == {}

    def test_overrides_replace_only_what_is_given(self) -> None:
        config = PROVIDER_REGISTRY["deepseek"]
        overridden = with_overrides(config, base_url="http://x/v1")
        assert overridden.base_url == "http://x/v1"
        assert overridden.env_var == config.env_var
        assert with_overrides(config) is config

    def test_custom_provider_uses_the_url_verbatim(self) -> None:
        """Whether a trailing ``/v1`` belongs is the endpoint's business."""
        config = custom_provider("my-llm", base_url="http://box:8080")
        assert config.base_url == "http://box:8080"
        assert config.env_var == "MY_LLM_API_KEY"
        assert config.base_url_env_var == "MY_LLM_BASE_URL"


# ---------------------------------------------------------------------------
# Thinking vocabulary
# ---------------------------------------------------------------------------


class TestThinkingVocabulary:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("high", "high"),
            ("HIGH", "high"),
            ("  medium  ", "medium"),
            ("off", "none"),
            ("disabled", "none"),
            ("ultra", "max"),
            ("x-high", "xhigh"),
            ("", ""),
            ("nonsense", ""),
            (None, ""),
            (3, ""),
        ],
    )
    def test_normalization(self, value: object, expected: str) -> None:
        assert normalize_thinking_level(value) == expected

    def test_a_typo_expresses_no_preference(self) -> None:
        """Better to fall back to the provider default than guess an effort."""
        assert normalize_thinking_level("hgih") == ""

    @pytest.mark.parametrize(
        ("level", "supported", "expected"),
        [
            ("max", ("low", "medium", "high"), "high"),
            ("high", ("low", "medium", "high"), "high"),
            ("medium", ("low", "high"), "low"),
            ("minimal", ("low", "medium", "high"), "low"),
            ("high", (), ""),
        ],
    )
    def test_clamping_snaps_down(
        self, level: str, supported: tuple[str, ...], expected: str
    ) -> None:
        assert clamp_thinking_level(level, supported) == expected

    def test_clamping_below_the_floor_takes_the_weakest(self) -> None:
        """Asking for less than a model offers still has to reason somehow."""
        assert clamp_thinking_level("minimal", ("high", "max")) == "high"


def test_provider_ids_are_sorted_and_complete() -> None:
    assert provider_ids() == tuple(sorted(PROVIDER_REGISTRY))
