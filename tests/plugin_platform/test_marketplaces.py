from __future__ import annotations

import pytest
from app.core.config import settings
from app.plugin_platform.marketplaces import (
    MarketplaceKind,
    add_marketplace,
    list_marketplaces,
    remove_marketplace,
    search_marketplace_plugins,
    sync_marketplace,
    validate_marketplace_url,
)


def test_marketplace_url_requires_public_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        validate_marketplace_url("http://plugins.example/registry.json")
    with pytest.raises(ValueError, match="public"):
        validate_marketplace_url("https://127.0.0.1/registry.json")
    with pytest.raises(ValueError, match="public"):
        validate_marketplace_url("https://localhost/registry.json")


def test_add_marketplace_persists_sources_separately_from_installs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    source = add_marketplace(
        kind=MarketplaceKind.agent_plugins,
        name="Community plugins",
        url="https://plugins.example/registry.json",
    )

    assert source.kind == MarketplaceKind.agent_plugins
    assert source.name == "Community plugins"
    assert source.url == "https://plugins.example/registry.json"
    assert list_marketplaces() == [source]
    assert (tmp_path / "data" / "agent-plugins" / "registry.json").exists() is False
    assert remove_marketplace(source.id).id == source.id
    assert list_marketplaces() == []


def test_sync_agent_plugins_registry_and_search_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    source = add_marketplace(
        kind=MarketplaceKind.agent_plugins,
        name="EvoFlux plugins",
        url="https://plugins.example/registry.json",
    )
    registry = {
        "version": 1,
        "plugins": [
            {
                "name": "research-skills",
                "version": "1.2.0",
                "description": "Research and source review skills",
                "categories": ["research"],
                "keywords": ["sources", "review"],
                "portable": True,
                "portableComponents": ["skills", "mcp"],
                "compatibleClients": ["evoflux", "claude"],
                "verification": {"state": "verified"},
                "artifact": {
                    "url": "https://plugins.example/research.evoplugin",
                    "sha256": "a" * 64,
                    "size": 256,
                },
            }
        ],
    }

    synced = sync_marketplace(source.id, fetcher=lambda _url: registry)
    results = search_marketplace_plugins("source review")

    assert synced.last_synced_at is not None
    assert len(results) == 1
    assert results[0].name == "research-skills"
    assert results[0].compatibility == "compatible"
    assert results[0].components == ["skills", "mcp"]
    assert results[0].categories == ["research"]
    assert results[0].keywords == ["sources", "review"]
    assert results[0].verification == "verified"


def test_sync_claude_marketplace_marks_component_compatibility_unknown(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    source = add_marketplace(
        kind=MarketplaceKind.claude_code,
        name="Claude official",
        url="https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
    )
    catalog = {
        "name": "claude-plugins-official",
        "plugins": [
            {
                "name": "agent-sdk-dev",
                "description": "Agent SDK development commands",
                "source": "./plugins/agent-sdk-dev",
            },
            {
                "name": "example-remote",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/example/plugins.git",
                    "path": "plugins/example-remote",
                    "sha": "b" * 40,
                },
            },
        ],
    }

    sync_marketplace(source.id, fetcher=lambda _url: catalog)
    results = search_marketplace_plugins("", marketplace_id=source.id)

    assert [item.name for item in results] == ["agent-sdk-dev", "example-remote"]
    assert all(item.compatibility == "unknown" for item in results)
    assert all(item.installable for item in results)
    assert results[0].source_type == "relative"
    assert results[1].source_type == "git-subdir"


def test_unsupported_claude_source_is_not_installable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    source = add_marketplace(
        kind=MarketplaceKind.claude_code,
        name="Claude marketplace",
        url="https://plugins.example/.claude-plugin/marketplace.json",
    )
    catalog = {
        "plugins": [
            {
                "name": "generated-plugin",
                "source": {"source": "command", "command": "curl | sh"},
            }
        ]
    }

    sync_marketplace(source.id, fetcher=lambda _url: catalog)
    result = search_marketplace_plugins("", marketplace_id=source.id)[0]

    assert result.compatibility == "unsupported"
    assert result.installable is False


def test_duplicate_marketplace_url_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    add_marketplace(
        kind=MarketplaceKind.agent_plugins,
        name="First",
        url="https://plugins.example/registry.json",
    )

    with pytest.raises(ValueError, match="already added"):
        add_marketplace(
            kind=MarketplaceKind.agent_plugins,
            name="Duplicate",
            url="https://plugins.example/registry.json",
        )


def test_unknown_marketplace_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        MarketplaceKind("npm")
