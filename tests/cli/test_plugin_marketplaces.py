from __future__ import annotations

from types import SimpleNamespace

from app.cli.commands import plugin as plugin_command
from app.cli.main import build_parser


def test_plugin_marketplace_add_command_parses_source_details() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "marketplace",
            "add",
            "--type",
            "claude_code",
            "--name",
            "Claude official",
            "--url",
            "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
        ]
    )

    assert args.plugin_action == "marketplace"
    assert args.marketplace_action == "add"
    assert args.kind == "claude_code"
    assert args.name == "Claude official"


def test_plugin_marketplace_install_preserves_local_install_command_shape() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "install",
            "research-skills",
            "--marketplace",
            "0123456789abcdef",
            "--allow-partial",
        ]
    )

    assert args.plugin_action == "install"
    assert args.path == "research-skills"
    assert args.marketplace_id == "0123456789abcdef"
    assert args.allow_partial is True
    assert args.enabled is False


def test_plugin_search_command_accepts_source_filter() -> None:
    args = build_parser().parse_args(
        ["plugin", "search", "design", "--marketplace", "0123456789abcdef"]
    )

    assert args.plugin_action == "search"
    assert args.query == "design"
    assert args.marketplace_id == "0123456789abcdef"


def test_plugin_marketplace_install_forwards_explicit_partial_consent(
    monkeypatch, capsys
) -> None:
    preview = SimpleNamespace(preview_id="a" * 32, unsupported_components=["hooks"])
    installed = {"installation": {"enabled": False}}
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        plugin_command, "prepare_marketplace_plugin", lambda *_args: preview
    )
    monkeypatch.setattr(
        plugin_command,
        "install_marketplace_preview",
        lambda preview_id, *, allow_partial=False: (
            calls.append((preview_id, allow_partial)) or installed
        ),
    )
    args = build_parser().parse_args(
        [
            "plugin",
            "install",
            "research-skills",
            "--marketplace",
            "0123456789abcdef",
            "--allow-partial",
        ]
    )

    plugin_command.cmd_plugin(args)

    assert calls == [(preview.preview_id, True)]
    assert '"enabled": false' in capsys.readouterr().out
