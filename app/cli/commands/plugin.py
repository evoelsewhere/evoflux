"""Portable Agent Plugins lifecycle commands."""

from __future__ import annotations

import argparse
import json
import sys

from app.plugin_platform import (
    create_plugin,
    get_installation,
    inspect_plugin,
    install_plugin,
    link_plugin,
    list_installations,
    pack_plugin,
    set_enabled,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.registry import plugin_data_root


def _print(value) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_plugin(args: argparse.Namespace) -> None:
    try:
        action = args.plugin_action
        if action == "list":
            _print([item.model_dump(mode="json") for item in list_installations()])
            return
        if action == "inspect":
            _print(inspect_plugin(args.path))
            return
        if action in {"install", "link"}:
            operation = link_plugin if action == "link" else install_plugin
            _print(operation(args.path, enabled=not args.disabled))
            return
        if action in {"enable", "disable"}:
            _print(set_enabled(args.installation_id, action == "enable"))
            return
        if action == "uninstall":
            _print(
                uninstall_plugin(
                    args.installation_id,
                    remove_data=args.remove_data,
                )
            )
            return
        if action == "update":
            _print(update_plugin(args.installation_id, args.path))
            return
        if action == "create":
            path = create_plugin(
                args.destination,
                name=args.name,
                description=args.description,
                skill_name=args.skill,
            )
            _print({"path": str(path)})
            return
        if action == "pack":
            _print({"path": str(pack_plugin(args.path, args.output))})
            return
        if action == "show":
            installation = get_installation(args.installation_id)
            if installation is None:
                raise KeyError(args.installation_id)
            _print(
                {
                    "installation": installation.model_dump(mode="json"),
                    "inspection": inspect_plugin(
                        installation.root,
                        data_root=plugin_data_root(installation.id),
                    ).model_dump(mode="json", by_alias=True),
                }
            )
            return
        raise ValueError("A plugin action is required. Run 'evoflux plugin --help'.")
    except (OSError, ValueError, KeyError) as exc:
        print(f"Plugin error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def add_plugin_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "plugin",
        help="Create, validate, import, and manage Agent Plugins",
    )
    actions = parser.add_subparsers(dest="plugin_action", metavar="action")

    actions.add_parser("list", help="List installed and linked plugins")

    inspect_parser = actions.add_parser("inspect", help="Validate a plugin directory")
    inspect_parser.add_argument("path")

    for name in ("install", "link"):
        operation = actions.add_parser(
            name,
            help=(
                "Copy a package into EvoFlux"
                if name == "install"
                else "Link a development directory"
            ),
        )
        operation.add_argument("path")
        operation.add_argument("--disabled", action="store_true")

    for name in ("show", "enable", "disable"):
        operation = actions.add_parser(name, help=f"{name.title()} one plugin")
        operation.add_argument("installation_id")

    uninstall = actions.add_parser("uninstall", help="Remove one installation")
    uninstall.add_argument("installation_id")
    uninstall.add_argument(
        "--remove-data",
        action="store_true",
        help="Also remove persistent PLUGIN_DATA",
    )

    update = actions.add_parser(
        "update",
        help="Replace a managed package while preserving its ID and data",
    )
    update.add_argument("installation_id")
    update.add_argument("path")

    create = actions.add_parser("create", help="Scaffold a portable plugin")
    create.add_argument("destination")
    create.add_argument("--name", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--skill")

    pack = actions.add_parser("pack", help="Build a deterministic .evoplugin archive")
    pack.add_argument("path")
    pack.add_argument("--output")

    parser.set_defaults(func=cmd_plugin)


__all__ = ["add_plugin_subparser", "cmd_plugin"]
