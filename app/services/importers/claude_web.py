"""Claude.ai web export parser.

Handles the JSON array exported from Claude Settings → Export Data.
Each conversation is a dict with ``uuid``, ``name``, ``created_at``,
``updated_at``, and ``chat_messages`` (list of message dicts).

Also handles Claude Projects: project instructions → agent config,
project knowledge files → wiki notes.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.importers.base import ImportBundle, ImportItem, utcnow


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse ISO-8601 datetime string, returning None on failure."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _normalise_content(msg: dict[str, Any]) -> str:
    """Extract human-readable text from a Claude message.

    Claude messages may have ``text`` (simple string) or ``content``
    (list of typed blocks).  We join text blocks; non-text blocks are
    noted as metadata.
    """
    text = msg.get("text")
    if text:
        return str(text)

    content = msg.get("content")
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
                    name = block.get("name", "unknown_tool")
                    parts.append(f"[Tool call: {name}]")
                elif btype == "tool_result":
                    parts.append("[Tool result]")
                elif btype == "image":
                    parts.append("[Image]")
                else:
                    parts.append(f"[{btype}]")
        return "\n".join(parts)

    return ""


def _message_role(sender: str) -> str:
    """Map Claude sender to EvoFlux message role."""
    mapping = {
        "human": "user",
        "assistant": "assistant",
        "system": "system",
    }
    return mapping.get(sender, sender)


def _parse_conversations(data: list[dict[str, Any]]) -> list[ImportItem]:
    """Parse a list of Claude conversation dicts into ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    for conv in data:
        conv_id = conv.get("uuid", "")
        title = conv.get("name", "Untitled conversation")
        created = _parse_dt(conv.get("created_at"))
        updated = _parse_dt(conv.get("updated_at"))

        messages_raw: list[dict[str, Any]] = conv.get("chat_messages", [])
        messages: list[dict[str, Any]] = []
        for i, msg in enumerate(messages_raw):
            sender = msg.get("sender", "unknown")
            role = _message_role(sender)
            content = _normalise_content(msg)
            msg_created = _parse_dt(msg.get("created_at"))
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "created_at": (msg_created or created or now).isoformat(),
                    "source_index": i,
                }
            )

        session_data: dict[str, Any] = {
            "title": title,
            "created_at": (created or now).isoformat(),
            "updated_at": (updated or created or now).isoformat(),
            "messages": messages,
            "mode": "work",
        }

        items.append(
            ImportItem(
                kind="session",
                source="claude_web",
                source_id=conv_id,
                data=session_data,
                label=title,
            )
        )

    return items


def _parse_projects(data: list[dict[str, Any]]) -> list[ImportItem]:
    """Parse Claude Projects into agent configs and knowledge items."""
    items: list[ImportItem] = []
    now = utcnow()

    for proj in data:
        proj_name = proj.get("name", "Untitled project")
        instructions = proj.get("instructions", "")
        knowledge_files = proj.get("documents", [])

        if instructions:
            agent_data: dict[str, Any] = {
                "name": _slugify(proj_name),
                "description": f"Imported from Claude Project: {proj_name}",
                "instructions": instructions,
                "created_at": now.isoformat(),
            }
            items.append(
                ImportItem(
                    kind="agent",
                    source="claude_web",
                    source_id=f"project:{proj_name}",
                    data=agent_data,
                    label=f"Agent: {proj_name}",
                )
            )

        for doc in knowledge_files:
            doc_name = doc.get("name", "untitled")
            doc_content = doc.get("content", "")
            if doc_content:
                knowledge_data: dict[str, Any] = {
                    "filename": f"{_slugify(proj_name)}-{_slugify(doc_name)}.md",
                    "content": doc_content,
                    "source_project": proj_name,
                    "created_at": now.isoformat(),
                }
                items.append(
                    ImportItem(
                        kind="knowledge",
                        source="claude_web",
                        source_id=f"project:{proj_name}:doc:{doc_name}",
                        data=knowledge_data,
                        label=f"Knowledge: {proj_name}/{doc_name}",
                    )
                )

    return items


def _slugify(text: str) -> str:
    """Simple slug for filenames."""
    import re

    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]


def parse_claude_web_export(path: Path) -> ImportBundle:
    """Parse a Claude.ai web export (JSON file or ZIP archive).

    Returns an :class:`ImportBundle` with all detected items.
    """
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    # ── Load data ──────────────────────────────────────────────────────────
    conversations: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []

    if path.suffix.lower() == ".zip":
        conversations, projects, zip_warnings = _extract_zip(path)
        warnings.extend(zip_warnings)
    elif path.suffix.lower() == ".json":
        conversations, projects, json_warnings = _extract_json(path)
        warnings.extend(json_warnings)
    else:
        warnings.append(f"Unexpected file extension: {path.suffix}")
        return ImportBundle(
            source="claude_web",
            detected_format="claude_web",
            warnings=warnings,
        )

    # ── Parse ──────────────────────────────────────────────────────────────
    if conversations:
        all_items.extend(_parse_conversations(conversations))
    if projects:
        all_items.extend(_parse_projects(projects))

    return ImportBundle(
        source="claude_web",
        detected_format="claude_web",
        items=all_items,
        warnings=warnings,
        metadata={
            "conversation_count": len(conversations),
            "project_count": len(projects),
            "total_items": len(all_items),
            "source_path": str(path),
        },
    )


def _extract_zip(
    path: Path,
) -> tuple[list[dict], list[dict], list[str]]:
    """Extract conversations and projects from a Claude export ZIP."""
    warnings: list[str] = []
    conversations: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []

    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                lower = name.lower()
                try:
                    with zf.open(name) as f:
                        data = json.loads(f.read())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    warnings.append(f"Could not parse {name}: {exc}")
                    continue

                if lower.endswith("conversations.json") or lower.endswith(
                    "conversations"
                ):
                    if isinstance(data, list):
                        conversations.extend(data)
                    elif isinstance(data, dict):
                        conversations.extend(data.get("conversations", []))
                elif "project" in lower:
                    if isinstance(data, list):
                        projects.extend(data)
                    elif isinstance(data, dict):
                        projects.extend(data.get("projects", []))
                elif lower.endswith(".json") and isinstance(data, list):
                    # Heuristic: if it looks like conversations, treat as such
                    if (
                        data
                        and isinstance(data[0], dict)
                        and "chat_messages" in data[0]
                    ):
                        conversations.extend(data)
    except zipfile.BadZipFile as exc:
        warnings.append(f"Invalid ZIP file: {exc}")

    return conversations, projects, warnings


def _extract_json(
    path: Path,
) -> tuple[list[dict], list[dict], list[str]]:
    """Extract conversations and projects from a Claude export JSON file."""
    warnings: list[str] = []
    conversations: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        warnings.append(f"Could not read {path}: {exc}")
        return conversations, projects, warnings

    if isinstance(data, list):
        # Top-level array — check first element to decide type
        if data and isinstance(data[0], dict):
            if "chat_messages" in data[0] or "uuid" in data[0]:
                conversations = data
            elif "documents" in data[0] or "instructions" in data[0]:
                projects = data
            else:
                # Assume conversations
                conversations = data
    elif isinstance(data, dict):
        if "conversations" in data:
            conversations = data["conversations"]
        if "projects" in data:
            projects = data["projects"]

    return conversations, projects, warnings
