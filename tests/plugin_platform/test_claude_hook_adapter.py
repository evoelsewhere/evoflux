from __future__ import annotations

import json
from pathlib import Path

from app.plugin_platform.extensions import HOOKS_EXTENSION
from app.plugin_platform.marketplaces import normalize_claude_plugin_directory


def _write_superpowers(root: Path, *, command: str | None = None) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "superpowers", "version": "6.4.1"}),
        encoding="utf-8",
    )
    (root / "hooks").mkdir()
    (root / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command
                                    or '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start',
                                    "shell": "bash",
                                    "async": False,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "hooks" / "run-hook.cmd").write_text(
        "THIS COMMAND MUST NEVER BE COPIED OR EXECUTED", encoding="utf-8"
    )
    skill = root / "skills" / "using-superpowers" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: using-superpowers\ndescription: Apply the workflow\n---\n\n"
        "Use the verified workflow steps.\n",
        encoding="utf-8",
    )
    return root


def test_normalizes_only_superpowers_session_start_to_static_context(
    tmp_path: Path,
) -> None:
    source = _write_superpowers(tmp_path / "source")

    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
        version="6.4.1",
    )

    manifest = json.loads((normalized.root / "plugin.json").read_text())
    hooks = manifest["extensions"][HOOKS_EXTENSION]["hooks"]
    assert normalized.supported_components == ["hooks", "skills"]
    assert normalized.unsupported_components == []
    assert len(hooks) == 1
    assert hooks[0]["execution_kind"] == "static_context"
    assert hooks[0]["command"] == ["./skills/using-superpowers/SKILL.md"]
    assert hooks[0]["event"] == "session.start"
    assert hooks[0]["output_fields"] == ["context"]
    assert (normalized.root / "skills/using-superpowers/SKILL.md").is_file()
    assert not (normalized.root / "hooks").exists()


def test_does_not_adapt_lookalike_shell_command(tmp_path: Path) -> None:
    source = _write_superpowers(
        tmp_path / "source",
        command='"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start && evil',
    )

    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
    )

    manifest = json.loads((normalized.root / "plugin.json").read_text())
    assert "hooks" not in manifest.get("extensions", {})
    assert normalized.unsupported_components == ["hooks"]
    assert normalized.warnings


def test_does_not_adapt_additional_claude_events(tmp_path: Path) -> None:
    source = _write_superpowers(tmp_path / "source")
    manifest_path = source / "hooks" / "hooks.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hooks"]["UserPromptSubmit"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
    )

    package_manifest = json.loads((normalized.root / "plugin.json").read_text())
    assert "hooks" not in package_manifest.get("extensions", {})
    assert normalized.unsupported_components == ["hooks"]


def test_oversized_superpowers_context_stays_a_skill_but_not_a_hook(
    tmp_path: Path,
) -> None:
    source = _write_superpowers(tmp_path / "source")
    skill = source / "skills" / "using-superpowers" / "SKILL.md"
    skill.write_text(
        "---\nname: using-superpowers\ndescription: Apply the workflow\n---\n\n"
        + ("workflow step\n" * 6000),
        encoding="utf-8",
    )

    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
    )

    package_manifest = json.loads((normalized.root / "plugin.json").read_text())
    assert "hooks" not in package_manifest.get("extensions", {})
    assert normalized.supported_components == ["skills"]
    assert normalized.unsupported_components == ["hooks"]
    assert any("bounded context size" in warning for warning in normalized.warnings)
    assert (normalized.root / "skills/using-superpowers/SKILL.md").is_file()
