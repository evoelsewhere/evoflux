"""Runtime-settings overlay tests for portable and read-only skill bundles."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from app.agent.skills import discovery
from app.agent.skills.discovery import discover_skill_records
from app.core.config import settings
from app.core.skill_settings import (
    SKILL_SETTINGS_FILENAME,
    write_skill_runtime_settings,
)


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test {name}.\n"
        "user-invocable: false\n---\nWorkflow body.\n"
    )
    (skill_dir / "agents" / "evoflux.yaml").write_text(
        "interface:\n"
        f'  display_name: "{name}"\n'
        '  short_description: "Test runtime settings"\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    (skill_dir / ".evoflux.json").write_text('{"modes":["work"]}\n')
    return skill_dir


def test_runtime_override_is_final_layer_and_content_digest_invalidates_cache(
    tmp_path, monkeypatch
):
    skills_root = tmp_path / "skills"
    config_root = tmp_path / "config"
    skills_root.mkdir()
    skill_dir = _write_skill(skills_root, "research")
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    discovery.discover_skill_records_cached.cache_clear()
    config_root.mkdir()
    settings_path = config_root / SKILL_SETTINGS_FILENAME
    settings_path.write_text('{"version":1,"skills":{}}\n')
    settings_path.chmod(0o644)

    before_skill = (skill_dir / "SKILL.md").read_bytes()
    before_metadata = (skill_dir / "agents" / "evoflux.yaml").read_bytes()
    before_scope = (skill_dir / ".evoflux.json").read_bytes()
    inherited = discover_skill_records([skills_root])["research"]
    assert inherited.modes == ("work",)
    assert inherited.allow_implicit_invocation is False
    assert inherited.user_invocable is False

    write_skill_runtime_settings(
        inherited.settings_id,
        name=inherited.name,
        source=inherited.source,
        modes=["coding"],
        allow_implicit_invocation=False,
        user_invocable=True,
    )
    overridden = discover_skill_records([skills_root])["research"]
    assert overridden.modes == ("coding",)
    assert overridden.allow_implicit_invocation is False
    assert overridden.user_invocable is True
    assert overridden.settings_overridden is True
    assert (skill_dir / "SKILL.md").read_bytes() == before_skill
    assert (skill_dir / "agents" / "evoflux.yaml").read_bytes() == before_metadata
    assert (skill_dir / ".evoflux.json").read_bytes() == before_scope

    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    previous_stat = settings_path.stat()
    previous_bytes = settings_path.read_bytes()
    payload = json.loads(previous_bytes)
    entry = payload["skills"][inherited.settings_id]
    entry["allow_implicit_invocation"] = True
    entry["user_invocable"] = False
    replacement = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    assert len(replacement) == len(previous_bytes)
    settings_path.write_bytes(replacement)
    os.utime(
        settings_path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns),
    )

    # Same path, size, and mtime still reloads because the bounded content
    # digest participates in the discovery cache key.
    externally_changed = discover_skill_records([skills_root])["research"]
    assert externally_changed.allow_implicit_invocation is True
    assert externally_changed.user_invocable is False


def test_invalid_override_falls_back_with_diagnostic(tmp_path, monkeypatch):
    skills_root = tmp_path / "skills"
    config_root = tmp_path / "config"
    skills_root.mkdir()
    _write_skill(skills_root, "research")
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    discovery.discover_skill_records_cached.cache_clear()
    inherited = discover_skill_records([skills_root])["research"]

    config_root.mkdir()
    (config_root / SKILL_SETTINGS_FILENAME).write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    inherited.settings_id: {
                        "modes": ["unsupported"],
                        "allow_implicit_invocation": True,
                        "user_invocable": True,
                    }
                },
            }
        )
    )
    discovered = discover_skill_records([skills_root])["research"]

    assert discovered.modes == ("work",)
    assert discovered.allow_implicit_invocation is False
    assert discovered.user_invocable is False
    assert discovered.settings_overridden is False
    assert {item.code for item in discovered.diagnostics} >= {
        "invalid-runtime-settings"
    }


def test_runtime_finalizer_covers_early_invalid_record(tmp_path, monkeypatch):
    skills_root = tmp_path / "skills"
    config_root = tmp_path / "config"
    skills_root.mkdir()
    skill_dir = _write_skill(skills_root, "broken")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\ndescription: [invalid\n---\nBody.\n"
    )
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    discovery.discover_skill_records_cached.cache_clear()
    invalid = discover_skill_records([skills_root])["broken"]
    assert invalid.valid is False
    assert invalid.settings_editable is False

    write_skill_runtime_settings(
        invalid.settings_id,
        name=invalid.name,
        source=invalid.source,
        modes=["coding"],
        allow_implicit_invocation=False,
        user_invocable=False,
    )
    finalized = discover_skill_records([skills_root])["broken"]

    assert finalized.valid is False
    assert finalized.settings_editable is False
    assert finalized.settings_overridden is True
    assert finalized.modes == ("coding",)
    assert finalized.allow_implicit_invocation is False
    assert finalized.user_invocable is False


def test_discovery_snapshots_runtime_settings_once(tmp_path, monkeypatch):
    skills_root = tmp_path / "skills"
    config_root = tmp_path / "config"
    skills_root.mkdir()
    _write_skill(skills_root, "first")
    _write_skill(skills_root, "second")
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    discovery.discover_skill_records_cached.cache_clear()

    calls = 0
    original = discovery.read_skill_runtime_settings_snapshot

    def counted_snapshot():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        discovery, "read_skill_runtime_settings_snapshot", counted_snapshot
    )
    assert set(discover_skill_records([skills_root])) == {"first", "second"}
    assert calls == 1
