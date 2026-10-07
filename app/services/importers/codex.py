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
from app.services.importers.generic import parse_generic_export


_MAX_IMPORTED_TEXT_CHARS = 20_000


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
    """Keep readable text blocks and omit control/reasoning block markers."""
    if isinstance(content, str):
        return content[:_MAX_IMPORTED_TEXT_CHARS]
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype in ("text", "input_text", "output_text"):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "\n".join(parts)[:_MAX_IMPORTED_TEXT_CHARS]
    return ""


def _source_extra(event_kind: str) -> dict[str, Any]:
    return {"import_source": {"provider": "codex", "event_kind": event_kind}}


def _normalise_arguments(value: Any) -> str:
    if isinstance(value, str):
        return value if len(value) <= _MAX_IMPORTED_TEXT_CHARS else '{"_truncated":true}'
    if isinstance(value, dict | list):
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return (
                encoded
                if len(encoded) <= _MAX_IMPORTED_TEXT_CHARS
                else '{"_truncated":true}'
            )
        except (TypeError, ValueError):
            return "{}"
    return "{}"


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
        if not isinstance(payload, dict):
            return None
        payload_type = payload.get("type")
        timestamp = (
            _parse_iso(entry.get("timestamp")) or utcnow()
        ).isoformat()

        if payload_type == "function_call":
            call_id = payload.get("call_id") or payload.get("id") or entry.get("id")
            name = payload.get("name")
            if not isinstance(call_id, str) or not call_id:
                call_id = f"codex-call-{timestamp}"
            if not isinstance(name, str) or not name.strip():
                name = "unknown_tool"
            return {
                "role": "assistant",
                "content": "",
                "created_at": timestamp,
                "tool_calls": [
                    {
                        "id": call_id[:256],
                        "type": "function",
                        "function": {
                            "name": name.strip()[:256],
                            "arguments": _normalise_arguments(
                                payload.get("arguments")
                            ),
                        },
                    }
                ],
                "extra": _source_extra("function_call"),
            }

        if payload_type == "function_call_output":
            call_id = payload.get("call_id") or payload.get("id")
            if not isinstance(call_id, str) or not call_id:
                return None
            output = _normalise_content(payload.get("output", ""))
            return {
                "role": "tool",
                "content": output,
                "created_at": timestamp,
                "tool_call_id": call_id[:256],
                "name": "tool",
                "extra": _source_extra("function_call_output"),
            }

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
                    "created_at": timestamp,
                    "extra": _source_extra("message"),
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
                    "extra": _source_extra("message"),
                }

        if payload_type == "assistant_message":
            content = _normalise_content(
                payload.get("content", payload.get("message", ""))
            )
            if content:
                return {
                    "role": "assistant",
                    "content": content,
                    "created_at": (
                        _parse_iso(entry.get("timestamp")) or utcnow()
                    ).isoformat(),
                    "extra": _source_extra("assistant_message"),
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
        "extra": _source_extra("message"),
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

    # Codex reads user skills from the shared Agent Skills root next to .codex.
    skills_root = path.parent / ".agents" / "skills"
    if skills_root.is_dir():
        skills = parse_generic_export(skills_root).items
        for item in skills:
            if item.kind == "skill":
                item.source = "codex"
                item.source_id = f"codex:{item.source_id}"
                all_items.append(item)

    return ImportBundle(
        source="codex",
        detected_format="codex",
        items=all_items,
        warnings=warnings,
        metadata={"total_items": len(all_items), "source_path": str(path)},
    )
