"""ChatGPT web export parser.

Handles the ``conversations.json`` from ChatGPT Settings → Data Controls →
Export.  The export is a ZIP containing ``conversations.json`` (array of
conversation objects with a tree-based ``mapping`` structure) and optionally
``user.json``, ``model_comparisons.json``, etc.

ChatGPT uses a tree-based message structure where each node references its
children.  We flatten this into a linear message list by walking the tree
depth-first and sorting by ``create_time``.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.importers.base import ImportBundle, ImportItem, utcnow


# ── Timestamp helpers ────────────────────────────────────────────────────────


def _parse_ts(raw: float | int | None) -> datetime | None:
    """Convert a Unix timestamp to a timezone-aware datetime."""
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    except (OSError, ValueError, TypeError):
        return None


# ── Message tree flattening ─────────────────────────────────────────────────


def _flatten_mapping(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the ChatGPT message tree depth-first and return messages sorted
    by ``create_time``.

    Each mapping entry has the shape::

        {
          "id": "msg_...",
          "message": { "author": {"role": "user"}, "content": {...}, "create_time": ... },
          "children": ["msg_..."]
        }

    We DFS from the virtual ``"root"`` node.
    """
    if not mapping:
        return []

    # Build adjacency: parent -> children (preserve child order)
    children_map: dict[str, list[str]] = {}
    for node_id, node in mapping.items():
        kids = node.get("children") or []
        children_map[node_id] = kids

    # DFS traversal
    ordered_ids: list[str] = []
    stack = children_map.get("root", [])
    while stack:
        nid = stack.pop(0)
        ordered_ids.append(nid)
        # Prepend children so they are processed in order
        kids = children_map.get(nid, [])
        stack = kids + stack

    # Extract messages
    messages: list[dict[str, Any]] = []
    for nid in ordered_ids:
        node = mapping.get(nid)
        if not node:
            continue
        msg = node.get("message")
        if not msg:
            continue

        author = msg.get("author", {})
        role = author.get("role", "unknown")

        content = _extract_content(msg.get("content"))
        if not content:
            continue

        create_time = msg.get("create_time")
        messages.append(
            {
                "role": _normalise_role(role),
                "content": content,
                "created_at": (
                    _parse_ts(create_time) or datetime.now(timezone.utc)
                ).isoformat(),
                "model": msg.get("metadata", {}).get("model_slug"),
            }
        )

    return messages


def _normalise_role(role: str) -> str:
    """Map ChatGPT roles to EvoFlux roles."""
    mapping = {
        "user": "user",
        "assistant": "assistant",
        "system": "system",
        "tool": "tool",
    }
    return mapping.get(role, role)


def _extract_content(content: dict[str, Any] | None) -> str:
    """Extract human-readable text from a ChatGPT content block."""
    if content is None:
        return ""

    ctype = content.get("content_type", "")

    if ctype == "text":
        parts = content.get("parts", [])
        return "\n".join(str(p) for p in parts if p)

    if ctype == "code":
        code = content.get("text", "")
        lang = content.get("language", "")
        return f"```{lang}\n{code}\n```"

    if ctype == "tether_browsing_display":
        result = content.get("result", "")
        return result

    if ctype == "multimodal_text":
        parts = content.get("parts", [])
        text_parts: list[str] = []
        for p in parts:
            if isinstance(p, str):
                text_parts.append(p)
            elif isinstance(p, dict):
                if p.get("content_type") == "image_asset_pointer":
                    text_parts.append("[Image]")
                else:
                    text_parts.append(f"[{p.get('content_type', 'media')}]")
        return "\n".join(text_parts)

    # Fallback: try common fields
    for key in ("text", "result"):
        if key in content:
            return str(content[key])

    return ""


# ── Conversation parsing ────────────────────────────────────────────────────


def _parse_conversations(data: list[dict[str, Any]]) -> list[ImportItem]:
    """Parse ChatGPT conversations into ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    for conv in data:
        title = conv.get("title", "Untitled conversation")
        create_time = conv.get("create_time")
        update_time = conv.get("update_time")
        mapping = conv.get("mapping", {})

        messages = _flatten_mapping(mapping)
        if not messages:
            continue

        source_id = f"chatgpt:{title}:{create_time}"

        session_data: dict[str, Any] = {
            "title": title,
            "created_at": (_parse_ts(create_time) or now).isoformat(),
            "updated_at": (
                _parse_ts(update_time) or _parse_ts(create_time) or now
            ).isoformat(),
            "messages": messages,
            "mode": "work",
        }

        items.append(
            ImportItem(
                kind="session",
                source="chatgpt",
                source_id=source_id,
                data=session_data,
                label=title,
            )
        )

    return items


# ── Custom GPTs parsing ─────────────────────────────────────────────────────


def _parse_gpts(data: list[dict[str, Any]]) -> list[ImportItem]:
    """Parse ChatGPT Custom GPTs into agent/skill ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    for gpt in data:
        name = gpt.get("name", "Untitled GPT")
        description = gpt.get("description", "")
        instructions = gpt.get("instructions", "")
        tools = gpt.get("tools", [])

        if instructions:
            agent_data: dict[str, Any] = {
                "name": _slugify(name),
                "description": description or f"Imported from ChatGPT: {name}",
                "instructions": instructions,
                "created_at": now.isoformat(),
            }
            items.append(
                ImportItem(
                    kind="agent",
                    source="chatgpt",
                    source_id=f"gpt:{name}",
                    data=agent_data,
                    label=f"Agent: {name}",
                )
            )

        if tools:
            tool_desc = "\n".join(
                f"- {t.get('type', 'unknown')}: {t.get('metadata', {}).get('name', '')}"
                for t in tools
            )
            skill_data: dict[str, Any] = {
                "name": _slugify(name),
                "description": f"Tools from ChatGPT GPT: {name}",
                "body": (
                    f"## Tools\n\n{tool_desc}\n\n## Instructions\n\n{instructions}"
                ),
                "created_at": now.isoformat(),
            }
            items.append(
                ImportItem(
                    kind="skill",
                    source="chatgpt",
                    source_id=f"gpt:{name}:skill",
                    data=skill_data,
                    label=f"Skill: {name}",
                )
            )

    return items


# ── Memory / user preferences ───────────────────────────────────────────────


def _parse_memory(data: dict[str, Any]) -> list[ImportItem]:
    """Parse ChatGPT memory/user preferences into knowledge ImportItems."""
    items: list[ImportItem] = []
    now = utcnow()

    facts = data.get("user_memory", [])
    if isinstance(facts, list):
        for i, fact in enumerate(facts):
            if isinstance(fact, str) and fact.strip():
                items.append(
                    ImportItem(
                        kind="knowledge",
                        source="chatgpt",
                        source_id=f"memory:{i}",
                        data={
                            "filename": f"chatgpt-memory-{i}.md",
                            "content": fact.strip(),
                            "created_at": now.isoformat(),
                        },
                        label=f"Memory: {fact[:60]}...",
                    )
                )
    elif isinstance(data.get("user_system_message"), dict):
        content = data["user_system_message"].get("content", "")
        if content:
            items.append(
                ImportItem(
                    kind="knowledge",
                    source="chatgpt",
                    source_id="memory:system_message",
                    data={
                        "filename": "chatgpt-user-preferences.md",
                        "content": content,
                        "created_at": now.isoformat(),
                    },
                    label="ChatGPT user preferences",
                )
            )

    return items


def _slugify(text: str) -> str:
    """Simple slug for filenames."""
    import re

    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]


# ── Main entry point ────────────────────────────────────────────────────────


def parse_chatgpt_export(path: Path) -> ImportBundle:
    """Parse a ChatGPT export (JSON file or ZIP archive).

    Returns an :class:`ImportBundle` with all detected items.
    """
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    conversations: list[dict[str, Any]] = []
    gpts: list[dict[str, Any]] = []
    memory: dict[str, Any] = {}

    if path.suffix.lower() == ".zip":
        conversations, gpts, memory, zip_warnings = _extract_zip(path)
        warnings.extend(zip_warnings)
    elif path.suffix.lower() == ".json":
        conversations, gpts, memory, json_warnings = _extract_json(path)
        warnings.extend(json_warnings)
    else:
        warnings.append(f"Unexpected file extension: {path.suffix}")
        return ImportBundle(
            source="chatgpt",
            detected_format="chatgpt",
            warnings=warnings,
        )

    if conversations:
        all_items.extend(_parse_conversations(conversations))
    if gpts:
        all_items.extend(_parse_gpts(gpts))
    if memory:
        all_items.extend(_parse_memory(memory))

    return ImportBundle(
        source="chatgpt",
        detected_format="chatgpt",
        items=all_items,
        warnings=warnings,
        metadata={
            "conversation_count": len(conversations),
            "gpt_count": len(gpts),
            "total_items": len(all_items),
            "source_path": str(path),
        },
    )


def _extract_zip(
    path: Path,
) -> tuple[list[dict], list[dict], dict, list[str]]:
    """Extract data from a ChatGPT export ZIP."""
    warnings: list[str] = []
    conversations: list[dict[str, Any]] = []
    gpts: list[dict[str, Any]] = []
    memory: dict[str, Any] = {}

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

                if "conversation" in lower and isinstance(data, list):
                    conversations.extend(data)
                elif "gpt" in lower and isinstance(data, list):
                    gpts.extend(data)
                elif lower.endswith("user.json") and isinstance(data, dict):
                    memory = data
    except zipfile.BadZipFile as exc:
        warnings.append(f"Invalid ZIP file: {exc}")

    return conversations, gpts, memory, warnings


def _extract_json(
    path: Path,
) -> tuple[list[dict], list[dict], dict, list[str]]:
    """Extract data from a ChatGPT JSON file."""
    warnings: list[str] = []
    conversations: list[dict[str, Any]] = []
    gpts: list[dict[str, Any]] = []
    memory: dict[str, Any] = {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        warnings.append(f"Could not read {path}: {exc}")
        return conversations, gpts, memory, warnings

    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            if "mapping" in data[0]:
                conversations = data
            elif "instructions" in data[0]:
                gpts = data
            else:
                conversations = data
    elif isinstance(data, dict):
        if "conversations" in data:
            conversations = data["conversations"]
        if "gpts" in data:
            gpts = data["gpts"]
        if "user_memory" in data or "user_system_message" in data:
            memory = data

    return conversations, gpts, memory, warnings
