"""Import orchestrator — detect, preview, execute.

Reads a local path, auto-detects the source format, runs the correct parser,
and writes accepted items through existing EvoFlux services.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.chat import ChatSession, SessionMessage
from app.services.importers.base import (
    ImportBundle,
    ImportItem,
    ImportItemOutcome,
    ImportResult,
    ImportUndoResult,
    utcnow,
)
from app.services.importers.claude_web import parse_claude_web_export
from app.services.importers.chatgpt import parse_chatgpt_export
from app.services.importers.claude_code import parse_claude_code_export
from app.services.importers.codex import parse_codex_export
from app.services.importers.cursor import parse_cursor_export
from app.services.importers.generic import parse_generic_export

# ── Import state (in-memory for Phase 1; moves to DB in Phase 4) ────────────

_import_jobs: dict[str, ImportBundle] = {}

# ── Source detection ─────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {".json", ".zip", ".jsonl", ".md", ".yaml", ".yml"}

# Map of source -> typical file/directory patterns
_SOURCE_SIGNATURES: dict[str, list[str]] = {
    "claude_web": ["conversations.json", "projects.json"],
    "claude_code": [".claude", "CLAUDE.md"],
    "chatgpt": ["conversations.json", "user.json", "model_comparisons.json"],
    "codex": [".codex", "sessions"],
    "cursor": [".cursor", ".cursorrules", ".cursorrules"],
}


def detect_source(path: Path) -> str | None:
    """Auto-detect the import source from a file or directory path.

    Returns the source identifier (e.g. ``"claude_web"``) or ``None`` if
    the format is not recognised.
    """
    if path.is_file():
        return _detect_file(path)
    if path.is_dir():
        return _detect_directory(path)
    return None


def _detect_file(path: Path) -> str | None:
    """Detect source from a single file."""
    name = path.name.lower()

    # ── JSON heuristic ─────────────────────────────────────────────────
    if path.suffix.lower() == ".json":
        try:
            with open(path, encoding="utf-8") as f:
                # Read just enough to detect format
                head = f.read(4096)
        except OSError:
            return None

        # Claude web: array of objects with chat_messages/uuid
        if '"chat_messages"' in head or '"uuid"' in head:
            return "claude_web"
        # ChatGPT: object with mapping key or array of objects with mapping
        if '"mapping"' in head or '"create_time"' in head:
            return "chatgpt"
        # Generic MCP config
        if '"mcpServers"' in head or '"servers"' in head:
            return "generic"
        # Default to claude_web if it's a JSON array
        if head.lstrip().startswith("["):
            return "claude_web"

    # ── ZIP heuristic ──────────────────────────────────────────────────
    if path.suffix.lower() == ".zip":
        import zipfile

        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = {n.lower() for n in zf.namelist()}
        except zipfile.BadZipFile:
            return None
        if any("conversation" in n for n in names):
            # Could be Claude or ChatGPT — check content
            return _detect_zip_content(path)
        return None

    # ── JSONL ──────────────────────────────────────────────────────────
    if path.suffix.lower() == ".jsonl":
        return "claude_code"

    # ── Markdown ───────────────────────────────────────────────────────
    if path.suffix.lower() == ".md":
        if name == "claude.md":
            return "claude_code"
        if name == ".cursorrules" or name == "cursorrules":
            return "cursor"
        # Check for SKILL.md frontmatter
        try:
            head = path.read_text(encoding="utf-8")[:200]
            if head.lstrip().startswith("---"):
                return "generic"
        except OSError:
            pass

    return None


def _detect_directory(path: Path) -> str | None:
    """Detect source from a directory."""
    children = {p.name for p in path.iterdir()}

    # Claude Code: ~/.claude/ or project with CLAUDE.md
    if ".claude" in children or "CLAUDE.md" in children:
        return "claude_code"
    # Cursor: .cursor/ or .cursorrules
    if ".cursor" in children or ".cursorrules" in children:
        return "cursor"
    # Codex: .codex/
    if ".codex" in children:
        return "codex"
    # Generic: has SKILL.md, plugin.json, or mcp.json
    if "SKILL.md" in children or "plugin.json" in children or "mcp.json" in children:
        return "generic"

    return None


def _detect_zip_content(path: Path) -> str | None:
    """Distinguish Claude vs ChatGPT ZIP by inspecting content."""
    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                lower = name.lower()
                if "conversation" in lower:
                    with zf.open(name) as f:
                        head = f.read(4096).decode("utf-8", errors="replace")
                    if '"mapping"' in head:
                        return "chatgpt"
                    if '"chat_messages"' in head or '"uuid"' in head:
                        return "claude_web"
    except (zipfile.BadZipFile, OSError):
        pass
    return None


# ── Parsing dispatch ────────────────────────────────────────────────────────


def parse_import(path: Path, source: str | None = None) -> ImportBundle:
    """Parse an import source into an ImportBundle.

    If *source* is ``None``, auto-detection is attempted first.
    """
    if source is None:
        source = detect_source(path)

    if source is None:
        return ImportBundle(
            source="unknown",
            detected_format="unknown",
            warnings=[
                f"Could not detect source format for: {path}. "
                "Please specify the source explicitly."
            ],
        )

    parsers = {
        "claude_web": parse_claude_web_export,
        "chatgpt": parse_chatgpt_export,
        "claude_code": parse_claude_code_export,
        "codex": parse_codex_export,
        "cursor": parse_cursor_export,
        "generic": parse_generic_export,
    }

    parser = parsers.get(source)
    if parser is None:
        return ImportBundle(
            source=source,
            detected_format=source,
            warnings=[
                f"Parser for source '{source}' is not yet implemented. "
                "Supported: claude_web, chatgpt, claude_code, codex, cursor, generic."
            ],
        )

    return parser(path)


# ── Conflict detection ──────────────────────────────────────────────────────


async def detect_conflicts(
    db: AsyncSession,
    bundle: ImportBundle,
) -> ImportBundle:
    """Check each item against existing data and annotate conflicts.

    Sessions: match by (source, title).  Agents/skills: file existence.
    MCP servers: name in mcp.json.  Knowledge: filename in wiki/sources/.
    Items already present get ``action="skip"`` and a conflict note.
    """
    for item in bundle.items:
        item.conflicts.clear()
        item.data.pop("_matched_session_id", None)
        item.data.pop("_conflict_reason", None)
        if item.kind == "session":
            await _check_session_conflict(db, item)
        elif item.kind == "agent":
            _check_agent_conflict(item)
        elif item.kind == "skill":
            _check_skill_conflict(item)
        elif item.kind == "mcp_server":
            _check_mcp_conflict(item)
        elif item.kind == "knowledge":
            _check_knowledge_conflict(item)

    return bundle


async def _check_session_conflict(db: AsyncSession, item: ImportItem) -> None:
    """Match stable source identity, falling back only to unique legacy titles."""
    title = item.data.get("title", "")
    existing = None
    if item.source_id:
        result = await db.execute(
            select(ChatSession).where(
                col(ChatSession.source) == item.source,
                col(ChatSession.source_item_id) == item.source_id,
            )
        )
        existing = result.scalars().first()

    # Migrate imports made by older releases that generated ChatGPT IDs from
    # title + create_time. The stable provider ID cannot be reconstructed from
    # those rows, so bridge only a unique timestamp match. Ambiguous matches
    # must remain reviewable rather than updating an unrelated conversation.
    legacy_source_id = item.data.get("_legacy_source_id")
    if existing is None and item.source == "chatgpt" and legacy_source_id:
        result = await db.execute(
            select(ChatSession).where(
                col(ChatSession.source) == item.source,
                col(ChatSession.source_item_id) == legacy_source_id,
            )
        )
        existing = result.scalars().first()

        if existing is None:
            legacy_timestamp = str(legacy_source_id).rsplit(":", 1)[-1]
            result = await db.execute(
                select(ChatSession).where(
                    col(ChatSession.source) == item.source,
                    col(ChatSession.source_item_id).startswith("chatgpt:"),
                )
            )
            legacy_candidates = [
                candidate
                for candidate in result.scalars().all()
                if candidate.source_item_id
                and candidate.source_item_id.endswith(f":{legacy_timestamp}")
            ]
            if len(legacy_candidates) == 1:
                existing = legacy_candidates[0]
            elif len(legacy_candidates) > 1:
                item.conflicts.append(
                    "Multiple legacy ChatGPT imports share this creation time"
                )
                item.data["_conflict_reason"] = "ambiguous_legacy_match"
                item.action = "skip"

    if existing is None:
        stmt = select(ChatSession).where(
            col(ChatSession.source) == item.source,
            col(ChatSession.title) == title,
        )
        result = await db.execute(stmt)
        candidates = list(result.scalars().all())
        # A different stable source ID is a different source session. Legacy
        # title matching is safe only for sessions that predate source IDs.
        legacy_matches = [
            candidate for candidate in candidates if candidate.source_item_id is None
        ]
        if len(legacy_matches) == 1:
            existing = legacy_matches[0]
        elif not item.source_id and len(candidates) == 1:
            existing = candidates[0]
        elif len(legacy_matches) > 1 or (not item.source_id and len(candidates) > 1):
            item.conflicts.append("Multiple legacy sessions have this source and title")
            item.data["_conflict_reason"] = "ambiguous_legacy_match"
            item.action = "skip"

    if existing is not None:
        item.data["_matched_session_id"] = str(existing.id)
        item.conflicts.append("Already imported")
        if item.action not in {"reimport", "replace"}:
            item.action = "skip"


def _check_agent_conflict(item: ImportItem) -> None:
    """Check if an agent file with the same name exists."""
    from app.core.config import settings

    agent_file = (
        Path(settings.EVOFLUX_CONFIG_DIR)
        / "agents"
        / f"{_agent_file_name(item.data.get('name', ''))}.md"
    )
    if agent_file.exists():
        item.conflicts.append("Agent already exists")
        item.action = "skip"


def _check_skill_conflict(item: ImportItem) -> None:
    """Check the EvoFlux target and other registered local Skill sources."""
    from app.core.config import settings

    name = item.data.get("name", "")
    target_root = Path(settings.SKILLS_DIR)
    skill_dir = target_root / _skill_directory_name(name)
    if skill_dir.exists():
        item.conflicts.append("Skill already exists")
        item.action = "skip"
        return

    # A same-name Skill in Claude/Codex/plugin roots is not an EvoFlux target,
    # but importing a copy would make registry precedence ambiguous. Keep it
    # under manual review and explain which local source owns the existing one.
    from app.agent.skills.registry import discover_skills

    existing = discover_skills().get(name)
    if existing is None:
        return
    try:
        same_root = existing.root.resolve() == target_root.resolve()
    except OSError:
        same_root = existing.root.absolute() == target_root.absolute()
    if same_root:
        return

    origin = _skill_registry_origin(existing)
    item.conflicts.append(f"Skill already exists in {origin}")
    item.action = "skip"
    item.data.setdefault("preview_origin", origin)


def _skill_registry_origin(skill: Any) -> str:
    """Describe a Skill source without exposing a machine-specific path."""
    if skill.plugin_id:
        return f"Plugin skill · {skill.plugin_id}"
    parts = {part.casefold() for part in skill.root.parts}
    if ".claude" in parts:
        return "Claude Code skills"
    if ".agents" in parts:
        return "Shared Agent Skills"
    if skill.source == "builtin":
        return "EvoFlux built-in skills"
    return "another local Skill source"


def _rename_skill_target(item: ImportItem) -> str:
    """Give a provider Skill a distinct EvoFlux name without touching source."""
    from app.core.config import settings

    original_name = item.data.setdefault("_original_name", item.data.get("name", ""))
    safe_original = _skill_directory_name(original_name)
    skills_root = Path(settings.SKILLS_DIR)
    suffix = 1
    while True:
        tail = "-evoflux" if suffix == 1 else f"-evoflux-{suffix}"
        prefix = safe_original[: 64 - len(tail)].rstrip("-") or "skill"
        candidate = f"{prefix}{tail}"
        if not (skills_root / candidate).exists():
            break
        suffix += 1
    item.data["name"] = candidate
    return candidate


def _check_mcp_conflict(item: ImportItem) -> None:
    """Check if an MCP server with the same name already exists in config."""
    import json as json_mod

    from app.core.config import settings

    mcp_path = Path(settings.EVOFLUX_CONFIG_DIR) / "mcp.json"
    if not mcp_path.exists():
        return
    try:
        data = json_mod.loads(mcp_path.read_text(encoding="utf-8"))
        servers = data.get("servers", {})
        if item.data.get("name") in servers:
            item.conflicts.append("MCP server already exists")
            item.action = "skip"
    except (ValueError, OSError):
        pass


def _check_knowledge_conflict(item: ImportItem) -> None:
    """Check if a knowledge file with the same name already exists."""
    from app.core.config import settings

    filename = item.data.get("filename", "")
    safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")[:200]
    knowledge_path = Path(settings.EVOFLUX_WIKI_DIR) / "sources" / safe_name
    if knowledge_path.exists():
        item.conflicts.append("Knowledge file already exists")
        item.action = "skip"


# ── Execution ───────────────────────────────────────────────────────────────


async def execute_import(
    db: AsyncSession,
    bundle: ImportBundle,
    *,
    origin: str = "manual",
) -> ImportResult:
    """Write accepted items and a durable per-item journal."""
    result = ImportResult()
    now = utcnow()
    import uuid

    from app.models.import_job import ImportJob
    from app.models.import_job_item import ImportJobItem

    job = ImportJob(
        id=uuid.uuid4().hex,
        source=bundle.source,
        source_path=bundle.metadata.get("source_path", ""),
        detected_format=bundle.detected_format,
        origin=origin if origin in {"manual", "auto_sync"} else "manual",
        undo_state="available",
        status="completed",
        imported_counts="{}",
        skipped_counts="{}",
        error_count=0,
        item_count=len(bundle.items),
        created_at=now,
        completed_at=now,
    )
    db.add(job)
    await db.commit()
    result.import_id = job.id

    for index, item in enumerate(bundle.items):
        source_item_id = f"{item.kind}:{item.source_id or index}"
        if item.action == "skip":
            result.skipped[item.kind] = result.skipped.get(item.kind, 0) + 1
            journal = ImportJobItem(
                id=uuid.uuid4().hex,
                job_id=job.id,
                source_item_id=source_item_id,
                kind=item.kind,
                label=item.label,
                operation="none",
                outcome="skipped",
                reason=item.data.get("_conflict_reason")
                or item.data.get("_skip_reason")
                or "Skipped by user or conflict detection",
                created_at=now,
                updated_at=utcnow(),
            )
            db.add(journal)
            result.items.append(
                ImportItemOutcome(
                    source_item_id,
                    item.kind,
                    item.label,
                    "none",
                    "skipped",
                    journal.reason,
                )
            )
            continue

        if item.kind not in {"session", "agent", "skill", "knowledge", "mcp_server"}:
            result.skipped[item.kind] = result.skipped.get(item.kind, 0) + 1
            journal = ImportJobItem(
                id=uuid.uuid4().hex,
                job_id=job.id,
                source_item_id=source_item_id,
                kind=item.kind,
                label=item.label,
                operation="none",
                outcome="skipped",
                reason="This item type is not supported by the importer.",
                created_at=now,
                updated_at=utcnow(),
            )
            db.add(journal)
            result.items.append(
                ImportItemOutcome(
                    source_item_id,
                    item.kind,
                    item.label,
                    "none",
                    "skipped",
                    journal.reason,
                )
            )
            continue

        is_reimport = item.action in {"reimport", "replace"}
        target_ref: str | None = None
        before_snapshot: str | None = None
        operation = "reimported" if is_reimport else "created"
        session_target: ChatSession | None = None
        target_path: Path | None = None
        journal_id = uuid.uuid4().hex
        journal: ImportJobItem | None = None
        try:
            if item.kind == "session":
                session_target = await _find_session_match(db, item)
                if is_reimport and session_target is None:
                    raise ValueError(
                        "The selected conflict no longer has a unique target"
                    )
                if not is_reimport and session_target is not None:
                    raise ValueError(
                        "This session now conflicts with an existing import; review it again"
                    )
                if session_target is not None:
                    target_ref = str(session_target.id)
                    before_snapshot = json.dumps(
                        await _session_snapshot(db, session_target),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
            else:
                target_path = _target_path_for_item(item)
                target_ref = str(target_path)
                if item.kind == "mcp_server" and target_path.exists():
                    existing_config = json.loads(
                        target_path.read_text(encoding="utf-8")
                    )
                    server_name = item.data.get("name")
                    server_exists = server_name in existing_config.get("servers", {})
                    if server_exists and not is_reimport:
                        raise ValueError(
                            "The MCP server already exists; choose Re-import to replace it"
                        )
                    previous_server = existing_config.get("servers", {}).get(
                        server_name
                    )
                    before_snapshot = json.dumps(
                        {
                            "config_existed": True,
                            "server_existed": server_exists,
                            "server_name": server_name,
                            "server": _sanitize_mcp_value(previous_server)
                            if server_exists
                            else None,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                elif item.kind == "mcp_server":
                    before_snapshot = json.dumps(
                        {
                            "config_existed": False,
                            "server_existed": False,
                            "server_name": item.data.get("name", "imported-server"),
                            "server": None,
                        }
                    )
                elif target_path.exists():
                    if not is_reimport:
                        raise ValueError(
                            "The target already exists; choose Re-import to replace it"
                        )
                    before_snapshot = json.dumps(
                        {"contents": target_path.read_text(encoding="utf-8")},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                elif is_reimport:
                    raise ValueError(
                        "The selected conflict no longer exists; review it again"
                    )

            journal = ImportJobItem(
                id=journal_id,
                job_id=job.id,
                source_item_id=source_item_id,
                kind=item.kind,
                label=item.label,
                operation=operation,
                target_ref=target_ref,
                outcome="pending",
                before_snapshot=before_snapshot,
                created_at=now,
                updated_at=utcnow(),
            )
            db.add(journal)
            await db.commit()

            if item.kind == "session":
                if session_target is None:
                    session_target = await _import_session(db, item, now)
                else:
                    await _replace_session(db, session_target, item, now)
                target_ref = str(session_target.id)
                journal.target_ref = target_ref
                journal.after_fingerprint = await _session_fingerprint(
                    db, session_target
                )
            else:
                _write_import_item(item, now)
                assert target_path is not None
                journal.after_fingerprint = _file_fingerprint(target_path)

            journal.outcome = "imported"
            journal.updated_at = utcnow()
            result.imported[item.kind] = result.imported.get(item.kind, 0) + 1
            result.items.append(
                ImportItemOutcome(
                    source_item_id,
                    item.kind,
                    item.label,
                    operation,
                    "imported",
                    target_ref=target_ref,
                )
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            result.errors.append(
                {
                    "item": item.label,
                    "kind": item.kind,
                    "error": str(exc),
                }
            )
            failed = await db.get(ImportJobItem, journal_id)
            if failed is None:
                failed = ImportJobItem(
                    id=journal_id,
                    job_id=job.id,
                    source_item_id=source_item_id,
                    kind=item.kind,
                    label=item.label,
                    operation=operation,
                    target_ref=target_ref,
                    outcome="failed",
                    reason=str(exc),
                    before_snapshot=before_snapshot,
                    created_at=now,
                    updated_at=utcnow(),
                )
                db.add(failed)
            else:
                failed.outcome = "failed"
                failed.reason = str(exc)
                failed.updated_at = utcnow()
            result.items.append(
                ImportItemOutcome(
                    source_item_id,
                    item.kind,
                    item.label,
                    operation,
                    "failed",
                    str(exc),
                    target_ref,
                )
            )
            await db.commit()

    job.imported_counts = json.dumps(result.imported)
    job.skipped_counts = json.dumps(result.skipped)
    job.error_count = len(result.errors)
    job.completed_at = utcnow()
    if not result.imported:
        job.undo_state = "unavailable"
    await db.commit()
    return result


async def undo_import(db: AsyncSession, job_id: str) -> ImportUndoResult:
    """Undo a journaled job only when each target still matches its import."""
    from sqlmodel import delete

    from app.models.import_job import ImportJob
    from app.models.import_job_item import ImportJobItem

    job = await db.get(ImportJob, job_id)
    if job is None:
        raise ValueError("Import history item not found")
    rows = list(
        (
            await db.execute(
                select(ImportJobItem)
                .where(ImportJobItem.job_id == job_id)
                .order_by(ImportJobItem.created_at, ImportJobItem.id)
            )
        )
        .scalars()
        .all()
    )
    if job.undo_state == "unavailable":
        return ImportUndoResult(job_id=job_id, state="unavailable")
    if job.undo_state == "undone":
        return ImportUndoResult(job_id=job_id, state="undone")

    result = ImportUndoResult(job_id=job_id, state="undone")
    for row in rows:
        if row.outcome == "undone":
            result.undone += 1
            continue
        if row.outcome == "undo_skipped":
            result.skipped += 1
            result.items.append(
                ImportItemOutcome(
                    row.source_item_id,
                    row.kind,
                    row.label,
                    row.operation,
                    "undo_skipped",
                    row.reason,
                    row.target_ref,
                )
            )
            continue
        if row.outcome != "imported":
            continue

        reason: str | None = None
        try:
            if row.kind == "session":
                from uuid import UUID

                from app.models.chat import ChatSession, SessionMessage

                session = (
                    await db.get(ChatSession, UUID(row.target_ref))
                    if row.target_ref
                    else None
                )
                if session is None:
                    reason = "Imported session no longer exists"
                elif await _session_fingerprint(db, session) != row.after_fingerprint:
                    reason = "Session changed after import; left it untouched"
                elif row.operation == "created" and row.kind != "mcp_server":
                    await db.execute(
                        delete(SessionMessage).where(
                            SessionMessage.session_id == session.id
                        )
                    )
                    await db.delete(session)
                else:
                    await _restore_session(
                        db, session, json.loads(row.before_snapshot or "{}")
                    )
            else:
                path = Path(row.target_ref or "")
                if not path.is_file():
                    reason = "Imported file no longer exists"
                elif _file_fingerprint(path) != row.after_fingerprint:
                    reason = "File changed after import; left it untouched"
                elif row.kind == "mcp_server":
                    snapshot = json.loads(
                        row.before_snapshot
                        or '{"config_existed":false,"server_existed":false,"server":null}'
                    )
                    config = json.loads(path.read_text(encoding="utf-8"))
                    servers = config.setdefault("servers", {})
                    server_name = snapshot.get("server_name") or row.label
                    current_server = servers.get(server_name, {})
                    if snapshot.get("server_existed"):
                        previous_server = snapshot.get("server") or {}
                        servers[server_name] = _restore_mcp_sensitive_values(
                            previous_server, current_server
                        )
                    else:
                        servers.pop(server_name, None)

                    if (
                        not snapshot.get("config_existed")
                        and not servers
                        and set(config).issubset({"servers"})
                    ):
                        path.unlink()
                    else:
                        path.write_text(
                            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                elif row.operation == "created":
                    path.unlink()
                    if row.kind == "skill":
                        try:
                            path.parent.rmdir()
                        except OSError:
                            pass
                else:
                    snapshot = json.loads(row.before_snapshot or "{}")
                    path.write_text(snapshot["contents"], encoding="utf-8")
        except Exception as exc:
            reason = str(exc)

        if reason:
            row.outcome = "undo_skipped"
            row.reason = reason
            result.skipped += 1
        else:
            row.outcome = "undone"
            row.reason = None
            result.undone += 1
        row.updated_at = utcnow()
        result.items.append(
            ImportItemOutcome(
                row.source_item_id,
                row.kind,
                row.label,
                row.operation,
                row.outcome,
                row.reason,
                row.target_ref,
            )
        )

    if result.skipped:
        result.state = "partially_undone"
        job.undo_state = "partially_undone"
    else:
        job.undo_state = "undone"
    await db.commit()
    return result


async def _find_session_match(db: AsyncSession, item: ImportItem) -> ChatSession | None:
    if item.source_id:
        exact = await db.execute(
            select(ChatSession).where(
                col(ChatSession.source) == item.source,
                col(ChatSession.source_item_id) == item.source_id,
            )
        )
        existing = exact.scalars().first()
        if existing is not None:
            return existing
    result = await db.execute(
        select(ChatSession).where(
            col(ChatSession.source) == item.source,
            col(ChatSession.title) == item.data.get("title", ""),
        )
    )
    candidates = list(result.scalars().all())
    legacy = [candidate for candidate in candidates if candidate.source_item_id is None]
    if len(legacy) == 1:
        return legacy[0]
    if not item.source_id and len(candidates) == 1:
        return candidates[0]
    return None


async def _session_snapshot(db: AsyncSession, session: ChatSession) -> dict[str, Any]:
    messages = (
        (
            await db.execute(
                select(SessionMessage)
                .where(SessionMessage.session_id == session.id)
                .order_by(SessionMessage.created_at, SessionMessage.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "session": {
            "id": str(session.id),
            "title": session.title,
            "mode": session.mode,
            "source": session.source,
            "source_item_id": session.source_item_id,
            "imported_at": session.imported_at.isoformat()
            if session.imported_at
            else None,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "messages": [
            {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "reasoning_content": message.reasoning_content,
                "tool_calls": message.tool_calls,
                "tool_call_id": message.tool_call_id,
                "name": message.name,
                "extra": message.extra,
                "is_summary": message.is_summary,
                "exclude_from_context": message.exclude_from_context,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


async def _session_fingerprint(db: AsyncSession, session: ChatSession) -> str:
    snapshot = await _session_snapshot(db, session)
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _restore_session(
    db: AsyncSession, session: ChatSession, snapshot: dict[str, Any]
) -> None:
    from uuid import UUID

    from sqlmodel import delete

    values = snapshot["session"]
    session.title = values["title"]
    session.mode = values["mode"]
    session.source = values["source"]
    session.source_item_id = values["source_item_id"]
    session.imported_at = _parse_iso(values["imported_at"])
    session.created_at = _parse_iso(values["created_at"]) or session.created_at
    session.updated_at = _parse_iso(values["updated_at"]) or session.updated_at
    await db.execute(
        delete(SessionMessage).where(SessionMessage.session_id == session.id)
    )
    for raw in snapshot["messages"]:
        db.add(
            SessionMessage(
                id=UUID(raw["id"]),
                session_id=session.id,
                role=raw["role"],
                content=raw["content"],
                reasoning_content=raw["reasoning_content"],
                tool_calls=raw["tool_calls"],
                tool_call_id=raw["tool_call_id"],
                name=raw["name"],
                extra=raw["extra"],
                is_summary=raw["is_summary"],
                exclude_from_context=raw["exclude_from_context"],
                created_at=_parse_iso(raw["created_at"]) or utcnow(),
            )
        )


def _target_path_for_item(item: ImportItem) -> Path:
    from app.core.config import settings

    if item.kind == "agent":
        return (
            Path(settings.EVOFLUX_CONFIG_DIR)
            / "agents"
            / f"{_agent_file_name(item.data.get('name', ''))}.md"
        )
    if item.kind == "skill":
        return (
            Path(settings.SKILLS_DIR)
            / _skill_directory_name(item.data.get("name", ""))
            / "SKILL.md"
        )
    if item.kind == "knowledge":
        filename = item.data.get("filename", "imported-knowledge.md")
        safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")[:200]
        return Path(settings.EVOFLUX_WIKI_DIR) / "sources" / safe_name
    if item.kind == "mcp_server":
        return Path(settings.EVOFLUX_CONFIG_DIR) / "mcp.json"
    raise ValueError(f"No file target for import kind {item.kind}")


def _file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _agent_file_name(raw_name: Any) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw_name or "").strip())
    return name.strip("-_")[:80] or "imported-agent"


def _write_import_item(item: ImportItem, now: datetime) -> None:
    if item.kind == "agent":
        _import_agent(item, now)
    elif item.kind == "skill":
        _import_skill(item, now)
    elif item.kind == "knowledge":
        _import_knowledge(item, now)
    elif item.kind == "mcp_server":
        _import_mcp_server(item, now)
    else:
        raise ValueError(f"Unsupported file import kind {item.kind}")


async def _import_session(
    db: AsyncSession,
    item: ImportItem,
    now: datetime,
) -> ChatSession:
    """Create a ChatSession and its messages from an ImportItem."""
    data = item.data
    created_at = _parse_iso(data.get("created_at")) or now

    session = ChatSession(
        title=data.get("title", "Imported session"),
        mode=data.get("mode", "work"),
        source=item.source,
        source_item_id=item.source_id or None,
        imported_at=now,
        created_at=created_at,
        updated_at=_parse_iso(data.get("updated_at")) or now,
    )
    db.add(session)
    await db.flush()  # get session.id

    for i, msg_data in enumerate(data.get("messages", [])):
        msg = SessionMessage(
            session_id=session.id,
            role=msg_data.get("role", "user"),
            content=msg_data.get("content", ""),
            reasoning_content=msg_data.get("reasoning_content"),
            tool_calls=msg_data.get("tool_calls"),
            tool_call_id=msg_data.get("tool_call_id"),
            name=msg_data.get("name"),
            extra=msg_data.get("extra"),
            is_summary=bool(msg_data.get("is_summary", False)),
            exclude_from_context=bool(msg_data.get("exclude_from_context", False)),
            created_at=_parse_iso(msg_data.get("created_at")) or created_at,
        )
        db.add(msg)

    await db.flush()

    return session


async def _replace_session(
    db: AsyncSession,
    session: ChatSession,
    item: ImportItem,
    now: datetime,
) -> None:
    from sqlmodel import delete

    data = item.data
    session.title = data.get("title", "Imported session")
    session.mode = data.get("mode", session.mode)
    session.source = item.source
    session.source_item_id = item.source_id or session.source_item_id
    session.imported_at = now
    session.created_at = _parse_iso(data.get("created_at")) or session.created_at
    session.updated_at = _parse_iso(data.get("updated_at")) or now
    await db.execute(
        delete(SessionMessage).where(SessionMessage.session_id == session.id)
    )
    for message_data in data.get("messages", []):
        db.add(
            SessionMessage(
                session_id=session.id,
                role=message_data.get("role", "user"),
                content=message_data.get("content", ""),
                reasoning_content=message_data.get("reasoning_content"),
                tool_calls=message_data.get("tool_calls"),
                tool_call_id=message_data.get("tool_call_id"),
                name=message_data.get("name"),
                extra=message_data.get("extra"),
                is_summary=bool(message_data.get("is_summary", False)),
                exclude_from_context=bool(
                    message_data.get("exclude_from_context", False)
                ),
                created_at=_parse_iso(message_data.get("created_at"))
                or session.created_at,
            )
        )
    await db.flush()


def _import_agent(item: ImportItem, now: datetime) -> None:
    """Write an agent .md file with YAML frontmatter."""
    from app.core.config import settings

    agent_dir = Path(settings.EVOFLUX_CONFIG_DIR) / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)

    data = item.data
    name = _agent_file_name(data.get("name", "imported-agent"))
    desc = data.get("description", "")
    instructions = data.get("instructions", "")

    content = f"""---
name: {name}
description: {desc}
source: {item.source}
imported_at: "{now.isoformat()}"
---

{instructions}
"""
    (agent_dir / f"{name}.md").write_text(content, encoding="utf-8")


def _import_skill(item: ImportItem, now: datetime) -> None:
    """Write a skill directory with SKILL.md."""
    from app.core.config import settings
    import yaml

    name = _skill_directory_name(item.data.get("name", ""))
    skill_dir = Path(settings.SKILLS_DIR) / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    data = item.data
    frontmatter = {
        "name": name,
        "description": str(data.get("description") or f"Imported skill: {name}"),
        "source": item.source,
        "imported_at": now.isoformat(),
    }
    source_metadata = data.get("source_metadata")
    if isinstance(source_metadata, dict):
        metadata = {
            str(key): str(value)
            for key, value in source_metadata.items()
            if isinstance(value, (str, int, float, bool))
        }
        if metadata:
            frontmatter["metadata"] = metadata
    for key in (
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
        "disable-model-invocation",
        "user-invocable",
    ):
        if key in data.get("frontmatter", {}):
            frontmatter[key] = data["frontmatter"][key]
    serialized = yaml.safe_dump(
        frontmatter, allow_unicode=True, sort_keys=False
    ).rstrip()
    content = f"---\n{serialized}\n---\n\n{data.get('body', '')}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _skill_directory_name(raw_name: Any) -> str:
    """Return a portable, traversal-safe directory name for an imported skill."""
    name = str(raw_name or "").strip().casefold()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:64].rstrip("-")
    return name or "imported-skill"


def _import_knowledge(item: ImportItem, now: datetime) -> None:
    """Write a knowledge file to the wiki sources directory."""
    from app.core.config import settings

    sources_dir = Path(settings.EVOFLUX_WIKI_DIR) / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    data = item.data
    filename = data.get("filename", "imported-knowledge.md")
    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")[:200]
    (sources_dir / safe_name).write_text(data.get("content", ""), encoding="utf-8")


def _import_mcp_server(item: ImportItem, now: datetime) -> None:
    """Merge an MCP server entry into the config mcp.json."""
    import json as json_mod

    from app.core.config import settings

    mcp_path = Path(settings.EVOFLUX_CONFIG_DIR) / "mcp.json"
    mcp_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if mcp_path.exists():
        try:
            existing = json_mod.loads(mcp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    servers = existing.get("servers", {})
    incoming_server = _sanitize_mcp_value(item.data.get("server", {}))
    server_name = item.data.get("name", "imported-server")
    old_server = servers.get(server_name, {})
    servers[server_name] = _restore_mcp_sensitive_values(incoming_server, old_server)
    existing["servers"] = servers

    mcp_path.write_text(
        json_mod.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


_MCP_SENSITIVE_NAMES = {
    "env",
    "headers",
    "key",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "auth",
}


def _is_sensitive_mcp_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    return normalized in _MCP_SENSITIVE_NAMES or any(
        marker in normalized
        for marker in (
            "apikey",
            "privatekey",
            "accesskey",
            "clientkey",
            "token",
            "secret",
            "password",
            "credential",
            "authorization",
            "auth",
        )
    )


def _sanitize_mcp_value(value: Any) -> Any:
    """Remove credential-bearing MCP fields before storing imported data or journal snapshots."""
    if isinstance(value, dict):
        return {
            key: _sanitize_mcp_value(nested)
            for key, nested in value.items()
            if not _is_sensitive_mcp_name(str(key))
        }
    if isinstance(value, list):
        return [_sanitize_mcp_value(item) for item in value]
    return value


def _restore_mcp_sensitive_values(safe_value: Any, existing_value: Any) -> Any:
    """Keep locally configured credentials from the current MCP entry."""
    if not isinstance(safe_value, dict) or not isinstance(existing_value, dict):
        return safe_value
    result = dict(safe_value)
    for key, old_value in existing_value.items():
        if _is_sensitive_mcp_name(str(key)):
            result[key] = old_value
        elif key in result:
            result[key] = _restore_mcp_sensitive_values(result[key], old_value)
    return result


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ── Job tracking (in-memory for Phase 1) ────────────────────────────────────


def store_bundle(import_id: str, bundle: ImportBundle) -> None:
    _import_jobs[import_id] = bundle


def get_bundle(import_id: str) -> ImportBundle | None:
    return _import_jobs.get(import_id)


def remove_bundle(import_id: str) -> None:
    _import_jobs.pop(import_id, None)
