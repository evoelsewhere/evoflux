"""Cursor editor directory parser.

Handles the ``.cursor/`` directory and ``.cursorrules`` file.

Expected layout::

    .cursor/
    ├── rules/
    │   └── *.mdc              # rule files (Markdown with metadata)
    ├── settings.json          # editor/model preferences
    └── mcp.json               # MCP server config

    .cursorrules               # workspace-level rules (legacy)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.importers.base import ImportBundle, ImportItem, utcnow


def _parse_rules(rules_dir: Path) -> list[ImportItem]:
    """Parse ``.cursor/rules/*.mdc`` into skill ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not rules_dir.is_dir():
        return items

    for rule_file in sorted(rules_dir.glob("*.mdc")):
        try:
            content = rule_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if not content:
            continue

        # .mdc files may have YAML frontmatter
        name = rule_file.stem
        description = ""
        body = content

        frontmatter, body_text = _split_frontmatter(content)
        if frontmatter:
            description = frontmatter.get("description", "")
            name = frontmatter.get("name", name)
            body = body_text

        if not description:
            # Use first line as description
            first_line = body.split("\n")[0].strip().lstrip("# ").strip()
            description = first_line[:120] if first_line else f"Cursor rule: {name}"

        items.append(
            ImportItem(
                kind="skill",
                source="cursor",
                source_id=f"rule:{rule_file.stem}",
                data={
                    "name": name,
                    "description": description,
                    "body": body,
                    "created_at": now.isoformat(),
                },
                label=f"Skill: {name}",
            )
        )

    return items


def _parse_cursorrules(path: Path) -> list[ImportItem]:
    """Parse ``.cursorrules`` into an agent ImportItem."""
    items: list[ImportItem] = []
    now = utcnow()

    if not path.is_file():
        return items

    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return items

    if content:
        items.append(
            ImportItem(
                kind="agent",
                source="cursor",
                source_id="cursorrules",
                data={
                    "name": "cursor-workspace",
                    "description": "Imported from Cursor workspace rules",
                    "instructions": content,
                    "created_at": now.isoformat(),
                },
                label="Agent: Cursor workspace rules",
            )
        )

    return items


def _parse_mcp_config(path: Path) -> list[ImportItem]:
    """Parse ``.cursor/mcp.json`` into MCP server ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not path.is_file():
        return items

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    servers = data.get("mcpServers", data.get("servers", {}))
    if not isinstance(servers, dict):
        return items

    for name, config in servers.items():
        if not isinstance(config, dict):
            continue
        items.append(
            ImportItem(
                kind="mcp_server",
                source="cursor",
                source_id=f"mcp:{name}",
                data={"name": name, "server": config, "created_at": now.isoformat()},
                label=f"MCP: {name}",
            )
        )

    return items


def _parse_settings(path: Path) -> list[ImportItem]:
    """Parse ``.cursor/settings.json`` for importable settings."""
    items: list[ImportItem] = []

    if not path.is_file():
        return items

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    if isinstance(data, dict) and data:
        items.append(
            ImportItem(
                kind="setting",
                source="cursor",
                source_id="settings",
                data={"settings": data},
                label="Cursor settings",
            )
        )

    return items


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from body text."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    fm_text = match.group(1)
    body = match.group(2)

    # Simple YAML key-value parser (no full YAML library needed)
    result: dict[str, str] = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")

    return result, body


def parse_cursor_export(path: Path) -> ImportBundle:
    """Parse a Cursor workspace directory.

    Accepts either the ``.cursor/`` directory itself or the parent workspace
    directory containing ``.cursor/`` and ``.cursorrules``.
    """
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    # If path is the workspace root (not .cursor/ itself), look inside
    cursor_dir = path
    if path.is_dir() and path.name != ".cursor":
        cursor_dir = path / ".cursor"

    if cursor_dir.is_dir():
        all_items.extend(_parse_rules(cursor_dir / "rules"))
        all_items.extend(_parse_mcp_config(cursor_dir / "mcp.json"))
        all_items.extend(_parse_settings(cursor_dir / "settings.json"))

    # .cursorrules lives at workspace root
    cursorrules_path = (
        path / ".cursorrules"
        if path.name != ".cursor"
        else path.parent / ".cursorrules"
    )
    all_items.extend(_parse_cursorrules(cursorrules_path))

    if not all_items:
        warnings.append("No importable Cursor data found")

    return ImportBundle(
        source="cursor",
        detected_format="cursor",
        items=all_items,
        warnings=warnings,
        metadata={"total_items": len(all_items), "source_path": str(path)},
    )
