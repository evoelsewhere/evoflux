"""Generic / ad-hoc file importer.

Handles loose files that don't come from a specific tool:

- ``mcp.json`` (any format) → MCP server merge
- ``SKILL.md`` with YAML frontmatter → Skill installation
- ``plugin.json`` + directory → Plugin installation
- Agent ``.md`` with YAML frontmatter → Agent config
- ``.env`` with ``*_API_KEY`` → Credential import
- Markdown knowledge files → Wiki knowledge base
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.importers.base import ImportBundle, ImportItem, utcnow


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from body text."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    fm_text = match.group(1)
    body = match.group(2)

    result: dict[str, str] = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")

    return result, body


def _parse_mcp_json(path: Path) -> list[ImportItem]:
    """Parse a standalone mcp.json file."""
    items: list[ImportItem] = []
    now = utcnow()

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
                source="generic",
                source_id=f"mcp:{name}",
                data={"name": name, "server": config, "created_at": now.isoformat()},
                label=f"MCP: {name}",
            )
        )

    return items


def _parse_skill_md(path: Path) -> list[ImportItem]:
    """Parse a SKILL.md file into a skill ImportItem."""
    items: list[ImportItem] = []
    now = utcnow()

    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return items

    if not content:
        return items

    frontmatter, body = _split_frontmatter(content)
    name = frontmatter.get(
        "name", path.parent.name if path.name == "SKILL.md" else path.stem
    )
    description = frontmatter.get("description", "")

    items.append(
        ImportItem(
            kind="skill",
            source="generic",
            source_id=f"skill:{name}",
            data={
                "name": name,
                "description": description or f"Imported skill: {name}",
                "body": body,
                "created_at": now.isoformat(),
            },
            label=f"Skill: {name}",
        )
    )

    return items


def _parse_agent_md(path: Path) -> list[ImportItem]:
    """Parse an agent .md file with YAML frontmatter."""
    items: list[ImportItem] = []
    now = utcnow()

    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return items

    if not content:
        return items

    frontmatter, body = _split_frontmatter(content)
    name = frontmatter.get("name", path.stem)
    description = frontmatter.get("description", "")

    items.append(
        ImportItem(
            kind="agent",
            source="generic",
            source_id=f"agent:{name}",
            data={
                "name": name,
                "description": description or f"Imported agent: {name}",
                "instructions": body,
                "created_at": now.isoformat(),
            },
            label=f"Agent: {name}",
        )
    )

    return items


def _parse_env_file(path: Path) -> list[ImportItem]:
    """Parse a .env file for credential import."""
    items: list[ImportItem] = []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return items

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # Only import keys that look like API keys or tokens
        if any(
            pattern in key.upper()
            for pattern in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
        ):
            items.append(
                ImportItem(
                    kind="setting",
                    source="generic",
                    source_id=f"credential:{key}",
                    data={"key": key, "value": value},
                    label=f"Credential: {key}",
                )
            )

    return items


def _parse_markdown_knowledge(path: Path) -> list[ImportItem]:
    """Parse a plain Markdown file as a knowledge ImportItem."""
    items: list[ImportItem] = []
    now = utcnow()

    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return items

    if not content:
        return items

    # Use first heading as title
    title = path.stem
    for line in content.split("\n"):
        if line.startswith("#"):
            title = line.lstrip("# ").strip()
            break

    items.append(
        ImportItem(
            kind="knowledge",
            source="generic",
            source_id=f"knowledge:{path.name}",
            data={
                "filename": path.name,
                "content": content,
                "created_at": now.isoformat(),
            },
            label=f"Knowledge: {title}",
        )
    )

    return items


def parse_generic_export(path: Path) -> ImportBundle:
    """Parse a generic file or directory of loose files.

    Auto-detects the file type from content and structure.
    """
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    if path.is_file():
        items = _parse_single_file(path)
        all_items.extend(items)
    elif path.is_dir():
        all_items.extend(_parse_directory(path))
    else:
        warnings.append(f"Path not found: {path}")

    if not all_items:
        warnings.append("No importable items found")

    return ImportBundle(
        source="generic",
        detected_format="generic",
        items=all_items,
        warnings=warnings,
        metadata={"total_items": len(all_items), "source_path": str(path)},
    )


def _parse_single_file(path: Path) -> list[ImportItem]:
    """Route a single file to the appropriate parser."""
    name = path.name.lower()

    if name == "mcp.json" or name.endswith(".mcp.json"):
        return _parse_mcp_json(path)
    if name == "skill.md":
        return _parse_skill_md(path)
    if name.endswith(".env"):
        return _parse_env_file(path)
    if name.endswith(".md"):
        # Could be an agent or knowledge file — check frontmatter
        try:
            head = path.read_text(encoding="utf-8")[:500]
        except OSError:
            return []
        if head.lstrip().startswith("---"):
            frontmatter, _ = _split_frontmatter(head)
            if "name" in frontmatter or "instructions" in frontmatter:
                return _parse_agent_md(path)
        return _parse_markdown_knowledge(path)

    return []


def _parse_directory(path: Path) -> list[ImportItem]:
    """Parse a directory of loose files."""
    items: list[ImportItem] = []

    # Check for plugin.json
    if (path / "plugin.json").is_file():
        items.extend(_parse_plugin_dir(path))
        return items

    # Otherwise scan for known file types
    for child in sorted(path.iterdir()):
        if child.is_file():
            items.extend(_parse_single_file(child))
        elif child.is_dir():
            # Recurse one level for skill directories
            if (child / "SKILL.md").is_file():
                items.extend(_parse_skill_md(child / "SKILL.md"))

    return items


def _parse_plugin_dir(path: Path) -> list[ImportItem]:
    """Parse a plugin directory with plugin.json."""
    items: list[ImportItem] = []
    now = utcnow()

    manifest_path = path / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    name = manifest.get("name", path.name)

    items.append(
        ImportItem(
            kind="plugin",
            source="generic",
            source_id=f"plugin:{name}",
            data={
                "name": name,
                "manifest": manifest,
                "path": str(path),
                "created_at": now.isoformat(),
            },
            label=f"Plugin: {name}",
        )
    )

    return items
