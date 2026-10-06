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
    list_effective_installations,
    pack_plugin,
    set_enabled,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.registry import plugin_data_root
from app.plugin_platform.marketplaces import (
    MarketplaceKind,
    add_marketplace,
    list_marketplaces,
    remove_marketplace,
    search_marketplace_plugins,
    sync_marketplace,
    install_marketplace_preview,
    prepare_marketplace_plugin,
)


def _print(value) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_plugin(args: argparse.Namespace) -> None:
    try:
        action = args.plugin_action
        if action == "marketplace":
            if args.marketplace_action == "add":
                source = add_marketplace(
                    kind=MarketplaceKind(args.kind),
                    name=args.name,
                    url=args.url,
                )
                _print(source)
                return
            if args.marketplace_action == "list":
                _print(list_marketplaces())
                return
            if args.marketplace_action == "sync":
                sources = (
                    [sync_marketplace(args.marketplace_id)]
                    if args.marketplace_id
                    else [sync_marketplace(item.id) for item in list_marketplaces()]
                )
                _print(sources)
                return
            if args.marketplace_action == "remove":
                _print(remove_marketplace(args.marketplace_id))
                return
        if action in {"search", "available"}:
            query = args.query if action == "search" else ""
            _print(
                search_marketplace_plugins(
                    query,
                    marketplace_id=getattr(args, "marketplace_id", None),
                )
            )
            return
        if action == "list":
            _print(
                [
                    item.model_dump(mode="json")
                    for item in list_effective_installations()
                ]
            )
            return
        if action == "inspect":
            _print(inspect_plugin(args.path))
            return
        if action in {"install", "link"}:
            if action == "install" and args.marketplace_id:
                if args.enabled:
                    raise ValueError(
                        "Marketplace plugins remain disabled until trust review; "
                        "enable them separately after installation."
                    )
                preview = prepare_marketplace_plugin(args.marketplace_id, args.path)
                if preview.unsupported_components and not args.allow_partial:
                    raise ValueError(
                        "Plugin includes unsupported components: "
                        + ", ".join(preview.unsupported_components)
                        + ". Re-run with --allow-partial to install only the listed supported components."
                    )
                _print(
                    install_marketplace_preview(
                        preview.preview_id,
                        allow_partial=args.allow_partial,
                    )
                )
                return
            operation = link_plugin if action == "link" else install_plugin
            _print(operation(args.path, enabled=args.enabled))
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

    marketplace = actions.add_parser(
        "marketplace", help="Add and synchronize plugin marketplaces"
    )
    marketplace_actions = marketplace.add_subparsers(
        dest="marketplace_action", metavar="marketplace-action", required=True
    )
    marketplace_add = marketplace_actions.add_parser(
        "add", help="Add a marketplace source"
    )
    marketplace_add.add_argument(
        "--type",
        dest="kind",
        choices=[kind.value for kind in MarketplaceKind],
        required=True,
    )
    marketplace_add.add_argument("--name", required=True)
    marketplace_add.add_argument("--url", required=True)
    marketplace_actions.add_parser("list", help="List configured marketplace sources")
    marketplace_sync = marketplace_actions.add_parser(
        "sync", help="Refresh catalog metadata"
    )
    marketplace_sync.add_argument("marketplace_id", nargs="?")
    marketplace_remove = marketplace_actions.add_parser(
        "remove", help="Remove a marketplace source"
    )
    marketplace_remove.add_argument("marketplace_id")

    search = actions.add_parser(
        "search", help="Search synchronized marketplace catalogs"
    )
    search.add_argument("query")
    search.add_argument("--marketplace", dest="marketplace_id")
    available = actions.add_parser(
        "available", help="List plugins in synchronized catalogs"
    )
    available.add_argument("--marketplace", dest="marketplace_id")

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
        if name == "install":
            operation.add_argument(
                "--marketplace",
                dest="marketplace_id",
                help="Install a plugin from a synchronized marketplace",
            )
            operation.add_argument(
                "--allow-partial",
                action="store_true",
                help="Confirm installation of supported components only",
            )
        enablement = operation.add_mutually_exclusive_group()
        enablement.add_argument(
            "--enabled",
            action="store_true",
            help="Enable immediately in non-interactive automation",
        )
        enablement.add_argument(
            "--disabled",
            action="store_false",
            dest="enabled",
            help="Install disabled (default; retained for compatibility)",
        )
        operation.set_defaults(enabled=False)

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
