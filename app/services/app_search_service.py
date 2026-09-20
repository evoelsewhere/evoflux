"""Application-wide Search Everywhere aggregation.

``search_everywhere_service`` answers "what is in this repository?".  This
module answers the other half of the command palette's promise: "what is in
this application?" — sessions, the dialogue inside them, Coding projects and
workspaces, Memory pages, scheduled tasks, agent definitions and skills.

Every source is bounded.  The palette calls this on each keystroke (behind a
debounce), so each source caps both the rows it reads and the rows it returns,
and file-backed sources run in a worker thread so the event loop keeps serving
the chat stream.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, CodingProject, CodingWorkspace, SessionMessage
from app.scheduler.models import ScheduledTask

AppSearchKind = Literal[
    "session",
    "message",
    "project",
    "workspace",
    "memory",
    "scheduled_task",
    "agent",
    "skill",
]

# Rows read per source before filtering. Keeps a keystroke's cost flat on a
# database that has accumulated years of chat history.
SESSION_SCAN_LIMIT = 400
MESSAGE_SCAN_LIMIT = 200
FILE_SCAN_LIMIT = 400

# Rows one source may contribute before the merge starts dropping them.
PER_SOURCE_LIMIT = 25
# Memory scores whole tokens, so it is capped tighter than the substring sources.
MEMORY_LIMIT = 8

EXCERPT_RADIUS = 70

# Markdown scaffolding that carries no meaning once a message is one line.
_MARKDOWN_NOISE = re.compile(r"\*\*|__|~~|`{1,3}|<!--|-->|#{1,6}\s")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# A Memory excerpt runs to 500 characters; a palette row shows far less.
MEMORY_EXCERPT_CHARS = 200


@dataclass(frozen=True, slots=True)
class AppSearchItem:
    """One application-level hit.

    ``session_id`` is the session the palette should open for this row: for a
    message hit that is the top-level session that owns it, not the team
    member's sub-session.  ``path`` carries a Memory page path or an agent /
    skill file path so the UI can open the right editor.
    """

    id: str
    kind: AppSearchKind
    label: str
    description: str
    session_id: str | None = None
    path: str | None = None
    metadata: dict[str, Any] | None = None


async def search_app(
    db: AsyncSession, query: str, *, limit: int = 40
) -> list[AppSearchItem]:
    """Aggregate application-level matches for *query*, one row per source in turn."""
    normalized = query.strip()
    if not normalized:
        return []
    groups = _drop_duplicate_conversations(
        await _parallel_sources(db, normalized, min(limit, PER_SOURCE_LIMIT))
    )
    # Round-robin so one loud source cannot push every other kind past the
    # cap, while a query that only matches sessions still fills the palette.
    items: list[AppSearchItem] = []
    seen: set[str] = set()
    for row in zip_longest(*groups):
        for item in row:
            if item is None or item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
            if len(items) >= limit:
                return items
    return items


def _drop_duplicate_conversations(
    groups: list[list[AppSearchItem]],
) -> list[list[AppSearchItem]]:
    """Keep a chat out of Messages when its own title already matched.

    Both rows open the same chat, so showing them together reads as a
    duplicate rather than as two findings.
    """
    titled = {
        item.session_id
        for group in groups
        for item in group
        if item.kind == "session" and item.session_id
    }
    if not titled:
        return groups
    return [
        [
            item
            for item in group
            if not (item.kind == "message" and item.session_id in titled)
        ]
        for group in groups
    ]


async def _parallel_sources(
    db: AsyncSession, query: str, limit: int
) -> list[list[AppSearchItem]]:
    """Run every source, letting one failure degrade to an empty group.

    Database sources share the caller's session, so they run sequentially —
    an ``AsyncSession`` is not safe for concurrent statements. Filesystem
    sources are offloaded to threads and gathered.
    """
    file_sources = asyncio.gather(
        asyncio.to_thread(_memory_items, query, limit),
        asyncio.to_thread(_agent_items, query, limit),
        asyncio.to_thread(_skill_items, query, limit),
        return_exceptions=True,
    )
    db_groups: list[list[AppSearchItem]] = []
    for source in (
        _session_items,
        _message_items,
        _project_items,
        _workspace_items,
        _scheduled_task_items,
    ):
        try:
            db_groups.append(await source(db, query, limit))
        except Exception as exc:  # noqa: BLE001 — a dead source must not blank the palette
            logger.warning(
                "app_search_source_failed source={} error={}", source.__name__, exc
            )
            db_groups.append([])
    file_groups = await file_sources
    resolved: list[list[AppSearchItem]] = []
    for name, group in zip(
        ("_memory_items", "_agent_items", "_skill_items"), file_groups
    ):
        if isinstance(group, list):
            resolved.append(group)
            continue
        logger.warning("app_search_source_failed source={} error={}", name, group)
        resolved.append([])
    return [*db_groups, *resolved]


def _like_pattern(query: str) -> str:
    """Build the SQL prefilter pattern for *query*.

    Wildcards are escaped so a literal ``%`` or ``_`` matches itself. The
    needle is case-folded in Python because SQLite's ``lower()`` — which
    ``ilike`` compiles to — only folds ASCII: folding "NƠI" here is what lets
    it reach a stored "nơi". The Python re-check on each row then removes the
    rows this looser prefilter let through.
    """
    escaped = (
        query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _matches(needle: str, *fields: str | None) -> bool:
    return any(field and needle in field.casefold() for field in fields)


def _excerpt(content: str, needle: str) -> str:
    """Return a one-line window of *content* around the first match.

    The window is cut from the raw text so the match keeps its position, and
    only the window is stripped of Markdown scaffolding — a palette row full
    of ``**``, backticks and ``##`` reads as noise, not as an answer.
    """
    flat = " ".join(content.split())
    index = flat.casefold().find(needle)
    if index < 0:
        return _plain_text(flat[: EXCERPT_RADIUS * 2])
    start = max(0, index - EXCERPT_RADIUS)
    end = min(len(flat), index + len(needle) + EXCERPT_RADIUS)
    window = _plain_text(flat[start:end])
    return f"{'…' if start else ''}{window}{'…' if end < len(flat) else ''}"


def _plain_text(text: str) -> str:
    """Drop HTML comments, Markdown emphasis, fences and heading markers.

    Memory notes open with an ``evoflux-memory-facts`` comment, so without
    this the first thing a Memory row shows is bookkeeping.
    """
    return _MARKDOWN_NOISE.sub("", _HTML_COMMENT.sub("", text)).strip()


def _session_label(session: ChatSession) -> str:
    return session.title or session.scheduled_task_name or "Untitled chat"


def _session_route(session: ChatSession) -> dict[str, Any]:
    """Everything the UI needs to open *session* under the right shell.

    A Coding session lives at ``/coding/{project_id|workspace}/{id}`` and a
    Work session at ``/{id}``; opening a Coding one on the Work route loads it
    under the wrong chrome, with no workspace and no repository tools.
    """
    return {
        "mode": session.mode,
        "workspace": session.workspace,
        "project_id": str(session.project_id) if session.project_id else None,
    }


def _session_description(session: ChatSession) -> str:
    parts = [session.mode or "work"]
    if session.workspace:
        parts.append(session.workspace.replace("\\", "/").rsplit("/", 1)[-1])
    if session.agent_name:
        parts.append(session.agent_name)
    if session.scheduled_task_name:
        parts.append(f"scheduled · {session.scheduled_task_name}")
    return " · ".join(parts)


# ── Sessions and dialogue ────────────────────────────────────────────────────


async def _session_items(
    db: AsyncSession, query: str, limit: int
) -> list[AppSearchItem]:
    needle = query.casefold()
    pattern = _like_pattern(query)
    stmt = (
        select(ChatSession)
        .where(col(ChatSession.parent_session_id).is_(None))
        .where(col(ChatSession.session_type) != "side_chat")
        .where(
            col(ChatSession.title).ilike(pattern, escape="\\")
            | col(ChatSession.agent_name).ilike(pattern, escape="\\")
            | col(ChatSession.workspace).ilike(pattern, escape="\\")
            | col(ChatSession.scheduled_task_name).ilike(pattern, escape="\\")
        )
        .order_by(col(ChatSession.updated_at).desc())
        .limit(SESSION_SCAN_LIMIT)
    )
    rows = (await db.exec(stmt)).all()
    items: list[AppSearchItem] = []
    for session in rows:
        # ``ilike`` folds ASCII only. Re-check in Python so a Vietnamese or
        # Japanese query keeps the same case-insensitive behaviour it has for
        # ASCII, and drop rows the SQL prefilter let through on case alone.
        if not _matches(
            needle,
            session.title,
            session.agent_name,
            session.workspace,
            session.scheduled_task_name,
        ):
            continue
        items.append(
            AppSearchItem(
                id=f"session:{session.id}",
                kind="session",
                label=_session_label(session),
                description=_session_description(session),
                session_id=str(session.id),
                metadata={
                    **_session_route(session),
                    "updated_at": session.updated_at.isoformat()
                    if session.updated_at
                    else None,
                },
            )
        )
        if len(items) >= limit:
            break
    return items


async def _message_items(
    db: AsyncSession, query: str, limit: int
) -> list[AppSearchItem]:
    needle = query.casefold()
    pattern = _like_pattern(query)
    stmt = (
        select(SessionMessage, ChatSession)
        .join(ChatSession, col(SessionMessage.session_id) == col(ChatSession.id))
        .where(col(SessionMessage.role).in_(("user", "assistant")))
        .where(col(SessionMessage.content).is_not(None))
        .where(col(SessionMessage.content).ilike(pattern, escape="\\"))
        .order_by(col(SessionMessage.created_at).desc())
        .limit(MESSAGE_SCAN_LIMIT)
    )
    rows = (await db.exec(stmt)).all()
    owners: dict[UUID, ChatSession] = {}
    # One row per conversation. Every row here opens the same chat anyway, so
    # a query that appears fifty times in one session used to fill the palette
    # with near-identical rows instead of showing fifty other places to look.
    newest: dict[str, tuple[SessionMessage, ChatSession, ChatSession]] = {}
    hits: Counter[str] = Counter()
    for message, session in rows:
        content = message.content or ""
        if needle not in content.casefold():
            continue
        # A team member's reply lives in a sub-session that the sidebar never
        # lists. Open the lead session that owns it instead.
        owner = session
        parent_id = session.parent_session_id or session.source_session_id
        if parent_id is not None:
            cached = owners.get(parent_id)
            if cached is None:
                cached = await db.get(ChatSession, parent_id)
                if cached is not None:
                    owners[parent_id] = cached
            owner = cached or session
        owner_id = str(owner.id)
        if owner_id not in newest and len(newest) >= limit:
            continue
        hits[owner_id] += 1
        newest.setdefault(owner_id, (message, session, owner))
    items: list[AppSearchItem] = []
    for owner_id, (message, session, owner) in newest.items():
        count = hits[owner_id]
        excerpt = _excerpt(message.content or "", needle)
        # Counts come from the scan window, so say "4+" rather than "4" once
        # the window is full and older messages went unread.
        tally = f"{count}+" if len(rows) >= MESSAGE_SCAN_LIMIT else str(count)
        # The row opens a chat, so the chat is what it is named after; the
        # matched text is the supporting line. A bare excerpt as the title
        # left people guessing what clicking would do.
        items.append(
            AppSearchItem(
                id=f"message:{message.id}",
                kind="message",
                label=_session_label(owner),
                description=f"{tally} matches · {excerpt}" if count > 1 else excerpt,
                session_id=owner_id,
                metadata={
                    **_session_route(owner),
                    "message_id": str(message.id),
                    "role": message.role,
                    "agent_name": session.agent_name,
                    "match_count": count,
                    "excerpt": excerpt,
                    "created_at": message.created_at.isoformat()
                    if message.created_at
                    else None,
                },
            )
        )
    return items


# ── Projects, workspaces and scheduled work ──────────────────────────────────


async def _project_items(
    db: AsyncSession, query: str, limit: int
) -> list[AppSearchItem]:
    needle = query.casefold()
    stmt = select(CodingProject).where(
        ~col(CodingProject.hidden),
        col(CodingProject.deleted_at).is_(None),
    )
    rows = (await db.exec(stmt)).all()
    items = [
        AppSearchItem(
            id=f"project:{project.id}",
            kind="project",
            label=project.name,
            description=project.description or "Coding project",
            metadata={"project_id": str(project.id)},
        )
        for project in rows
        if _matches(needle, project.name, project.description)
    ]
    return items[:limit]


async def _workspace_items(
    db: AsyncSession, query: str, limit: int
) -> list[AppSearchItem]:
    needle = query.casefold()
    stmt = select(CodingWorkspace).where(
        ~col(CodingWorkspace.hidden),
        col(CodingWorkspace.deleted_at).is_(None),
    )
    rows = (await db.exec(stmt)).all()
    items = [
        AppSearchItem(
            id=f"workspace:{workspace.id}",
            kind="workspace",
            label=workspace.name
            or workspace.path.replace("\\", "/").rsplit("/", 1)[-1],
            description=workspace.path,
            path=workspace.path,
            metadata={"workspace": workspace.path, "kind": workspace.kind},
        )
        for workspace in rows
        if _matches(needle, workspace.name, workspace.path)
    ]
    return items[:limit]


async def _scheduled_task_items(
    db: AsyncSession, query: str, limit: int
) -> list[AppSearchItem]:
    needle = query.casefold()
    rows = (await db.exec(select(ScheduledTask))).all()
    items: list[AppSearchItem] = []
    for task in rows:
        if not _matches(needle, task.name, task.prompt, task.cron_expression):
            continue
        schedule = task.cron_expression or (
            f"every {task.every_seconds}s" if task.every_seconds else task.schedule_type
        )
        items.append(
            AppSearchItem(
                id=f"scheduled-task:{task.id}",
                kind="scheduled_task",
                label=task.name,
                description=f"{schedule} · {task.status if task.enabled else 'paused'}",
                metadata={"task_id": str(task.id), "mode": task.mode},
            )
        )
        if len(items) >= limit:
            break
    return items


# ── Filesystem-backed sources ────────────────────────────────────────────────


def _memory_items(query: str, limit: int) -> list[AppSearchItem]:
    from app.services.memory import search_memory_files

    # Memory matches on tokens rather than substrings, so a common word hits
    # most pages. Keep its evidence gate on and take a tighter slice than the
    # other sources, or one broad word buries every other kind.
    results = search_memory_files(
        query, limit=min(limit, MEMORY_LIMIT), scope="all", abstain_weak=True
    )
    return [
        AppSearchItem(
            id=f"memory:{result.path or result.source_ref}",
            kind="memory",
            label=_plain_text(result.title or (result.path or result.source_ref)),
            description=_plain_text(result.excerpt)[:MEMORY_EXCERPT_CHARS]
            or "Memory page",
            path=result.path,
            metadata={"source_ref": result.source_ref},
        )
        for result in results
    ]


def _markdown_description(text: str, fallback: str) -> str:
    """Prefer a definition's frontmatter description, else its first prose line."""
    from app.agent.skills.discovery import parse_frontmatter

    metadata, body = parse_frontmatter(text)
    description = metadata.get("description")
    if isinstance(description, str) and description.strip():
        return " ".join(description.split())[:240]
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:240]
    return fallback


def _agent_items(query: str, limit: int) -> list[AppSearchItem]:
    from app.services.agent_fs import list_agents, read_agent

    needle = query.casefold()
    items: list[AppSearchItem] = []
    for name in list_agents()[:FILE_SCAN_LIMIT]:
        try:
            record = read_agent(name)
        except (OSError, ValueError, FileNotFoundError):
            continue
        if not _matches(needle, name, record.content):
            continue
        items.append(
            AppSearchItem(
                id=f"agent:{name}",
                kind="agent",
                label=name,
                description=_markdown_description(record.content, "Agent definition"),
                path=record.path,
                metadata={"name": name},
            )
        )
        if len(items) >= limit:
            break
    return items


def _skill_items(query: str, limit: int) -> list[AppSearchItem]:
    from app.services.agent_fs import list_skills, read_skill

    needle = query.casefold()
    items: list[AppSearchItem] = []
    for name in list_skills()[:FILE_SCAN_LIMIT]:
        try:
            record = read_skill(name)
        except (OSError, ValueError, FileNotFoundError):
            continue
        if not _matches(needle, name, record.content):
            continue
        items.append(
            AppSearchItem(
                id=f"app-skill:{name}",
                kind="skill",
                label=name,
                description=_markdown_description(record.content, "Agent skill"),
                path=record.path,
                metadata={"name": name},
            )
        )
        if len(items) >= limit:
            break
    return items
