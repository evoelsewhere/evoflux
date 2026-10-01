"""Claude Code CLI directory parser.

Handles the ``~/.claude/`` directory structure:

.. code-block:: text

    ~/.claude/
    ├── settings.json              # global settings, MCP servers
    ├── projects/
    │   └── <project-hash>/
    │       ├── settings.json      # project-level settings
    │       ├── sessions/
    │       │   └── <session-id>.jsonl   # session transcript
    │       └── CLAUDE.md          # project instructions
    ├── commands/                   # custom slash commands
    │   └── <name>.md
    └── .mcp.json                  # MCP server config
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.importers.base import ImportBundle, ImportItem, utcnow


# ── Session parsing (JSONL) ─────────────────────────────────────────────────


def _parse_session_jsonl(path: Path) -> dict[str, Any] | None:
    """Parse a Claude Code JSONL session file into session data.

    Each line is a JSON object representing a message or event.
    Returns a dict with ``title``, ``messages``, ``created_at``, or ``None``
    on failure.
    """
    messages: list[dict[str, Any]] = []
    created_at: datetime | None = None

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = _extract_message(entry)
                if msg:
                    if created_at is None:
                        created_at = _parse_iso(msg.get("created_at"))
                    messages.append(msg)
    except OSError:
        return None

    if not messages:
        return None

    # Derive title from first user message
    title = "Claude Code session"
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            title = content[:80].split("\n")[0].strip()
            if title:
                break

    now = utcnow()
    return {
        "title": title,
        "created_at": (created_at or now).isoformat(),
        "updated_at": now.isoformat(),
        "messages": messages,
        "mode": "work",
    }


def _extract_message(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a normalised message from a Claude Code JSONL entry.

    Handles multiple formats:
    - Claude Desktop: {"type":"queue-operation","operation":"enqueue","content":"..."}
    - Claude Desktop: {"type":"human","message":{"role":"human","content":"..."}}
    - Claude Code CLI: {"type":"message","role":"user","content":"..."}
    - Claude Code CLI: {"message":{"role":"assistant","content":[...]}}
    """
    entry_type = entry.get("type", "")

    # ── Claude Desktop queue-operation format ────────────────────────────
    if entry_type == "queue-operation":
        operation = entry.get("operation", "")
        if operation == "enqueue":
            content = entry.get("content", "")
            if content:
                return {
                    "role": "user",
                    "content": str(content),
                    "created_at": (utcnow()).isoformat(),
                }
        return None

    # ── Claude Desktop message types ────────────────────────────────────
    if entry_type in ("human", "user"):
        msg = entry.get("message", entry)
        content = _normalise_content(msg.get("content", ""))
        if content:
            timestamp = entry.get("timestamp")
            return {
                "role": "user",
                "content": content,
                "created_at": (_parse_iso(timestamp) or utcnow()).isoformat(),
            }
        return None

    if entry_type in ("assistant", "ai"):
        msg = entry.get("message", entry)
        content = _normalise_content(msg.get("content", ""))
        if content:
            timestamp = entry.get("timestamp")
            return {
                "role": "assistant",
                "content": content,
                "created_at": (_parse_iso(timestamp) or utcnow()).isoformat(),
            }
        return None

    if entry_type == "system":
        content = _normalise_content(entry.get("content", entry.get("message", "")))
        if content:
            return {
                "role": "system",
                "content": content,
                "created_at": (utcnow()).isoformat(),
            }
        return None

    # ── Claude Code CLI format ──────────────────────────────────────────
    role_raw = entry.get("role", "")
    content_raw = entry.get("content", "")

    # Handle nested message structure
    if "message" in entry and isinstance(entry["message"], dict):
        inner = entry["message"]
        role_raw = inner.get("role", role_raw)
        content_raw = inner.get("content", content_raw)

    if not role_raw:
        return None

    role = _normalise_role(role_raw)
    content = _normalise_content(content_raw)

    if not content:
        return None

    timestamp = entry.get("timestamp") or entry.get("created_at")
    created = _parse_iso(timestamp)

    return {
        "role": role,
        "content": content,
        "created_at": (created or utcnow()).isoformat(),
    }


def _normalise_role(role: str) -> str:
    mapping = {
        "human": "user",
        "user": "user",
        "assistant": "assistant",
        "ai": "assistant",
        "system": "system",
    }
    return mapping.get(role, role)


def _normalise_content(content: Any) -> str:
    """Normalise content to a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    name = block.get("name", "unknown")
                    parts.append(f"[Tool call: {name}]")
                elif btype == "tool_result":
                    parts.append("[Tool result]")
                else:
                    parts.append(f"[{btype}]")
        return "\n".join(parts)
    return str(content) if content else ""


# ── Project parsing ─────────────────────────────────────────────────────────


def _parse_projects(projects_dir: Path) -> list[ImportItem]:
    """Parse Claude Code projects into session and agent ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not projects_dir.is_dir():
        return items

    for project_path in projects_dir.iterdir():
        if not project_path.is_dir():
            continue

        project_name = project_path.name

        # Parse CLAUDE.md → agent config
        claude_md = project_path / "CLAUDE.md"
        if claude_md.is_file():
            try:
                instructions = claude_md.read_text(encoding="utf-8").strip()
            except OSError:
                instructions = ""
            if instructions:
                items.append(
                    ImportItem(
                        kind="agent",
                        source="claude_code",
                        source_id=f"project:{project_name}:claude_md",
                        data={
                            "name": _slugify(project_name),
                            "description": (
                                f"Imported from Claude Code project: {project_name}"
                            ),
                            "instructions": instructions,
                            "created_at": now.isoformat(),
                        },
                        label=f"Agent: {project_name}",
                    )
                )

        # Parse sessions/*.jsonl — check both sessions/ subdir and project root
        jsonl_files: list[Path] = []
        sessions_dir = project_path / "sessions"
        if sessions_dir.is_dir():
            jsonl_files.extend(sorted(sessions_dir.glob("*.jsonl")))
        # Claude Desktop stores JSONL directly in project dir
        jsonl_files.extend(sorted(project_path.glob("*.jsonl")))

        for session_file in jsonl_files:
            session_data = _parse_session_jsonl(session_file)
            if session_data:
                items.append(
                    ImportItem(
                        kind="session",
                        source="claude_code",
                        source_id=(
                            f"project:{project_name}:session:{session_file.stem}"
                        ),
                        data=session_data,
                        label=session_data["title"],
                    )
                )

    return items


# ── Commands parsing ────────────────────────────────────────────────────────


def _parse_commands(commands_dir: Path) -> list[ImportItem]:
    """Parse custom slash commands into skill ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not commands_dir.is_dir():
        return items

    for cmd_file in sorted(commands_dir.glob("*.md")):
        try:
            content = cmd_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if not content:
            continue

        name = cmd_file.stem
        # First line as description if it starts with #
        lines = content.split("\n")
        description = ""
        body = content
        if lines and lines[0].startswith("#"):
            description = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip()

        items.append(
            ImportItem(
                kind="skill",
                source="claude_code",
                source_id=f"command:{name}",
                data={
                    "name": name,
                    "description": description or f"Claude Code command: {name}",
                    "body": body,
                    "created_at": now.isoformat(),
                },
                label=f"Skill: {name}",
            )
        )

    return items


# ── MCP config parsing ──────────────────────────────────────────────────────


def _parse_mcp_config(mcp_path: Path) -> list[ImportItem]:
    """Parse .mcp.json into MCP server ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not mcp_path.is_file():
        return items

    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
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
                source="claude_code",
                source_id=f"mcp:{name}",
                data={
                    "name": name,
                    "server": config,
                    "created_at": now.isoformat(),
                },
                label=f"MCP: {name}",
            )
        )

    return items


# ── Settings parsing ────────────────────────────────────────────────────────


def _parse_settings(settings_path: Path) -> list[ImportItem]:
    """Parse settings.json for useful importable settings."""
    items: list[ImportItem] = []

    if not settings_path.is_file():
        return items

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    # Extract API keys (if present) — these go through credential import
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        value = data.get(key)
        if value:
            items.append(
                ImportItem(
                    kind="setting",
                    source="claude_code",
                    source_id=f"credential:{key}",
                    data={
                        "key": key,
                        "value": value,
                    },
                    label=f"Credential: {key}",
                )
            )

    return items


def _scan_skills_in_dir(skills_dir: Path, source_label: str) -> list[ImportItem]:
    """Scan a ``skills/`` directory for SKILL.md files and return ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    if not skills_dir.is_dir():
        return items

    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not content:
            continue

        frontmatter, body = _split_frontmatter(content)
        name = frontmatter.get("name", skill_dir.name)
        description = frontmatter.get("description", "")

        items.append(
            ImportItem(
                kind="skill",
                source="claude_code",
                source_id=f"{source_label}:skill:{name}",
                data={
                    "name": name,
                    "description": description or f"Skill from {source_label}",
                    "body": body,
                    "created_at": now.isoformat(),
                },
                label=f"Skill: {name}",
            )
        )

    return items


def _parse_plugin_skills(claude_dir: Path) -> list[ImportItem]:
    """Parse skills from installed plugins listed in ``installed_plugins.json``.

    For each plugin, resolves its ``installPath`` and scans
    ``skills/*/SKILL.md``.
    """
    items: list[ImportItem] = []

    installed_path = claude_dir / "plugins" / "installed_plugins.json"
    if not installed_path.is_file():
        return items

    try:
        data = json.loads(installed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    plugins_dict = data.get("plugins", {}) if isinstance(data, dict) else {}
    for plugin_key, installs in plugins_dict.items():
        if not isinstance(installs, list) or not installs:
            continue
        install = installs[0]
        install_path = install.get("installPath", "")
        if not install_path:
            continue
        plugin_dir = Path(install_path)
        items.extend(_scan_skills_in_dir(plugin_dir / "skills", plugin_key))

    return items


def _parse_standalone_plugins(claude_dir: Path) -> list[ImportItem]:
    """Scan any directory under ``~/.claude/`` that looks like a plugin.

    A directory is treated as a standalone plugin if it has a ``skills/``
    subdirectory or a ``plugin.json`` manifest.  This catches plugins
    installed outside ``installed_plugins.json`` (e.g. manually placed).
    """
    items: list[ImportItem] = []
    now = utcnow()
    seen_source_ids: set[str] = set()

    if not claude_dir.is_dir():
        return items

    for child in claude_dir.iterdir():
        if not child.is_dir():
            continue
        # Skip known non-plugin directories
        if child.name in (
            "projects",
            "plugins",
            "sessions",
            "commands",
            "browser",
            "cache",
            "plans",
        ):
            continue

        has_skills = (child / "skills").is_dir()
        has_manifest = (child / "plugin.json").is_file()

        if not has_skills and not has_manifest:
            continue

        plugin_name = child.name

        # Scan skills
        if has_skills:
            skill_items = _scan_skills_in_dir(
                child / "skills", f"standalone:{plugin_name}"
            )
            for si in skill_items:
                if si.source_id not in seen_source_ids:
                    seen_source_ids.add(si.source_id)
                    items.append(si)

        # Scan MCP config
        mcp_path = child / "mcp.json"
        if mcp_path.is_file():
            try:
                mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
                servers = mcp_data.get("mcpServers", mcp_data.get("servers", {}))
                for server_name, server_config in servers.items():
                    if not isinstance(server_config, dict):
                        continue
                    sid = f"standalone:{plugin_name}:mcp:{server_name}"
                    if sid not in seen_source_ids:
                        seen_source_ids.add(sid)
                        items.append(
                            ImportItem(
                                kind="mcp_server",
                                source="claude_code",
                                source_id=sid,
                                data={
                                    "name": server_name,
                                    "server": server_config,
                                    "created_at": now.isoformat(),
                                },
                                label=f"MCP: {server_name}",
                            )
                        )
            except (json.JSONDecodeError, OSError):
                pass

    return items


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from body text."""
    import re

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


def _slugify(text: str) -> str:
    import re

    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]


def _parse_iso(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ── Main entry point ────────────────────────────────────────────────────────


def parse_claude_code_export(path: Path) -> ImportBundle:
    """Parse a Claude Code ``~/.claude/`` directory.

    Returns an :class:`ImportBundle` with all detected items.
    """
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    if not path.is_dir():
        warnings.append(f"Not a directory: {path}")
        return ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            warnings=warnings,
        )

    # Projects (sessions + CLAUDE.md)
    projects_dir = path / "projects"
    if projects_dir.is_dir():
        all_items.extend(_parse_projects(projects_dir))

    # Commands → Skills
    commands_dir = path / "commands"
    if commands_dir.is_dir():
        all_items.extend(_parse_commands(commands_dir))

    # Global MCP config
    mcp_path = path / ".mcp.json"
    if mcp_path.is_file():
        all_items.extend(_parse_mcp_config(mcp_path))

    # Global settings (credentials)
    settings_path = path / "settings.json"
    if settings_path.is_file():
        all_items.extend(_parse_settings(settings_path))

    # Claude Code also supports user-level skills directly under ~/.claude/skills.
    all_items.extend(_scan_skills_in_dir(path / "skills", "global"))

    # Plugin skills from installed_plugins.json
    all_items.extend(_parse_plugin_skills(path))

    # Standalone plugin directories (any dir with skills/ or plugin.json)
    all_items.extend(_parse_standalone_plugins(path))

    return ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=all_items,
        warnings=warnings,
        metadata={
            "total_items": len(all_items),
            "source_path": str(path),
        },
    )
