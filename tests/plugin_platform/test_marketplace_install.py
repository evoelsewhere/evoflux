from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.plugin_platform import marketplaces
from app.plugin_platform.marketplaces import (
    MarketplaceKind,
    add_marketplace,
    install_marketplace_preview,
    normalize_claude_plugin_directory,
    prepare_marketplace_plugin,
    sync_marketplace,
)

_AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def _write_agent_plugin(root: Path, *, name: str = "source-skill") -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": _AGENT_PLUGIN_SCHEMA,
                "name": name,
                "version": "1.0.0",
                "description": "A marketplace skill package",
                "compatibility": {
                    "portableComponents": ["skills"],
                    "compatibleClients": ["evoflux"],
                    "hostCapabilities": [],
                },
            }
        ),
        encoding="utf-8",
    )
    skill = root / "skills" / "source-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: source-skill\ndescription: Research skill\n---\n\nResearch carefully.\n",
        encoding="utf-8",
    )
    return root


def test_prepare_and_install_registry_artifact_verifies_digest_and_stays_disabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    package = _write_agent_plugin(tmp_path / "package")
    archive = tmp_path / "plugin.evoplugin"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in package.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(package).as_posix())
    artifact = archive.read_bytes()
    source = add_marketplace(
        kind=MarketplaceKind.agent_plugins,
        name="Community",
        url="https://plugins.example/registry.json",
    )
    sync_marketplace(
        source.id,
        fetcher=lambda _url: {
            "version": 1,
            "plugins": [
                {
                    "name": "source-skill",
                    "version": "1.0.0",
                    "description": "A marketplace skill package",
                    "portable": True,
                    "portableComponents": ["skills"],
                    "compatibleClients": ["evoflux"],
                    "artifact": {
                        "url": "https://plugins.example/source-skill.evoplugin",
                        "sha256": hashlib.sha256(artifact).hexdigest(),
                        "size": len(artifact),
                    },
                }
            ],
        },
    )

    fetch_calls: list[tuple[str, int]] = []

    def fetch_artifact(url: str, *, limit: int) -> bytes:
        fetch_calls.append((url, limit))
        return artifact

    monkeypatch.setattr(marketplaces, "_fetch_bytes", fetch_artifact)
    preview = prepare_marketplace_plugin(source.id, "source-skill")
    installed = install_marketplace_preview(preview.preview_id)

    assert preview.plugin.compatibility == "compatible"
    assert preview.supported_components == ["skills"]
    assert fetch_calls == [
        (
            "https://plugins.example/source-skill.evoplugin",
            marketplaces._MAX_REMOTE_PACKAGE_BYTES,
        )
    ]
    assert installed.name == "source-skill"
    assert installed.enabled is False
    assert installed.source_ref.startswith("marketplace:")


def test_prepare_rejects_registry_digest_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    source = add_marketplace(
        kind=MarketplaceKind.agent_plugins,
        name="Community",
        url="https://plugins.example/registry.json",
    )
    sync_marketplace(
        source.id,
        fetcher=lambda _url: {
            "version": 1,
            "plugins": [
                {
                    "name": "source-skill",
                    "version": "1.0.0",
                    "portable": True,
                    "portableComponents": ["skills"],
                    "compatibleClients": ["evoflux"],
                    "artifact": {
                        "url": "https://plugins.example/source-skill.evoplugin",
                        "sha256": "d" * 64,
                        "size": 4,
                    },
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="digest"):
        prepare_marketplace_plugin(
            source.id,
            "source-skill",
            byte_fetcher=lambda _url, _limit: b"bad!",
        )


def test_claude_normalizer_keeps_skills_and_mcp_and_reports_other_components(
    tmp_path,
) -> None:
    source = tmp_path / "claude-plugin"
    (source / ".claude-plugin").mkdir(parents=True)
    (source / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "official-skill", "version": "1.2.0"}),
        encoding="utf-8",
    )
    skill = source / "skills" / "official-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: official-skill\ndescription: An official skill\n---\n\nDo the task.\n",
        encoding="utf-8",
    )
    (source / "agents").mkdir()
    (source / "agents" / "reviewer.md").write_text("# Reviewer\n", encoding="utf-8")
    (source / "commands").mkdir()
    (source / "commands" / "review.md").write_text("# Review\n", encoding="utf-8")
    (source / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "remote": {
                        "type": "http",
                        "url": "https://mcp.example/tools",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="official-skill",
        description="Official compatible parts",
        version="1.2.0",
    )

    assert result.supported_components == ["mcp", "skills"]
    assert result.unsupported_components == ["agents", "commands"]
    normalized_mcp = json.loads((result.root / "mcp.json").read_text(encoding="utf-8"))
    assert (
        normalized_mcp["$schema"]
        == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    )
    assert set(normalized_mcp) == {"$schema", "mcpServers"}
    assert normalized_mcp["mcpServers"]["remote"]["type"] == "streamable-http"
    from app.plugin_platform.validator import inspect_plugin

    assert inspect_plugin(result.root).valid
    assert (result.root / "skills" / "official-skill" / "SKILL.md").is_file()


def test_marketplace_partial_install_requires_explicit_consent(
    tmp_path, monkeypatch
) -> None:
    preview_id = "a" * 32
    content_sha256 = "b" * 64
    state = SimpleNamespace(
        source_id="0123456789abcdef",
        source_name="Test marketplace",
        plugin_name="research-skills",
        source_ref="main",
        root=tmp_path / "preview" / "plugin",
        content_sha256=content_sha256,
        expires_at=10**12,
        supported_components=["skills"],
        unsupported_components=["hooks"],
    )
    state.root.mkdir(parents=True)
    installed = object()
    install_calls: list[bool] = []
    origin_calls: list[dict[str, str | None]] = []
    monkeypatch.setitem(marketplaces._PREVIEWS, preview_id, state)
    monkeypatch.setattr(marketplaces, "_clean_expired_previews", lambda: None)
    monkeypatch.setattr(
        marketplaces,
        "inspect_plugin",
        lambda root: SimpleNamespace(
            valid=True, content_sha256=content_sha256, diagnostics=[]
        ),
    )
    monkeypatch.setattr(
        marketplaces,
        "install_plugin",
        lambda root, *, enabled, source_ref, origin: (
            install_calls.append(enabled) or origin_calls.append(origin) or installed
        ),
    )
    monkeypatch.setattr(marketplaces.shutil, "rmtree", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="explicit consent"):
        install_marketplace_preview(preview_id)
    assert install_calls == []

    result = install_marketplace_preview(preview_id, allow_partial=True)

    assert result is installed
    assert install_calls == [False]
    assert origin_calls == [
        {
            "kind": "marketplace",
            "marketplace_id": "0123456789abcdef",
            "marketplace_name": "Test marketplace",
            "source_ref": "marketplace:0123456789abcdef/research-skills@main",
        }
    ]


def test_marketplace_install_blocks_component_errors_even_when_inspection_valid(
    tmp_path, monkeypatch
) -> None:
    preview_id = "c" * 32
    state = SimpleNamespace(
        source_id="0123456789abcdef",
        source_name="Test marketplace",
        plugin_name="research-skills",
        source_ref="main",
        root=tmp_path / "preview" / "plugin",
        content_sha256="b" * 64,
        expires_at=10**12,
        supported_components=["skills"],
        unsupported_components=[],
    )
    state.root.mkdir(parents=True)
    monkeypatch.setitem(marketplaces._PREVIEWS, preview_id, state)
    monkeypatch.setattr(marketplaces, "_clean_expired_previews", lambda: None)
    monkeypatch.setattr(
        marketplaces,
        "inspect_plugin",
        lambda root: SimpleNamespace(
            valid=True,
            content_sha256="b" * 64,
            diagnostics=[SimpleNamespace(severity="error")],
        ),
    )
    monkeypatch.setattr(
        marketplaces,
        "install_plugin",
        lambda *args, **kwargs: pytest.fail("invalid components must not install"),
    )

    with pytest.raises(ValueError, match="changed after compatibility review"):
        install_marketplace_preview(preview_id)
