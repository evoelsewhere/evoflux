"""Wiki service — file operations for the wiki knowledge store.

Storage layout (Karpathy LLM Wiki pattern, see ``documents/docs/agent/memory.md``)::

    {EVOFLUX_WIKI_DIR}/
      USER.md          # always injected into system prompt
      INDEX.md         # dream-maintained table of contents
      LOG.md           # dream-maintained chronological log
      LINT.md          # latest lint report (auto-overwritten)
      topics/          # concept pages (abstract ideas)
        {slug}.md
      entities/        # entity pages (people, tools, orgs, products)
        {slug}.md
      sources/         # one-page summaries per ingested source
        {slug}.md
      comparisons/     # comparison pages (X vs Y)
        {slug}.md
      notes/           # agent notes, one file per day (append-only)
        {date}.md

This module is the single source of truth for path validation, frontmatter
parsing, and tree assembly for the wiki system.

Background on the page-type split: ``topics/entities/sources/comparisons``
mirror the structure Karpathy specified in his April 2026 LLM-Wiki gist.
``topics/`` is kept (rather than renamed to ``concepts/``) for backwards
compatibility with existing wikis — the dream prompt treats ``topics/``
as the "concept" page-type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from loguru import logger

from app.core.config import settings

# ── Layout constants ─────────────────────────────────────────────────────────

USER_FILE = "USER.md"  # wiki/USER.md — always injected
INDEX_FILE = "INDEX.md"  # wiki/INDEX.md — dream-maintained TOC
LOG_FILE = "LOG.md"  # wiki/LOG.md — chronological append-only log
LINT_FILE = "LINT.md"  # wiki/LINT.md — most recent lint report
TOPICS_DIR = "topics"  # wiki/topics/{slug}.md (concept pages)
ENTITIES_DIR = "entities"  # wiki/entities/{slug}.md (people, tools, orgs)
SOURCES_DIR = "sources"  # wiki/sources/{slug}.md (one summary per source)
COMPARISONS_DIR = "comparisons"  # wiki/comparisons/{slug}.md (X vs Y)
NOTES_DIR = "notes"  # wiki/notes/{date}.md
MEMORY_WIKI_DIR = "wiki"  # wiki/wiki/{slug}.md (Memory v2 curated/source pages)
IMPORTS_DIR = "imports"  # wiki/imports/{slug}.md (Memory v2 raw imports)

#: Root-level files dream may write to.  USER.md and INDEX.md are protected
#: against deletion; LOG.md and LINT.md are not (the dream agent overwrites
#: LINT.md on every lint pass).
_ROOT_FILES: frozenset[str] = frozenset({USER_FILE, INDEX_FILE, LOG_FILE, LINT_FILE})

#: All subdirectories where dream may write knowledge files.  ``notes/`` is
#: separate — it's the *input* side (agent/user log) and not part of the
#: knowledge graph the dream agent maintains.
_KNOWLEDGE_DIRS: tuple[str, ...] = (
    MEMORY_WIKI_DIR,
    TOPICS_DIR,
    ENTITIES_DIR,
    SOURCES_DIR,
    COMPARISONS_DIR,
)

#: Every subdirectory that may appear as the first path component.
_VALID_SUBDIRS: frozenset[str] = frozenset((*_KNOWLEDGE_DIRS, IMPORTS_DIR, NOTES_DIR))

#: Default content for USER.md on first seed.
DEFAULT_USER_FILE = """\
identity: {}
preferences: []
working_style: []
projects: []
"""

#: Frontmatter delimiter pattern — matches ``---\n<yaml>\n---\n`` at start of file.
_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)


# ── Data types ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WikiFileInfo:
    """Metadata for a single wiki file surfaced in the tree view."""

    path: str  # relative to EVOFLUX_WIKI_DIR, e.g. "topics/auth.md"
    description: str  # from frontmatter, or "" for system files
    updated: str | None  # ISO date string or None
    tags: tuple[str, ...] = ()  # from frontmatter ``tags`` list
    #: ``high|medium|low`` from frontmatter, or ``None`` when unspecified.
    #: A Karpathy-pattern signal that lets the UI surface uncertain knowledge
    #: and lets the dream lint operation flag low-confidence pages for review.
    confidence: str | None = None
    #: Source-of-record list (e.g. ``["session-a1b2c3d4", "note-2026-05-17"]``).
    #: Drives traceability so a user reading a topic can see which conversations
    #: contributed.  Empty tuple when no sources are declared.
    sources: tuple[str, ...] = ()


@dataclass
class WikiTree:
    """Structured view of the wiki store for UI and prompt injection.

    Each knowledge category gets its own list so the frontend can render
    them under separate headers (topics / entities / sources / comparisons)
    instead of one flat list.
    """

    system: list[WikiFileInfo] = field(default_factory=list)
    notes: list[WikiFileInfo] = field(default_factory=list)
    imports: list[WikiFileInfo] = field(default_factory=list)
    wiki: list[WikiFileInfo] = field(default_factory=list)
    topics: list[WikiFileInfo] = field(default_factory=list)
    entities: list[WikiFileInfo] = field(default_factory=list)
    sources: list[WikiFileInfo] = field(default_factory=list)
    comparisons: list[WikiFileInfo] = field(default_factory=list)


@dataclass(frozen=True)
class WikiFileContent:
    """Raw file contents plus structural metadata."""

    path: str
    content: str
    description: str
    updated: str | None
    tags: tuple[str, ...] = ()
    confidence: str | None = None
    sources: tuple[str, ...] = ()


# ── Root resolution ──────────────────────────────────────────────────────────


def wiki_root() -> Path:
    """Return the absolute wiki root directory, creating it if missing."""
    root = Path(settings.EVOFLUX_WIKI_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── Path validation ──────────────────────────────────────────────────────────


class WikiPathError(ValueError):
    """Raised when a relative wiki path is invalid or unsafe."""


def validate_wiki_path(rel_path: str) -> Path:
    """Validate *rel_path* and return its resolved absolute path under EVOFLUX_WIKI_DIR.

    Rules:
      - ``USER.md``, ``INDEX.md``, ``LOG.md``, and ``LINT.md`` are valid at root level.
      - Knowledge dirs and ``notes/*.md`` are valid at one path segment deep.
      - No path traversal; must stay inside wiki root.
      - Must end in ``.md``.
    """
    if not rel_path:
        raise WikiPathError("Wiki path must not be empty.")
    if rel_path.startswith(("/", "~")):
        raise WikiPathError(f"Wiki path must be relative: {rel_path}")

    p = Path(rel_path)
    if p.is_absolute():
        raise WikiPathError(f"Wiki path must be relative: {rel_path}")

    if p.suffix != ".md":
        raise WikiPathError(f"Wiki files must be Markdown (.md): {rel_path}")

    # Reject traversal segments in the raw string before Path normalises them away.
    # Path("topics/./test.md").parts == ("topics", "test.md") — dot is silently
    # dropped, so we must check the raw string components, not p.parts.
    raw_parts = rel_path.replace("\\", "/").split("/")
    if any(part in ("..", ".") for part in raw_parts):
        raise WikiPathError(f"Wiki path may not contain '..' or '.': {rel_path}")

    parts = p.parts
    # Root-level files: USER.md, INDEX.md, LOG.md, LINT.md
    if len(parts) == 1:
        if rel_path not in _ROOT_FILES:
            allowed = ", ".join(sorted(_ROOT_FILES))
            raise WikiPathError(
                f"Only {allowed} are valid at wiki root level: {rel_path}"
            )
    elif len(parts) == 2:
        if parts[0] not in _VALID_SUBDIRS:
            allowed = ", ".join(sorted(_VALID_SUBDIRS))
            raise WikiPathError(
                f"Wiki subdir must be one of [{allowed}]: got {parts[0]!r}"
            )
    else:
        raise WikiPathError(f"Wiki path too deep (max 2 components): {rel_path}")

    root = wiki_root()
    candidate = root / p
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WikiPathError(f"Wiki path escapes root: {rel_path}") from exc
    return resolved


# ── Frontmatter parsing ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedMarkdown:
    description: str
    updated: str | None
    tags: tuple[str, ...]
    body: str
    raw: str
    confidence: str | None = None
    sources: tuple[str, ...] = ()


_VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})


def parse_frontmatter(raw: str) -> ParsedMarkdown:
    """Parse YAML frontmatter from *raw*.

    Returns a :class:`ParsedMarkdown` with empty fields when no frontmatter
    is present.  Recognised keys (all optional):

    - ``description`` — one-sentence summary
    - ``tags`` — list of strings, normalised to lowercase
    - ``updated`` — ISO date string or YAML date
    - ``confidence`` — one of ``high|medium|low`` (case-insensitive, others ignored)
    - ``sources`` — list of source slugs (e.g. ``session-a1b2c3d4``)
    """
    empty = ParsedMarkdown(
        description="",
        updated=None,
        tags=(),
        body=raw,
        raw=raw,
        confidence=None,
        sources=(),
    )
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return empty
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return empty

    if not isinstance(data, dict):
        return empty

    description = str(data.get("description", "")).strip()
    updated_val = data.get("updated")
    updated: str | None
    if isinstance(updated_val, (date, datetime)):
        updated = updated_val.isoformat()
    elif isinstance(updated_val, str):
        updated = updated_val.strip() or None
    else:
        updated = None

    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        tags: tuple[str, ...] = tuple(
            str(t).strip().lower() for t in raw_tags if str(t).strip()
        )
    else:
        tags = ()

    raw_confidence = data.get("confidence")
    if isinstance(raw_confidence, str):
        normalised = raw_confidence.strip().lower()
        confidence = normalised if normalised in _VALID_CONFIDENCE else None
    else:
        confidence = None

    raw_sources = data.get("sources")
    if isinstance(raw_sources, list):
        sources: tuple[str, ...] = tuple(
            str(s).strip() for s in raw_sources if str(s).strip()
        )
    else:
        sources = ()

    body = m.group(2).lstrip("\n")
    return ParsedMarkdown(
        description=description,
        updated=updated,
        tags=tags,
        body=body,
        raw=raw,
        confidence=confidence,
        sources=sources,
    )


# ── Tree listing ─────────────────────────────────────────────────────────────


def _file_info(rel: str, raw: str) -> WikiFileInfo:
    """Build a :class:`WikiFileInfo` from a raw file's contents."""
    parsed = parse_frontmatter(raw)
    return WikiFileInfo(
        path=rel,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


def _list_subdir(subdir: str) -> list[WikiFileInfo]:
    root = wiki_root() / subdir
    if not root.is_dir():
        return []
    infos: list[WikiFileInfo] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        rel = f"{subdir}/{entry.name}"
        try:
            raw = entry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("wiki_read_failed path={} error={}", rel, exc)
            infos.append(WikiFileInfo(path=rel, description="", updated=None))
            continue
        infos.append(_file_info(rel, raw))
    return infos


def list_tree(*, unprocessed_notes: set[str] | None = None) -> WikiTree:
    """Return the current wiki tree grouped by section.

    Args:
      unprocessed_notes: When provided, only notes whose filename is in this
        set are included.  Pass ``None`` (default) to include all notes.

    Returns:
      A :class:`WikiTree` with the full knowledge-graph view:

      - ``system`` — root files (``USER.md``, ``INDEX.md``, ``LOG.md``, ``LINT.md``)
      - ``wiki`` — Memory v2 curated/source-compiled pages
      - ``topics`` / ``entities`` / ``sources`` / ``comparisons`` — legacy knowledge pages
      - ``imports`` / ``notes`` — raw memory inputs, optionally filtered to unprocessed
    """
    root = wiki_root()
    system: list[WikiFileInfo] = []

    # Root files in a stable, user-friendly order.
    for root_file in (USER_FILE, INDEX_FILE, LOG_FILE, LINT_FILE):
        path = root / root_file
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("wiki_read_failed path={} error={}", root_file, exc)
            raw = ""
        system.append(_file_info(root_file, raw))

    all_notes = _list_subdir(NOTES_DIR)
    if unprocessed_notes is not None:
        notes = [n for n in all_notes if Path(n.path).name in unprocessed_notes]
    else:
        notes = all_notes

    return WikiTree(
        system=system,
        wiki=_list_subdir(MEMORY_WIKI_DIR),
        topics=_list_subdir(TOPICS_DIR),
        entities=_list_subdir(ENTITIES_DIR),
        sources=_list_subdir(SOURCES_DIR),
        comparisons=_list_subdir(COMPARISONS_DIR),
        imports=_list_subdir(IMPORTS_DIR),
        notes=notes,
    )


# ── File CRUD ────────────────────────────────────────────────────────────────


def read_file(rel_path: str) -> WikiFileContent:
    """Read a wiki file and return its raw contents + parsed metadata."""
    resolved = validate_wiki_path(rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Wiki file not found: {rel_path}")
    raw = resolved.read_text(encoding="utf-8")
    parsed = parse_frontmatter(raw)
    return WikiFileContent(
        path=rel_path,
        content=raw,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


def write_file(rel_path: str, content: str) -> WikiFileContent:
    """Create or overwrite a wiki file."""
    resolved = validate_wiki_path(rel_path)
    parsed = parse_frontmatter(content)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    logger.info(
        "wiki_file_written path={} bytes={}", rel_path, len(content.encode("utf-8"))
    )
    return WikiFileContent(
        path=rel_path,
        content=content,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


#: Files that may not be deleted via the wiki API — overwrite instead.
#: ``USER.md`` and ``INDEX.md`` carry irreplaceable state.  ``LOG.md`` is
#: append-only audit log; deleting it loses history.  ``LINT.md`` *can* be
#: deleted (it's regenerated on every lint pass) — by design.
_PROTECTED_FILES: frozenset[str] = frozenset({USER_FILE, INDEX_FILE, LOG_FILE})


def delete_file(rel_path: str) -> None:
    """Delete a wiki file.  USER.md, INDEX.md, and LOG.md cannot be deleted."""
    resolved = validate_wiki_path(rel_path)
    if rel_path in _PROTECTED_FILES:
        raise WikiPathError(
            f"Refusing to delete protected wiki file: {rel_path}. "
            "Overwrite the contents instead."
        )
    if not resolved.exists():
        raise FileNotFoundError(f"Wiki file not found: {rel_path}")
    resolved.unlink()
    logger.info("wiki_file_deleted path={}", rel_path)


# ── LOG.md append helper ─────────────────────────────────────────────────────


def append_log(entry: str) -> Path:
    """Append a single entry to ``wiki/LOG.md``.

    ``entry`` is the body text of the entry.  This helper prepends a
    machine-greppable header line of the form::

        ## [YYYY-MM-DD HH:MM UTC] <entry first line>

    The grep prefix is deliberately stable so users can introspect history
    with ``grep '^## \\[' LOG.md`` — matching Karpathy's recommended pattern.

    Returns the resolved path.  The file is created if missing with a brief
    explanatory header.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    first_line = entry.strip().splitlines()[0] if entry.strip() else "(empty)"

    body_lines = entry.strip().splitlines()
    # Header line gets the first non-empty body line for grep parsability;
    # the rest of the entry is indented below as plain markdown.
    rest = "\n".join(body_lines[1:]) if len(body_lines) > 1 else ""

    block = f"## [{timestamp}] {first_line}\n"
    if rest:
        block += f"\n{rest}\n"
    block += "\n"

    root = wiki_root()
    dest = root / LOG_FILE
    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        dest.write_text(existing + block, encoding="utf-8")
    else:
        # Bootstrap header so a first-time reader knows what this file is.
        header = (
            "# Wiki Log\n\n"
            "Chronological append-only record of dream activity.  Each entry "
            "is parseable with `grep '^## \\['`.\n\n"
        )
        dest.write_text(header + block, encoding="utf-8")
    logger.info("wiki_log_appended bytes={}", len(block.encode("utf-8")))
    return dest


# ── Note helper ──────────────────────────────────────────────────────────────


def write_note(content: str) -> Path:
    """Append one note entry to ``wiki/notes/{date}.md``.

    All notes for the same day share one file. Each call appends a
    ``## HH:MM UTC`` header so entries remain readable.
    No frontmatter — plain markdown logs.

    Returns the resolved path.
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%H:%M UTC")
    filename = f"{today}.md"
    root = wiki_root()
    notes_dir = root / NOTES_DIR
    notes_dir.mkdir(parents=True, exist_ok=True)
    dest = notes_dir / filename

    entry = f"## {timestamp}\n\n{content.strip()}\n"

    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        dest.write_text(existing + "\n" + entry, encoding="utf-8")
        logger.info(
            "wiki_note_appended path={} bytes={}", dest, len(content.encode("utf-8"))
        )
    else:
        dest.write_text(entry, encoding="utf-8")
        logger.info(
            "wiki_note_written path={} bytes={}", dest, len(content.encode("utf-8"))
        )
    return dest
