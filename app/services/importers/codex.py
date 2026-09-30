"""Codex CLI directory parser.

Handles the ``.codex/`` directory structure produced by the OpenAI Codex CLI.

Expected layout::

    .codex/
    ├── config.json          # model, provider preferences
    ├── instructions.md      # workspace instructions
    └── sessions/
        └── <session-id>.jsonl  # session transcript
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.importers.base import ImportBundle, ImportItem, utcnow


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


def _normalise_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype in ("text", "input_text", "output_text"):
                    parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    parts.append(f"[Tool call: {block.get('name', 'unknown')}]")
                elif btype == "tool_result":
                    parts.append("[Tool result]")
                else:
                    parts.append(f"[{btype}]")
        return "\n".join(parts)
    return str(content) if content else ""


def _extract_codex_message(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a normalised message from a Codex JSONL entry.

    Handles:
    - ``{"type":"response_item","payload":{"type":"message","role":"user","content":"..."}}``
    - ``{"type":"event_msg","payload":{"type":"message","role":"user","content":"..."}}``
    - ``{"type":"event_msg","payload":{"type":"assistant_message","content":"..."}}``
    - ``{"role":"user","content":"..."}`` (simple format)
    - ``{"type":"session_meta",…}`` → skip
    """
    entry_type = entry.get("type", "")

    # Skip non-message types
    if entry_type in (
        "session_meta",
        "world_state",
        "turn_context",
        "task_started",
        "item_completed",
        "item_updated",
        "turn_completed",
    ):
        return None

    # ── response_item format (Codex CLI current) ────────────────────────
    if entry_type == "response_item":
        payload = entry.get("payload", {})
        if payload.get("type") == "message":
            role = payload.get("role", "")
            content = _normalise_content(payload.get("content", ""))
            if role and content and role != "developer":
                role_map = {
                    "user": "user",
                    "assistant": "assistant",
                    "system": "system",
                }
                return {
                    "role": role_map.get(role, role),
                    "content": content,
                    "created_at": (
                        _parse_iso(entry.get("timestamp")) or utcnow()
                    ).isoformat(),
                }
        return None

    # ── event_msg format (Codex CLI older) ──────────────────────────────
    if entry_type == "event_msg":
        payload = entry.get("payload", {})
        payload_type = payload.get("type", "")

        if payload_type == "message":
            role = payload.get("role", "")
            content = _normalise_content(payload.get("content", ""))
            if role and content and role != "developer":
                role_map = {
                    "user": "user",
                    "assistant": "assistant",
                    "system": "system",
                }
                return {
                    "role": role_map.get(role, role),
                    "content": content,
                    "created_at": (
                        _parse_iso(entry.get("timestamp")) or utcnow()
                    ).isoformat(),
                }

        if payload_type == "assistant_message":
            content = _normalise_content(payload.get("content", ""))
            if content:
                return {
                    "role": "assistant",
                    "content": content,
                    "created_at": (
                        _parse_iso(entry.get("timestamp")) or utcnow()
                    ).isoformat(),
                }

        return None

    # ── Simple format: role + content at top level ──────────────────────
    role = entry.get("role", "")
    content = _normalise_content(entry.get("content", ""))
    if not role or not content:
        return None

    role_map = {
        "human": "user",
        "user": "user",
        "assistant": "assistant",
        "system": "system",
    }
    return {
        "role": role_map.get(role, role),
        "content": content,
        "created_at": (
            _parse_iso(entry.get("timestamp") or entry.get("created_at")) or utcnow()
        ).isoformat(),
    }


def _parse_session_jsonl(path: Path) -> dict[str, Any] | None:
    """Parse a Codex JSONL session file."""
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

                msg = _extract_codex_message(entry)
                if msg:
                    if created_at is None:
                        created_at = _parse_iso(msg.get("created_at"))
                    messages.append(msg)
    except OSError:
        return None

    if not messages:
        return None

    title = "Codex session"
    for m in messages:
        if m.get("role") == "user":
            title = m["content"][:80].split("\n")[0].strip()
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


def _parse_sessions(sessions_dir: Path) -> list[ImportItem]:
    items: list[ImportItem] = []
    if not sessions_dir.is_dir():
        return items
    # Sessions are nested: sessions/2026/09/<day>/thread.jsonl
    for session_file in sorted(sessions_dir.rglob("*.jsonl")):
        data = _parse_session_jsonl(session_file)
        if data:
            items.append(
                ImportItem(
                    kind="session",
                    source="codex",
                    source_id=f"session:{session_file.stem}",
                    data=data,
                    label=data["title"],
                )
            )
    return items


def _parse_instructions(path: Path) -> list[ImportItem]:
    items: list[ImportItem] = []
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
                source="codex",
                source_id="instructions",
                data={
                    "name": "codex-workspace",
                    "description": "Imported from Codex CLI instructions",
                    "instructions": content,
                    "created_at": utcnow().isoformat(),
                },
                label="Agent: Codex workspace instructions",
            )
        )
    return items


def _parse_config(path: Path) -> list[ImportItem]:
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
                source="codex",
                source_id="config",
                data={"settings": data},
                label="Codex settings",
            )
        )
    return items


def parse_codex_export(path: Path) -> ImportBundle:
    """Parse a Codex CLI ``.codex/`` directory."""
    warnings: list[str] = []
    all_items: list[ImportItem] = []

    if not path.is_dir():
        warnings.append(f"Not a directory: {path}")
        return ImportBundle(source="codex", detected_format="codex", warnings=warnings)

    all_items.extend(_parse_sessions(path / "sessions"))
    all_items.extend(_parse_instructions(path / "instructions.md"))
    all_items.extend(_parse_config(path / "config.json"))

    return ImportBundle(
        source="codex",
        detected_format="codex",
        items=all_items,
        warnings=warnings,
        metadata={"total_items": len(all_items), "source_path": str(path)},
    )
