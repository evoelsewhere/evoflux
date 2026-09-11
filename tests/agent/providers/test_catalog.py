"""The provider catalog, and how little of it is written by hand.

Every fact in a settings row now has exactly one home: the registry for
connection facts, models.dev for catalog facts, ``_OVERRIDES`` for the
handful a machine cannot know. These tests hold that line — a row that
restates something derivable is the failure mode they exist to catch.
"""

from __future__ import annotations

import pytest

from app.agent.providers.catalog import (
    _AUTH_KINDS,
    _OVERRIDES,
    _catalog_entry_from_envelope,
    all_providers,
    builtin_providers,
    catalog_providers,
    find,
)
from app.agent.providers.registry import PROVIDER_REGISTRY


class TestDerivedRows:
    def test_every_registry_provider_gets_a_row(self) -> None:
        """A provider you can connect to must be one you can configure.

        Eight providers used to be reachable by the factory with no row in
        the settings UI, so there was no way to enter a key for them.
        """
        assert {entry["id"] for entry in builtin_providers()} == set(PROVIDER_REGISTRY)

    def test_connection_facts_come_from_the_registry(self) -> None:
        for entry in builtin_providers():
            config = PROVIDER_REGISTRY[entry["id"]]
            assert entry["env_var"] == config.env_var
            # The credential form follows the auth mode unless a row says
            # otherwise: 9Router and CLIProxy are local daemons that still
            # want a key, so their form is an API-key form.
            expected = _OVERRIDES.get(entry["id"], {}).get(
                "kind", _AUTH_KINDS[config.auth]
            )
            assert entry["kind"] == expected

    def test_overrides_never_restate_a_derivable_fact(self) -> None:
        """``_OVERRIDES`` may add, never duplicate.

        A label, credential variable or docs link written here would be a
        second copy of something the registry already states, and the two
        would drift the first time either changed.
        """
        derivable = {"id", "label", "env_var", "docs_url", "env_vars"}
        offenders = {
            pid: sorted(derivable & set(override))
            for pid, override in _OVERRIDES.items()
            if derivable & set(override)
        }
        assert offenders == {}

    def test_a_hand_written_description_wins(self) -> None:
        assert find("anthropic")["description"] == "Claude API via Anthropic Messages."

    def test_a_missing_description_is_derived_not_blank(self) -> None:
        """A row with no copy still says what the endpoint is."""
        entry = find("baseten")
        assert entry is not None
        assert "baseten.co" in entry["description"]
        assert "models.dev" in entry["description"]

    def test_credentials_are_generated_from_the_registry(self) -> None:
        entry = find("deepseek")
        assert entry is not None
        assert [field["name"] for field in entry["credentials"]] == [
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
        ]

    def test_a_cloud_provider_keeps_its_hand_written_form(self) -> None:
        """Multi-field credential forms cannot be inferred, so they stay."""
        entry = find("bedrock")
        assert entry is not None
        assert entry["kind"] == "cloud_creds"
        assert "AWS_BEDROCK_REGION" in [f["name"] for f in entry["credentials"]]

    def test_env_vars_mirror_the_credential_form(self) -> None:
        for entry in builtin_providers():
            assert entry["env_vars"] == [
                field["name"] for field in entry["credentials"]
            ]


class TestCatalogIdClaims:
    def test_a_rename_is_only_claimed_when_the_id_is_free(self) -> None:
        """Codex reads OpenAI's rows without taking them over.

        ``models_dev_provider_id`` re-keys a catalog provider's models under
        another ID. That is right for ``google`` -> ``googlegenai`` and
        catastrophic for ``openai`` -> ``codex``: every ``openai:*`` model
        would vanish from the registry. Sharing is what
        ``metadata_source_provider`` is for.
        """
        codex = find("codex")
        assert codex is not None
        assert "models_dev_provider_id" not in codex
        assert codex["metadata_source_provider"] == "openai"

    def test_a_genuine_rename_is_claimed(self) -> None:
        entry = find("googlegenai")
        assert entry is not None
        assert entry["models_dev_provider_id"] == "google"

    def test_openai_models_survive_codex_being_configured(self) -> None:
        from app.agent.providers.model_registry import provider_model_counts

        counts = provider_model_counts()
        assert counts.get("openai", (0, 0))[0] > 0


class TestLongTail:
    def test_the_catalog_tier_excludes_curated_providers(self) -> None:
        curated = set(PROVIDER_REGISTRY)
        curated |= {c.models_dev_provider_id for c in PROVIDER_REGISTRY.values()}
        assert {entry["id"] for entry in catalog_providers()} & curated == set()

    def test_no_duplicate_rows(self) -> None:
        ids = [entry["id"] for entry in all_providers()]
        assert len(ids) == len(set(ids))

    def test_the_long_tail_is_not_auto_connected(self) -> None:
        """Opening settings must not fan out to 160-odd endpoints.

        It would also send a vendor's key to plan variants of theirs the
        user never selected, since those share one credential variable.
        """
        assert all(entry["auto_connect"] is False for entry in catalog_providers())

    def test_curated_providers_keep_their_connect_behaviour(self) -> None:
        assert find("anthropic")["auto_connect"] is True

    @pytest.mark.parametrize(
        "envelope",
        [
            {"id": "x", "env": ["K"]},  # no endpoint
            {"id": "x", "api": "https://x/v1"},  # no credential
            {"id": "x", "env": ["K"], "api": "https://${Y}/v1"},  # templated
            {"env": ["K"], "api": "https://x/v1"},  # no id
        ],
    )
    def test_unusable_envelopes_are_not_listed(self, envelope: dict) -> None:
        """A row that can never reach a working state is worse than none."""
        assert _catalog_entry_from_envelope(envelope) is None

    def test_a_usable_envelope_becomes_a_row(self) -> None:
        entry = _catalog_entry_from_envelope(
            {
                "id": "my-host",
                "name": "My Host",
                "env": ["MY_HOST_API_KEY"],
                "api": "https://api.my-host.dev/v1",
                "npm": "@ai-sdk/openai-compatible",
                "doc": "https://docs.my-host.dev",
            }
        )
        assert entry is not None
        assert entry["label"] == "My Host"
        assert entry["source"] == "catalog"
        assert entry["env_var"] == "MY_HOST_API_KEY"
        assert "MY_HOST_BASE_URL" in entry["env_vars"]
        assert entry["docs_url"] == "https://docs.my-host.dev"

    def test_a_secret_looking_variable_is_masked(self) -> None:
        entry = _catalog_entry_from_envelope(
            {
                "id": "h",
                "env": ["H_API_KEY", "H_REGION"],
                "api": "https://h/v1",
            }
        )
        assert entry is not None
        secrets = {f["name"]: f["secret"] for f in entry["credentials"]}
        assert secrets["H_API_KEY"] is True
        # A region names a setting, not a credential, and masking it would
        # only stop the user reading back what they typed.
        assert secrets["H_REGION"] is False
