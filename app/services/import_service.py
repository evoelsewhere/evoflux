"""Import orchestrator — detect, preview, execute.

Reads a local path, auto-detects the source format, runs the correct parser,
and writes accepted items through existing EvoFlux services.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.chat import ChatSession, SessionMessage
from app.services.importers.base import ImportBundle, ImportItem, ImportResult, utcnow
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
    """Check each item in *bundle* against existing data and annotate conflicts.

    Mutates items in-place (sets ``conflicts`` and ``action``) and returns the
    bundle for chaining.
    """
    for item in bundle.items:
        if item.kind == "session":
            await _check_session_conflict(db, item)
        elif item.kind == "agent":
            _check_agent_conflict(item)
        elif item.kind == "skill":
            _check_skill_conflict(item)
        # Other kinds: no conflict detection in Phase 1

    return bundle


async def _check_session_conflict(db: AsyncSession, item: ImportItem) -> None:
    """Check if a session with the same source_id already exists."""
    stmt = select(ChatSession).where(
        col(ChatSession.source) == item.source,
        col(ChatSession.title) == item.data.get("title"),
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing is not None:
        item.conflicts.append(
            f"Session '{item.data.get('title')}' already imported (id={existing.id})"
        )
        item.action = "skip"


def _check_agent_conflict(item: ImportItem) -> None:
    """Check if an agent file with the same name exists."""
    from app.core.config import settings

    agent_file = (
        Path(settings.EVOFLUX_CONFIG_DIR) / "agents" / f"{item.data.get('name', '')}.md"
    )
    if agent_file.exists():
        item.conflicts.append(f"Agent file already exists: {agent_file}")
        item.action = "skip"


def _check_skill_conflict(item: ImportItem) -> None:
    """Check if a skill directory with the same name exists."""
    from app.core.config import settings

    skill_dir = Path(settings.EVOFLUX_CONFIG_DIR) / "skills" / item.data.get("name", "")
    if skill_dir.exists():
        item.conflicts.append(f"Skill directory already exists: {skill_dir}")
        item.action = "skip"


# ── Execution ───────────────────────────────────────────────────────────────


async def execute_import(
    db: AsyncSession,
    bundle: ImportBundle,
) -> ImportResult:
    """Write accepted items into EvoFlux data stores.

    Returns an :class:`ImportResult` with counts per kind.
    """
    result = ImportResult()
    now = utcnow()

    for item in bundle.items:
        if item.action == "skip":
            result.skipped[item.kind] = result.skipped.get(item.kind, 0) + 1
            continue

        try:
            if item.kind == "session":
                await _import_session(db, item, now)
            elif item.kind == "agent":
                _import_agent(item, now)
            elif item.kind == "skill":
                _import_skill(item, now)
            elif item.kind == "knowledge":
                _import_knowledge(item, now)
            elif item.kind == "mcp_server":
                _import_mcp_server(item, now)
            else:
                # Not yet implemented — skip silently
                result.skipped[item.kind] = result.skipped.get(item.kind, 0) + 1
                continue

            result.imported[item.kind] = result.imported.get(item.kind, 0) + 1
        except Exception as exc:
            result.errors.append(
                {
                    "item": item.label,
                    "kind": item.kind,
                    "error": str(exc),
                }
            )

    await db.commit()

    # Record import job in history
    import json as json_mod
    import uuid

    from app.models.import_job import ImportJob

    job = ImportJob(
        id=uuid.uuid4().hex[:32],
        source=bundle.source,
        source_path=bundle.metadata.get("source_path", ""),
        detected_format=bundle.detected_format,
        status="completed",
        imported_counts=json_mod.dumps(result.imported),
        skipped_counts=json_mod.dumps(result.skipped),
        error_count=len(result.errors),
        item_count=len(bundle.items),
        created_at=now,
        completed_at=utcnow(),
    )
    db.add(job)
    await db.commit()

    return result


async def _import_session(
    db: AsyncSession,
    item: ImportItem,
    now: datetime,
) -> None:
    """Create a ChatSession and its messages from an ImportItem."""
    data = item.data
    created_at = _parse_iso(data.get("created_at")) or now

    session = ChatSession(
        title=data.get("title", "Imported session"),
        mode=data.get("mode", "work"),
        source=item.source,
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
            created_at=_parse_iso(msg_data.get("created_at")) or created_at,
        )
        db.add(msg)

    await db.flush()


def _import_agent(item: ImportItem, now: datetime) -> None:
    """Write an agent .md file with YAML frontmatter."""
    from app.core.config import settings

    agent_dir = Path(settings.EVOFLUX_CONFIG_DIR) / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)

    data = item.data
    name = data.get("name", "imported-agent")
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

    skill_dir = (
        Path(settings.EVOFLUX_CONFIG_DIR)
        / "skills"
        / item.data.get("name", "imported-skill")
    )
    skill_dir.mkdir(parents=True, exist_ok=True)

    data = item.data
    content = f"""---
name: {data.get("name", "imported-skill")}
description: {data.get("description", "")}
source: {item.source}
imported_at: "{now.isoformat()}"
---

{data.get("body", "")}
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


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

    existing: dict[str, Any] = {}
    if mcp_path.exists():
        try:
            existing = json_mod.loads(mcp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    servers = existing.get("servers", {})
    server_data = item.data.get("server", {})
    server_name = item.data.get("name", "imported-server")
    servers[server_name] = server_data
    existing["servers"] = servers

    mcp_path.write_text(
        json_mod.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
