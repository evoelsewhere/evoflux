from __future__ import annotations

import json

import pytest

from app.plugin_platform import registry


def _legacy_installation(*, source_type: str = "installed") -> dict[str, object]:
    return {
        "id": "0123456789abcdef0123456789abcdef",
        "name": f"legacy-{source_type}-plugin",
        "version": "0.1.0",
        "description": "A legacy plugin",
        "root": "/tmp/legacy-plugin",
        "source_type": source_type,
        "source_ref": "/tmp/legacy-plugin.evoplugin",
        "content_sha256": "a" * 64,
        "enabled": True,
        "installed_at": "2026-09-21T00:00:00+00:00",
        "updated_at": "2026-09-21T00:00:00+00:00",
    }


def test_v1_registry_migrates_metadata_defaults(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plugins.json"
    path.write_text(
        json.dumps({"version": 1, "installations": [_legacy_installation()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "registry_path", lambda: path)

    document = registry._read_document(strict=True)

    assert document.version == 2
    installation = document.installations[0]
    assert installation.provenance.verification_state == "legacy"
    assert installation.connection_profile_ids == []
    assert installation.version_history == []

    registry._write_document(document)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["version"] == 2
    assert persisted["installations"][0]["provenance"]["verification_state"] == "legacy"


def test_v1_registry_preserves_legacy_linked_plugins(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plugins.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "installations": [_legacy_installation(source_type="linked")],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "registry_path", lambda: path)

    installation = registry._read_document(strict=True).installations[0]

    assert installation.source_type == "linked"
    assert installation.source_ref == "/tmp/legacy-plugin.evoplugin"
    assert installation.provenance.verification_state == "legacy"


def test_registry_parse_failure_is_safe(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plugins.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(registry, "registry_path", lambda: path)

    assert registry._read_document().installations == []
    with pytest.raises(ValueError):
        registry._read_document(strict=True)


def test_registry_atomic_write_failure_preserves_previous_document(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "plugins.json"
    path.write_text('{"version": 2, "installations": []}', encoding="utf-8")
    monkeypatch.setattr(registry, "registry_path", lambda: path)
    original_replace = registry.os.replace

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(registry.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        registry._write_document(registry.PluginRegistryDocument())

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 2,
        "installations": [],
    }
    monkeypatch.setattr(registry.os, "replace", original_replace)
    assert not list(tmp_path.glob(".plugins.json.*.tmp"))


def test_new_installation_metadata_round_trips(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plugins.json"
    monkeypatch.setattr(registry, "registry_path", lambda: path)
    document = registry.PluginRegistryDocument()

    assert document.version == 2
    registry._write_document(document)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == {"installations": [], "version": 2}
