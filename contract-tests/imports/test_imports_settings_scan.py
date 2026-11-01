"""``/api/import`` contract: auto-sync settings and the local scan."""

from __future__ import annotations

import yaml

from import_sources import (
    build_claude_code_dir,
    build_codex_dir,
    write,
    write_json,
)

DEFAULTS = {"enabled": False, "scan_interval_seconds": 300, "notify_new_items": True}


# ── auto-sync ──────────────────────────────────────────────────────────────


def test_auto_sync_defaults(client, config_dir) -> None:
    # The seeded settings.yaml has no import_auto_sync section.
    response = client.get("/api/import/auto-sync")
    assert response.status_code == 200
    assert response.json() == DEFAULTS
    (config_dir / "settings.yaml").unlink()
    assert client.get("/api/import/auto-sync").json() == DEFAULTS


def test_auto_sync_put_rewrites_whole_settings_file(
    client, config_dir, scrub, snapshot
) -> None:
    (config_dir / "settings.yaml").unlink()
    response = client.put("/api/import/auto-sync", json={"notify_new_items": False})
    assert response.json() == {**DEFAULTS, "notify_new_items": False}
    saved = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    snapshot.check("auto_sync_saved_settings.json", scrub(saved))


def test_auto_sync_put_merges_and_persists(client, config_dir) -> None:
    response = client.put("/api/import/auto-sync", json={"enabled": True})
    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, "enabled": True}
    response = client.put(
        "/api/import/auto-sync",
        json={"scan_interval_seconds": 30, "notify_new_items": None},
    )
    expected = {"enabled": True, "scan_interval_seconds": 30, "notify_new_items": True}
    assert response.json() == expected
    assert client.get("/api/import/auto-sync").json() == expected
    saved = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert saved["import_auto_sync"] == expected


def test_auto_sync_put_keeps_other_settings(client, config_dir) -> None:
    write(
        config_dir / "settings.yaml",
        "import_auto_sync:\n  enabled: true\n  scan_interval_seconds: 120\n"
        "title_generation:\n  enabled: false\n",
    )
    assert client.get("/api/import/auto-sync").json() == {
        **DEFAULTS,
        "enabled": True,
        "scan_interval_seconds": 120,
    }
    response = client.put("/api/import/auto-sync", json={})
    assert response.json() == {
        **DEFAULTS,
        "enabled": True,
        "scan_interval_seconds": 120,
    }
    saved = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert saved["title_generation"]["enabled"] is False


def test_auto_sync_invalid_file_value_falls_back(client, config_dir) -> None:
    write(
        config_dir / "settings.yaml",
        "import_auto_sync:\n  enabled: true\n  scan_interval_seconds: 5\n",
    )
    assert client.get("/api/import/auto-sync").json() == {**DEFAULTS, "enabled": True}


def test_auto_sync_put_validation_writes_nothing(client, config_dir, snapshot) -> None:
    before = (config_dir / "settings.yaml").read_bytes()
    errors = {}
    for name, body in {
        "too_small": {"scan_interval_seconds": 29},
        "string_bool": {"enabled": "yes"},
        "int_bool": {"notify_new_items": 1},
        "float_interval": {"scan_interval_seconds": 60.0},
        "string_interval": {"scan_interval_seconds": "60"},
        "not_object": [1],
    }.items():
        response = client.put("/api/import/auto-sync", json=body)
        assert response.status_code == 422, name
        errors[name] = response.json()
    snapshot.check("auto_sync_422.json", errors)
    assert (config_dir / "settings.yaml").read_bytes() == before
    assert client.get("/api/import/auto-sync").json() == DEFAULTS


# ── scan ───────────────────────────────────────────────────────────────────


def test_scan_empty_machine(client) -> None:
    response = client.get("/api/import/scan")
    assert response.status_code == 200
    assert response.json() == {"discovered": []}


def test_scan_finds_each_source(client, tmp_path, home, scrub, snapshot) -> None:
    build_claude_code_dir(home)
    write_json(
        home / ".claude" / "plugins" / "installed_plugins.json",
        {"plugins": {"tools@market": [{"installPath": str(tmp_path / "plug")}]}},
    )
    write(tmp_path / "plug" / "skills" / "fmt" / "SKILL.md", "---\nname: fmt\n---\nx")
    build_codex_dir(home)
    write(home / "Downloads" / "claude-export-2026.json", "[]")
    write(home / "Desktop" / "chatgpt-export.zip", "zip")
    cwd = tmp_path / "cwd"
    write(cwd / ".cursor" / "rules" / "a.mdc", "rule")
    write_json(cwd / ".cursor" / "mcp.json", {})
    write(cwd / ".cursorrules", "rules")
    write(cwd / "CLAUDE.md", "x")
    write(cwd / ".windsurfrules", "x")
    write(home / "projects" / "app" / ".codex" / "keep", "")
    write(home / "projects" / "app" / "CLAUDE.md", "x")
    response = client.get("/api/import/scan")
    assert response.status_code == 200
    snapshot.check("scan.json", scrub(response.json()))
