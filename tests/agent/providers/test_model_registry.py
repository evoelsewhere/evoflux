from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.agent.providers import model_metadata, model_registry
from app.agent.providers.capabilities import get_capabilities
from app.agent.providers.model_metadata import (
    get_model_cost,
    get_model_features,
    get_model_limits,
    get_model_thinking_levels,
)


def _clear_registry_caches() -> None:
    # One call, because the catalog now feeds several caches — the provider
    # envelopes and the settings-UI rows derived from them included — and
    # clearing a subset leaves the rest answering from data that is gone.
    model_registry.reset_catalog_caches()
    model_metadata.clear_runtime_model_metadata()


@pytest.fixture(autouse=True)
def _registry_cache_cleanup():
    _clear_registry_caches()
    yield
    _clear_registry_caches()


def test_models_dev_metadata_is_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "id": "openai",
                "models": {
                    "gpt-live": {
                        "id": "gpt-live",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 123000, "output": 4567},
                        "cost": {
                            "input": 1.25,
                            "output": 10.0,
                            "cache_read": 0.1,
                            "cache_write": 0.2,
                        },
                        "tool_call": True,
                        "attachment": True,
                        "temperature": False,
                        "reasoning": True,
                        "status": "beta",
                        "release_date": "2026-01-02",
                    }
                },
            }
        },
    )

    assert get_capabilities("openai:gpt-live").input.vision is True
    limits = get_model_limits("openai:gpt-live")
    assert limits.context_length == 123000
    assert limits.max_completion_tokens == 4567
    cost = get_model_cost("openai:gpt-live")
    assert cost.input == 1.25
    assert cost.output == 10.0
    assert cost.cache_read == 0.1
    assert cost.cache_write == 0.2
    features = get_model_features("openai:gpt-live")
    assert features.tool_call is True
    assert features.attachment is True
    assert features.temperature is False
    assert features.reasoning is True
    assert features.status == "beta"
    assert features.release_date == "2026-01-02"


def test_models_dev_provider_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "amazon-bedrock": {
                "id": "amazon-bedrock",
                "models": {
                    "anthropic.claude-sonnet-4-6": {
                        "id": "anthropic.claude-sonnet-4-6",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 2000, "output": 200},
                    }
                },
            },
            "google": {
                "id": "google",
                "models": {
                    "gemini-live": {
                        "id": "gemini-live",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 1000, "output": 100},
                    }
                },
            },
            "alibaba": {
                "id": "alibaba",
                "models": {
                    "qwen-live": {
                        "id": "qwen-live",
                        "modalities": {
                            "input": ["text", "image"],
                            "output": ["text"],
                        },
                        "limit": {"context": 3000, "output": 300},
                        "tool_call": True,
                    }
                },
            },
        },
    )

    assert get_capabilities("bedrock:anthropic.claude-sonnet-4-6").input.vision is True
    assert (
        get_model_limits("bedrock:anthropic.claude-sonnet-4-6").context_length == 2000
    )
    assert get_capabilities("googlegenai:gemini-live").input.vision is True
    assert get_model_limits("googlegenai:gemini-live").context_length == 1000
    assert get_capabilities("qwencloud:qwen-live").input.vision is True
    assert get_model_limits("qwencloud:qwen-live").context_length == 3000
    assert get_model_features("qwencloud:qwen-live").tool_call is True


def test_provider_owned_model_registry_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_provider_entries",
        lambda include_plugins: [
            {
                "id": "runtime",
                "metadata_source_provider": "openai",
                "model_registry_aliases": {"renamed-live": "openai:gpt-renamed-source"},
            }
        ],
    )
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "id": "openai",
                "models": {
                    "gpt-live": {
                        "id": "gpt-live",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 222000, "output": 333},
                    },
                    "gpt-renamed-source": {
                        "id": "gpt-renamed-source",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 666000, "output": 777},
                    },
                },
            },
        },
    )

    assert get_capabilities("runtime:gpt-live").input.vision is True
    assert get_model_limits("runtime:gpt-live").context_length == 222000
    assert get_capabilities("runtime:renamed-live").input.vision is True
    assert get_model_limits("runtime:renamed-live").context_length == 666000


def test_provider_alias_can_exclude_endpoint_specific_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_provider_entries",
        lambda include_plugins: [
            {
                "id": "runtime",
                "metadata_source_provider": "openai",
                "metadata_source_exclude": ["thinking"],
            }
        ],
    )
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "models": {
                    "gpt-live": {
                        "limit": {"context": 123000},
                        "reasoning_options": [
                            {"type": "effort", "values": ["low", "high"]}
                        ],
                    }
                }
            }
        },
    )

    assert get_model_limits("runtime:gpt-live").context_length == 123000
    assert get_model_thinking_levels("runtime:gpt-live") == ()


def test_snapshot_bundles_the_whole_catalog_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every provider EvoFlux can use gets offline metadata.

    EvoFlux configures and uses every provider models.dev lists, so limiting
    the bundle to curated ones would leave the long tail with real
    credentials, a real endpoint and no idea what its models can do until
    the catalog downloads — a silent failure, since limits and prices would
    read "unknown".
    """
    from scripts.update_model_registry import _build_registry

    registry = _build_registry(
        {
            "openai:gpt-live": {"limits": {"context_length": 123000}},
            "chutes:some-model": {"limits": {"context_length": 1}},
        }
    )

    assert registry["chutes:some-model"]["limits"]["context_length"] == 1
    assert registry["openai:gpt-live"]["limits"]["context_length"] == 123000


def test_snapshot_can_be_narrowed_to_curated_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--curated-only`` keeps the older, smaller shape."""
    from scripts.update_model_registry import _build_registry

    monkeypatch.setattr(
        "scripts.update_model_registry._supported_provider_ids",
        lambda: {"openai", "codex"},
    )
    registry = _build_registry(
        {
            "openai:gpt-live": {
                "limits": {"context_length": 123000},
                "thinking": {"levels": ["low", "high"]},
            },
            "removed-provider:stale-model": {"limits": {"context_length": 1}},
        },
        curated_only=True,
    )

    assert "removed-provider:stale-model" not in registry
    assert registry["openai:gpt-live"]["thinking"]["levels"] == ["low", "high"]
    # Codex inherits OpenAI's limits but not its reasoning controls, which
    # come from the Codex catalogue at runtime.
    assert registry["codex:gpt-live"]["limits"]["context_length"] == 123000
    assert "thinking" not in registry["codex:gpt-live"]


def test_provider_aliases_are_ignored_when_plugins_are_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_registry,
        "_provider_entries",
        lambda include_plugins: [
            {
                "id": "builtin-runtime",
                "models_dev_provider_id": "builtin-source",
                "metadata_source_provider": "openai",
            },
            *(
                [
                    {
                        "id": "plugin-runtime",
                        "models_dev_provider_id": "plugin-source",
                        "metadata_source_provider": "anthropic",
                        "model_registry_aliases": {
                            "plugin-renamed": "openai:gpt-source"
                        },
                    }
                ]
                if include_plugins
                else []
            ),
        ],
    )

    data = {
        "builtin-source": {
            "models": {
                "builtin-model": {
                    "modalities": {"input": ["image"], "output": ["text"]}
                }
            }
        },
        "plugin-source": {
            "models": {
                "plugin-model": {"modalities": {"input": ["image"], "output": ["text"]}}
            }
        },
    }

    with_plugins = model_registry._normalize_models_dev(data, include_plugins=True)
    without_plugins = model_registry._normalize_models_dev(data, include_plugins=False)
    registry = {
        "openai:gpt-source": {"limits": {"context_length": 123}},
        "anthropic:claude-source": {"limits": {"context_length": 456}},
    }

    assert "plugin-runtime:plugin-model" in with_plugins
    assert "plugin-source:plugin-model" in without_plugins
    assert "plugin-runtime:plugin-model" not in without_plugins

    with_plugin_aliases = model_registry.apply_model_registry_aliases(
        registry, overwrite=True, include_plugins=True
    )
    without_plugin_aliases = model_registry.apply_model_registry_aliases(
        registry, overwrite=True, include_plugins=False
    )
    assert (
        with_plugin_aliases["plugin-runtime:plugin-renamed"]["limits"]["context_length"]
        == 123
    )
    assert "plugin-runtime:plugin-renamed" not in without_plugin_aliases


def test_model_aliases_ignore_malformed_and_missing_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_registry,
        "_provider_entries",
        lambda include_plugins: [
            {
                "id": "runtime",
                "model_registry_aliases": {
                    "renamed": "openai:gpt-source",
                    "other:explicit": "openai:gpt-source",
                    "missing": "openai:missing",
                    123: "openai:gpt-source",
                    "bad-source": 456,
                },
            },
            {"id": "broken", "metadata_source_provider": 123},
            {"metadata_source_provider": "openai"},
        ],
    )

    aliased = model_registry.apply_model_registry_aliases(
        {"openai:gpt-source": {"limits": {"context_length": 123}}},
        overwrite=True,
    )

    assert aliased["runtime:renamed"]["limits"]["context_length"] == 123
    assert aliased["other:explicit"]["limits"]["context_length"] == 123
    assert "runtime:missing" not in aliased
    assert "runtime:bad-source" not in aliased
    assert "broken:gpt-source" not in aliased


def test_refreshed_source_metadata_updates_stale_alias_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_provider_entries",
        lambda include_plugins: [
            {"id": "runtime", "metadata_source_provider": "openai"}
        ],
    )
    monkeypatch.setattr(
        model_registry,
        "_load_bundled_registry",
        lambda: {
            "runtime:gpt-live": {
                "capabilities": {"input": {"audio": True}},
                "limits": {"context_length": 100, "max_completion_tokens": 20},
            }
        },
    )
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "models": {
                    "gpt-live": {
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 900, "output": 80},
                    }
                }
            }
        },
    )

    caps = get_capabilities("runtime:gpt-live")
    limits = get_model_limits("runtime:gpt-live")
    assert caps.input.audio is True
    assert caps.input.vision is True
    assert limits.context_length == 900
    assert limits.max_completion_tokens == 80


def test_user_overlay_wins_over_models_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_registry.yaml").write_text(
        """
openai:gpt-live:
  capabilities:
    input: {audio: true}
  limits: {context_length: 999, max_completion_tokens: 88}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "id": "openai",
                "models": {
                    "gpt-live": {
                        "id": "gpt-live",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 123000, "output": 4567},
                    }
                },
            }
        },
    )

    caps = get_capabilities("openai:gpt-live")
    assert caps.input.vision is True
    assert caps.input.audio is True
    limits = get_model_limits("openai:gpt-live")
    assert limits.context_length == 999
    assert limits.max_completion_tokens == 88


def test_user_overlay_propagates_to_metadata_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_registry.yaml").write_text(
        """
openai:gpt-live:
  limits: {context_length: 999}
codex:gpt-live:
  limits: {max_completion_tokens: 88}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)
    monkeypatch.setattr(
        model_registry,
        "_fetch_models_dev",
        lambda: {
            "openai": {
                "id": "openai",
                "models": {
                    "gpt-live": {
                        "id": "gpt-live",
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "limit": {"context": 123000, "output": 4567},
                    }
                },
            }
        },
    )

    limits = get_model_limits("codex:gpt-live")
    assert limits.context_length == 999
    assert limits.max_completion_tokens == 88


def _models_dev_payload(model_id: str) -> dict[str, object]:
    return {
        "openai": {
            "id": "openai",
            "models": {
                model_id: {
                    "id": model_id,
                    "modalities": {"input": ["text"], "output": ["text"]},
                    "limit": {"context": 1000, "output": 100},
                }
            },
        }
    }


def _refreshing_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config")
    )
    monkeypatch.setattr(model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True)


def test_refresh_models_dev_cache_publishes_new_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The merged registry is memoized per process, so a model that appears
    # after boot is only reachable if the refresh drops the derived caches.
    _refreshing_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        model_registry, "_fetch_models_dev", lambda: _models_dev_payload("gpt-first")
    )
    assert "openai:gpt-first" in model_registry.load_model_registry()

    monkeypatch.setattr(
        model_registry, "_fetch_models_dev", lambda: _models_dev_payload("gpt-second")
    )
    assert model_registry.refresh_models_dev_cache() is True

    registry = model_registry.load_model_registry()
    assert "openai:gpt-second" in registry
    assert "openai:gpt-first" not in registry


def test_refresh_models_dev_cache_keeps_caches_when_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refreshing_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        model_registry, "_fetch_models_dev", lambda: _models_dev_payload("gpt-first")
    )
    model_registry.load_model_registry()

    resets: list[bool] = []
    monkeypatch.setattr(
        model_registry, "reset_catalog_caches", lambda: resets.append(True)
    )
    cache_path = model_registry._models_dev_cache_path()
    stale = time.time() - (2 * model_registry.MODELS_DEV_CACHE_TTL_SECONDS)
    os.utime(cache_path, (stale, stale))

    assert model_registry.refresh_models_dev_cache() is False
    assert resets == []
    # The mtime is the TTL clock: an identical payload still has to bump it,
    # or the next cold start refetches for nothing.
    assert cache_path.stat().st_mtime > stale


def test_refresh_models_dev_cache_respects_the_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refreshing_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        model_registry.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", False
    )
    fetches: list[bool] = []

    def _fetch() -> dict[str, object]:
        fetches.append(True)
        return _models_dev_payload("gpt-first")

    monkeypatch.setattr(model_registry, "_fetch_models_dev", _fetch)

    assert model_registry.refresh_models_dev_cache() is False
    assert fetches == []


def test_refresh_models_dev_cache_survives_a_failed_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refreshing_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        model_registry, "_fetch_models_dev", lambda: _models_dev_payload("gpt-first")
    )
    model_registry.load_model_registry()

    monkeypatch.setattr(model_registry, "_fetch_models_dev", lambda: None)
    assert model_registry.refresh_models_dev_cache() is False
    # A dead network must not empty the catalog the process is already serving.
    assert "openai:gpt-first" in model_registry.load_model_registry()
