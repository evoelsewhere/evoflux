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
    """Extract a normalised message from a Claude Code JSONL entry."""
    # Claude Code JSONL entries vary — common patterns:
    # {"type": "message", "role": "user", "content": "..."}
    # {"type": "assistant", "message": {"role": "assistant", "content": [...]}}
    # {"role": "human", "content": "..."}
    # {"role": "assistant", "content": "..."}

    role_raw = entry.get("role", "")
    content_raw = entry.get("content", "")

    # Handle nested message structure
    if "message" in entry and isinstance(entry["message"], dict):
        inner = entry["message"]
        role_raw = inner.get("role", role_raw)
        content_raw = inner.get("content", content_raw)

    if not role_raw:
        entry_type = entry.get("type", "")
        if entry_type in ("user", "human"):
            role_raw = "user"
        elif entry_type in ("assistant", "ai"):
            role_raw = "assistant"
        elif entry_type == "system":
            role_raw = "system"
        else:
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

        # Parse sessions/*.jsonl
        sessions_dir = project_path / "sessions"
        if sessions_dir.is_dir():
            for session_file in sorted(sessions_dir.glob("*.jsonl")):
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
