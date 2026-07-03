"""mark_chapter — agent tool to create a named session chapter.

Persists a SessionChapter row and emits a chapter_created SSE event so
the frontend SessionTOC refreshes in real time without polling.
"""

from __future__ import annotations

from typing import Annotated, Any

from app.agent.tools.registry import InjectedArg, Tool


async def _mark_chapter(
    title: str,
    summary: str | None = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Mark the start of a new chapter in this session.

    Call this when the work shifts to a meaningfully different phase — e.g.
    after finishing exploration and starting implementation, or when the user
    pivots to an unrelated topic. The chapter title appears in the session
    table of contents so users can navigate long sessions easily.

    Args:
        title: Short noun-phrase title for the chapter (under 60 chars).
            Examples: "Codebase exploration", "Auth bug fix", "Test verification".
        summary: Optional one-line description of what this chapter covers.
    """
    from uuid import UUID

    from loguru import logger

    from app.agent.schemas.events import ChapterCreatedEvent
    from app.core.db import async_session_factory
    from app.models.chat import SessionChapter
    from app.services import memory_stream_store as stream_store
    from app.services.stream_envelope import StreamEnvelope

    session_id: str | None = (
        _state.metadata.get("session_id") if _state is not None else None
    )

    if not session_id:
        return "Chapter marked (no session context — skipping persistence)."

    chapter = SessionChapter(
        session_id=UUID(session_id),
        title=title[:255],
        summary=summary,
    )

    try:
        async with async_session_factory() as db:
            db.add(chapter)
            await db.commit()
            await db.refresh(chapter)
    except Exception as exc:
        logger.warning("mark_chapter: db error session={} err={}", session_id, exc)
        return f"Chapter '{title}' could not be saved: {exc}"

    chapter_id = str(chapter.id)
    event = ChapterCreatedEvent(
        chapter_id=chapter_id,
        session_id=session_id,
        title=chapter.title,
        summary=chapter.summary,
        message_id=None,
    )
    await stream_store.push_event(session_id, StreamEnvelope.from_event(event))

    logger.info(
        "mark_chapter session={} chapter={} title={}",
        session_id,
        chapter_id,
        title,
    )
    return f"Chapter '{title}' created."


mark_chapter = Tool(
    _mark_chapter,
    name="mark_chapter",
    description=(
        "Mark the start of a new chapter in the session with a short title. "
        "Adds a divider to the session table of contents so users can jump "
        "between topics. Call when work shifts to a meaningfully different phase."
    ),
)
