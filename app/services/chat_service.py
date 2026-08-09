import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, NamedTuple
from uuid import UUID

from loguru import logger
from sqlmodel import and_, col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from pydantic import TypeAdapter

from app.agent.multimodal import build_parts_from_metas
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    HumanMessage,
    ToolMessage,
)
from app.core.paths import session_workspace_dir
from app.models.chat import ChatSession, SessionMessage
from app.services import snapshot_service


@dataclass(slots=True)
class BoundaryShift:
    """Result of moving the session's revert boundary."""

    applied: bool
    target: SessionMessage | None = None
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


_chat_message_adapter: TypeAdapter[ChatMessage] = TypeAdapter(ChatMessage)


async def create_chat_session(
    db: AsyncSession,
    title: str | None = None,
    parent_session_id: UUID | None = None,
    agent_name: str | None = None,
) -> ChatSession:
    """Creates a new chat session.

    Args:
        db: Async database session.
        title: Optional human-readable title.
        parent_session_id: If set, links this session as a child of another
            (e.g. a subagent session within a supervisor run).
        agent_name: Name of the agent that owns this session.
    """
    logger.debug("creating_chat_session title={} agent_name={}", title, agent_name)
    try:
        session = ChatSession(
            title=title,
            parent_session_id=parent_session_id,
            agent_name=agent_name,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        logger.info("chat_session_created session_id={} title={}", session.id, title)
        return session
    except Exception as e:
        logger.error("chat_session_creation_failed error={} title={}", e, title)
        raise


_INTERRUPTED_TOOL_RESULT = (
    "Tool execution was interrupted before a result could be recorded."
)
USER_SHELL_LLM_CONTENT = "The following tool was executed by the user"


async def heal_orphaned_tool_calls(db: AsyncSession, session_id: UUID) -> int:
    """Insert synthetic ``ToolMessage`` rows for unmatched visible tool_calls.

    Background — the agent loop persists the assistant turn (with
    ``tool_calls``) *before* tools run, so a server restart mid-tool
    leaves an assistant message whose ``tool_calls`` have no following
    ``tool`` rows.  The next turn would then 400 against any provider
    that enforces the assistant→tool pairing (OpenAI, Anthropic, …)::

        No tool output found for function call fc_…

    Heal strategy: inspect every *visible* assistant message in the same
    LLM-facing window as :func:`get_messages_for_llm`.  If an assistant row
    has ``tool_calls``, look up which IDs are already paired with visible
    ``tool`` replies and INSERT a stub for any that are missing.  The stub
    sits in the same DB transaction as the caller, so the heal lands
    atomically with the next user message.

    Earlier versions only inspected the latest assistant row.  That missed
    compacted sessions where ``[latest_summary] + keep_last_n`` exposed an
    older orphan before the current tail, causing OpenAI to reject the full
    request even though the last assistant message looked healthy.

    Returns the number of synthetic rows inserted (``0`` in the healthy
    case).  Caller is responsible for the commit.
    """
    boundary = await _revert_boundary(db, session_id)
    summary_stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.is_summary))
        .where(~col(SessionMessage.exclude_from_context))
    )
    summary_stmt = (
        _before_boundary(summary_stmt, boundary)
        .order_by(
            col(SessionMessage.created_at).desc(),
            col(SessionMessage.id).desc(),
        )
        .limit(1)
    )
    latest_summary = (await db.exec(summary_stmt)).first()

    if latest_summary is None:
        db_messages = list(
            (await db.exec(_visible_messages_stmt(session_id, boundary))).all()
        )
    else:
        rest_stmt = _visible_messages_stmt(session_id, boundary).where(
            ~col(SessionMessage.is_summary)
        )
        db_messages = [latest_summary] + list((await db.exec(rest_stmt)).all())

    assistant_rows = [
        row for row in db_messages if row.role == "assistant" and row.tool_calls
    ]
    if not assistant_rows:
        return 0

    expected_ids: list[str] = []
    for row in assistant_rows:
        expected_ids.extend(tc["id"] for tc in row.tool_calls or [] if tc.get("id"))
    if not expected_ids:
        return 0

    matched_ids = {
        row.tool_call_id
        for row in db_messages
        if row.role == "tool" and row.tool_call_id in expected_ids
    }
    missing_by_row: list[tuple[SessionMessage, list[dict]]] = []
    for row in assistant_rows:
        missing = [tc for tc in row.tool_calls or [] if tc.get("id") not in matched_ids]
        if missing:
            missing_by_row.append((row, missing))

    if not missing_by_row:
        return 0

    # Anchor synthetic timestamps so LLM order stays
    # ``assistant{tool_calls} → tool (synth) → … → next message``.
    # Prefer a slot strictly before the next chronological row — a bare
    # ``+1µs`` is not enough when SQLite/Windows collapses sub-ms precision
    # and ``ORDER BY (created_at, id)`` then parks a fresh UUID7 stub after
    # later same-tick user/assistant rows.
    healed_ids: list[str] = []
    for row, missing in missing_by_row:
        next_row = (
            await db.exec(
                select(SessionMessage)
                .where(col(SessionMessage.session_id) == session_id)
                .where(
                    or_(
                        col(SessionMessage.created_at) > row.created_at,
                        and_(
                            col(SessionMessage.created_at) == row.created_at,
                            col(SessionMessage.id) > row.id,
                        ),
                    )
                )
                .order_by(
                    col(SessionMessage.created_at).asc(),
                    col(SessionMessage.id).asc(),
                )
                .limit(1)
            )
        ).first()
        for i, tc in enumerate(missing):
            stub = ToolMessage(
                content=_INTERRUPTED_TOOL_RESULT,
                tool_call_id=tc["id"],
                name=tc.get("function", {}).get("name", "unknown"),
            )
            if next_row is not None and next_row.created_at > row.created_at:
                gap = next_row.created_at - row.created_at
                stub_at = row.created_at + (gap * (i + 1)) / (len(missing) + 1)
            else:
                # Tail orphan, or same-timestamp successor: step forward in
                # whole milliseconds so the stub stays ahead of later rows
                # even when sub-ms timestamps are truncated.
                stub_at = row.created_at + timedelta(milliseconds=i + 1)
            await save_message(
                db,
                session_id,
                stub,
                created_at=stub_at,
            )
            healed_ids.append(tc["id"])

    logger.warning(
        "tool_call_orphans_healed session_id={} count={} ids=[{}]",
        session_id,
        len(healed_ids),
        ", ".join(healed_ids),
    )
    return len(healed_ids)


async def save_message(
    db: AsyncSession,
    session_id: UUID,
    message: ChatMessage,
    *,
    is_summary: bool = False,
    is_hidden: bool = False,
    exclude_from_context: bool | None = None,
    extra: dict | None = None,
    created_at: datetime | None = None,
) -> SessionMessage:
    """Saves a ChatMessage to the database.

    Args:
        db: Async database session.
        session_id: The session to attach the message to.
        message: The chat message to persist.
        is_summary: When ``True`` this message is a conversation summary
            (produced by :class:`~app.hooks.summarization.SummarizationHook`).
        is_hidden: Deprecated alias for ``exclude_from_context``.
        exclude_from_context: When ``True`` this message is excluded from the
            LLM context window but retained for audit / history.
        created_at: Optional explicit timestamp.  Defaults to ``utcnow()``
            via the model's Field default.  Used by
            :func:`heal_orphaned_tool_calls` to anchor synthetic tool
            replies immediately after the orphaned assistant message
            (so the LLM sees ``assistant{tool_calls} → tool → user``,
            not ``assistant{tool_calls} → user → tool``).
    """
    # Me support both old and new param names during transition
    _exclude = exclude_from_context if exclude_from_context is not None else is_hidden
    logger.debug(
        "saving_message session_id={} role={} content_length={} is_summary={} exclude_from_context={}",
        session_id,
        message.role,
        len(message.content or ""),
        is_summary,
        _exclude,
    )

    tool_calls = None
    tool_call_id = None
    name = None
    reasoning_content = None

    if isinstance(message, AssistantMessage):
        reasoning_content = message.reasoning_content
        if message.tool_calls:
            tool_calls = [tc.model_dump() for tc in message.tool_calls]
            logger.debug(
                "assistant_message_has_tool_calls session_id={} count={}",
                session_id,
                len(tool_calls),
            )
    elif isinstance(message, ToolMessage):
        tool_call_id = message.tool_call_id
        name = message.name
        logger.debug(
            "tool_message_with_result session_id={} tool={} id={}",
            session_id,
            name,
            tool_call_id,
        )

    try:
        kwargs: dict = dict(
            session_id=session_id,
            role=message.role,
            content=message.content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
            is_summary=is_summary,
            exclude_from_context=_exclude,
            extra=extra,
        )
        if created_at is not None:
            kwargs["created_at"] = created_at
        db_message = SessionMessage(**kwargs)
        db.add(db_message)
        await db.flush()
        logger.debug(
            "message_saved session_id={} message_id={} role={}",
            session_id,
            db_message.id,
            message.role,
        )
        return db_message
    except Exception as e:
        logger.error(
            "message_save_failed session_id={} role={} error={}",
            session_id,
            message.role,
            e,
        )
        raise


def _revert_message_id(session: ChatSession | None) -> UUID | None:
    value = session.revert if session else None
    if not isinstance(value, dict):
        return None
    raw = value.get("message_id")
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def _revert_boundary(db: AsyncSession, session_id: UUID) -> SessionMessage | None:
    session = await db.get(ChatSession, session_id)
    message_id = _revert_message_id(session)
    if message_id is None:
        return None
    row = await db.get(SessionMessage, message_id)
    if row is None or row.session_id != session_id:
        return None
    return row


def _before_boundary(stmt, boundary: SessionMessage | None):
    """Restrict *stmt* to rows strictly before the revert boundary.

    Order is ``(created_at, id)`` so rows that share a timestamp with the
    boundary still total-order correctly (common when several messages are
    flushed in the same tick).
    """
    if boundary is None:
        return stmt
    return stmt.where(
        or_(
            col(SessionMessage.created_at) < boundary.created_at,
            and_(
                col(SessionMessage.created_at) == boundary.created_at,
                col(SessionMessage.id) < boundary.id,
            ),
        )
    )


def _after_boundary(stmt, boundary: SessionMessage):
    """Restrict *stmt* to rows strictly after the revert boundary."""
    return stmt.where(
        or_(
            col(SessionMessage.created_at) > boundary.created_at,
            and_(
                col(SessionMessage.created_at) == boundary.created_at,
                col(SessionMessage.id) > boundary.id,
            ),
        )
    )


def _on_or_after_boundary(stmt, boundary: SessionMessage):
    """Restrict *stmt* to the boundary row and everything after it."""
    return stmt.where(
        or_(
            col(SessionMessage.created_at) > boundary.created_at,
            and_(
                col(SessionMessage.created_at) == boundary.created_at,
                col(SessionMessage.id) >= boundary.id,
            ),
        )
    )


def _visible_messages_stmt(
    session_id: UUID, boundary: SessionMessage | None = None
):
    """Base query: all LLM-visible messages for a session, oldest first.

    ``exclude_from_context`` is the LLM-context flag. UI-only hiding uses
    ``extra.hidden_from_user`` and is applied after deserialization.
    """
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(~col(SessionMessage.exclude_from_context))
    )
    return _before_boundary(stmt, boundary).order_by(
        col(SessionMessage.created_at).asc(),
        col(SessionMessage.id).asc(),
    )


def _history_messages_stmt(
    session_id: UUID, boundary: SessionMessage | None = None
):
    stmt = select(SessionMessage).where(col(SessionMessage.session_id) == session_id)
    if boundary is not None:
        stmt = _before_boundary(stmt, boundary)
    return stmt.order_by(
        col(SessionMessage.created_at).asc(),
        col(SessionMessage.id).asc(),
    )


def _is_history_visible(row: SessionMessage) -> bool:
    if not row.exclude_from_context:
        return True
    return bool(row.extra and row.extra.get("queue_status") == "queued")


def _is_hidden_from_user(row: SessionMessage) -> bool:
    return bool(row.extra and row.extra.get("hidden_from_user"))


def _is_undo_target(row: SessionMessage) -> bool:
    if _is_hidden_from_user(row):
        return False
    return row.is_summary or not row.exclude_from_context


async def get_messages(db: AsyncSession, session_id: UUID) -> list[ChatMessage]:
    """Retrieves all *visible* ChatMessages for a session.

    Excluded messages (``exclude_from_context=True``) are filtered out — this
    is the list shown to the end user.  Summary messages (``is_summary=True``)
    are included so the UI can render them.

    To get the context window sent to the LLM, use
    :func:`get_messages_for_llm` instead.
    """
    logger.debug("loading_messages session_id={}", session_id)
    try:
        boundary = await _revert_boundary(db, session_id)
        rows = (await db.exec(_history_messages_stmt(session_id, boundary))).all()
        db_messages = [row for row in rows if _is_history_visible(row)]
        logger.debug(
            "messages_fetched session_id={} count={}", session_id, len(db_messages)
        )
        # Me run in thread — _deserialize_messages does disk I/O for image hydration
        messages = await asyncio.to_thread(_deserialize_messages, db_messages)
        return [
            m for m in messages if not (m.extra and m.extra.get("hidden_from_user"))
        ]
    except Exception as e:
        logger.error("load_messages_failed session_id={} error={}", session_id, e)
        raise


async def get_visible_session_rows(
    db: AsyncSession, session_id: UUID
) -> list[SessionMessage]:
    """Return raw, user-visible ``SessionMessage`` rows for one session.

    Unlike :func:`get_messages`, this does NOT deserialize into
    ``ChatMessage`` (which drops the ORM-only ``id``/``session_id`` columns
    per ``BaseMessage.model_config = ConfigDict(extra="ignore")``) — API
    routes that build a ``MessageResponse`` (which requires those fields)
    need the raw row, the same as ``get_team_history`` already fetches for
    the main session's message list.
    """
    boundary = await _revert_boundary(db, session_id)
    rows = (await db.exec(_history_messages_stmt(session_id, boundary))).all()
    return [
        row
        for row in rows
        if _is_history_visible(row) and not _is_hidden_from_user(row)
    ]


async def get_messages_for_llm(db: AsyncSession, session_id: UUID) -> list[ChatMessage]:
    """Return the message window that should be sent to the LLM.

    Strategy
    --------
    1. Find the most recent ``is_summary=True`` message.
    2. If one exists, return ``[latest_summary] + [non-hidden, non-summary
       messages ordered by created_at]``.  This correctly handles:
       - Multiple summaries: only the latest is prepended; older summary rows
         are excluded by the ``not is_summary`` filter.
       - ``keep_last_n`` messages: they were not hidden so they appear after
         the summary in chronological order, even though their ``created_at``
         is earlier than the summary's.
       - Fresh messages added after the summary: included in order.
    3. If no summary exists, fall back to all visible (non-hidden) messages —
       identical to :func:`get_messages`.
    """
    logger.debug("loading_llm_messages session_id={}", session_id)
    try:
        boundary = await _revert_boundary(db, session_id)
        # Find the latest summary message
        summary_stmt = (
            select(SessionMessage)
            .where(col(SessionMessage.session_id) == session_id)
            .where(col(SessionMessage.is_summary))
            .where(~col(SessionMessage.exclude_from_context))
        )
        summary_stmt = (
            _before_boundary(summary_stmt, boundary)
            .order_by(
                col(SessionMessage.created_at).desc(),
                col(SessionMessage.id).desc(),
            )
            .limit(1)
        )
        latest_summary = (await db.exec(summary_stmt)).first()

        if latest_summary is None:
            # No summary yet — use all visible messages
            db_messages = (
                await db.exec(_visible_messages_stmt(session_id, boundary))
            ).all()
            messages = await asyncio.to_thread(
                _deserialize_messages, db_messages, sanitize_tool_pairs=True
            )
            return _apply_llm_content_overrides(messages)

        # Fetch all non-hidden, non-summary messages.  This naturally includes:
        #   - keep_last_n messages (not hidden, created before the summary)
        #   - fresh messages added after the summary
        # It excludes:
        #   - hidden messages (superseded by the summary)
        #   - other summary rows (older summaries are also excluded)
        #   - the latest summary itself (prepended explicitly below)
        rest_stmt = _visible_messages_stmt(session_id, boundary).where(
            ~col(SessionMessage.is_summary)
        )
        rest_messages = list((await db.exec(rest_stmt)).all())

        db_messages = [latest_summary] + rest_messages

        logger.debug(
            "llm_messages_fetched session_id={} count={} summary_id={}",
            session_id,
            len(db_messages),
            latest_summary.id,
        )
        # Me run in thread — _deserialize_messages does disk I/O for image hydration
        messages = await asyncio.to_thread(
            _deserialize_messages, db_messages, sanitize_tool_pairs=True
        )
        return _apply_llm_content_overrides(messages)
    except Exception as e:
        logger.error("load_llm_messages_failed session_id={} error={}", session_id, e)
        raise


def _message_snapshot(row: SessionMessage | None) -> str | None:
    if row is None or not row.extra:
        return None
    value = row.extra.get("snapshot")
    return value if isinstance(value, str) and value else None


def _redo_anchor(session: ChatSession | None) -> str | None:
    value = session.revert if session else None
    if not isinstance(value, dict):
        return None
    raw = value.get("snapshot")
    return raw if isinstance(raw, str) and raw else None


async def undo_session_messages(db: AsyncSession, session_id: UUID) -> BoundaryShift:
    """Move the session revert boundary to the previous user message."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        return BoundaryShift(applied=False)
    boundary = await _revert_boundary(db, session_id)
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.role) == "user")
        .order_by(
            col(SessionMessage.created_at).desc(),
            col(SessionMessage.id).desc(),
        )
    )
    if boundary is not None:
        stmt = _before_boundary(stmt, boundary)
    rows = (await db.exec(stmt)).all()
    target = next((row for row in rows if _is_undo_target(row)), None)
    if target is None:
        return BoundaryShift(applied=False)

    workspace = session_workspace_dir(str(session_id), session.workspace)
    redo_anchor = _redo_anchor(session)
    just_tracked = False
    if redo_anchor is None:
        redo_anchor = await snapshot_service.track(str(session_id), workspace)
        just_tracked = redo_anchor is not None

    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    target_snapshot = _message_snapshot(target)
    if target_snapshot:
        result = await snapshot_service.restore(
            str(session_id),
            workspace,
            target_snapshot,
            skip_stage=just_tracked,
        )
        added, modified, removed = result.added, result.modified, result.removed

    revert_state: dict = {"message_id": str(target.id)}
    if redo_anchor:
        revert_state["snapshot"] = redo_anchor
    session.revert = revert_state
    db.add(session)
    await db.flush()
    return BoundaryShift(
        applied=True,
        target=target,
        added=added,
        modified=modified,
        removed=removed,
    )


async def redo_session_messages(db: AsyncSession, session_id: UUID) -> BoundaryShift:
    """Move the revert boundary forward, or clear it at the end."""
    session = await db.get(ChatSession, session_id)
    boundary = await _revert_boundary(db, session_id)
    if session is None or boundary is None:
        return BoundaryShift(applied=False)
    redo_anchor = _redo_anchor(session)
    next_user = (
        await db.exec(
            _after_boundary(
                select(SessionMessage)
                .where(col(SessionMessage.session_id) == session_id)
                .where(col(SessionMessage.role) == "user"),
                boundary,
            )
            .order_by(
                col(SessionMessage.created_at).asc(),
                col(SessionMessage.id).asc(),
            )
            .limit(1)
        )
    ).first()

    workspace = session_workspace_dir(str(session_id), session.workspace)
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    if next_user is None:
        if redo_anchor:
            result = await snapshot_service.restore(
                str(session_id), workspace, redo_anchor
            )
            added, modified, removed = result.added, result.modified, result.removed
        session.revert = None
    else:
        next_snapshot = _message_snapshot(next_user)
        if next_snapshot:
            result = await snapshot_service.restore(
                str(session_id), workspace, next_snapshot
            )
            added, modified, removed = result.added, result.modified, result.removed
        revert_state: dict = {"message_id": str(next_user.id)}
        if redo_anchor:
            revert_state["snapshot"] = redo_anchor
        session.revert = revert_state
    db.add(session)
    await db.flush()
    return BoundaryShift(
        applied=True,
        target=next_user,
        added=added,
        modified=modified,
        removed=removed,
    )


async def cleanup_reverted_tail(db: AsyncSession, session_id: UUID) -> int:
    """Permanently hide the reverted tail before accepting an edited resend."""
    session = await db.get(ChatSession, session_id)
    boundary = await _revert_boundary(db, session_id)
    if session is None or boundary is None:
        return 0
    rows = (
        await db.exec(
            _on_or_after_boundary(
                select(SessionMessage).where(
                    col(SessionMessage.session_id) == session_id
                ),
                boundary,
            )
        )
    ).all()
    cleaned = 0
    for row in rows:
        if row.extra and row.extra.get("queue_status") == "queued":
            continue
        extra = dict(row.extra or {})
        extra["hidden_from_user"] = True
        row.extra = extra
        row.exclude_from_context = True
        db.add(row)
        cleaned += 1
    if boundary.is_summary:
        previous_summaries = (
            await db.exec(
                _before_boundary(
                    select(SessionMessage)
                    .where(col(SessionMessage.session_id) == session_id)
                    .where(col(SessionMessage.is_summary)),
                    boundary,
                ).order_by(
                    col(SessionMessage.created_at).desc(),
                    col(SessionMessage.id).desc(),
                )
            )
        ).all()
        previous_summary = next(
            (row for row in previous_summaries if not _is_hidden_from_user(row)), None
        )
        if previous_summary is not None:
            previous_summary.exclude_from_context = False
            db.add(previous_summary)
        restored = (
            await db.exec(
                _before_boundary(
                    select(SessionMessage)
                    .where(col(SessionMessage.session_id) == session_id)
                    .where(~col(SessionMessage.is_summary))
                    .where(col(SessionMessage.exclude_from_context)),
                    boundary,
                )
            )
        ).all()
        for row in restored:
            if _is_hidden_from_user(row):
                continue
            if previous_summary is not None and (
                row.created_at < previous_summary.created_at
                or (
                    row.created_at == previous_summary.created_at
                    and row.id <= previous_summary.id
                )
            ):
                continue
            row.exclude_from_context = False
            db.add(row)
    session.revert = None
    db.add(session)
    await db.flush()
    return cleaned


async def save_queued_user_message(
    db: AsyncSession,
    session_id: UUID,
    content: str,
    *,
    extra: dict | None = None,
) -> SessionMessage:
    queued_at = datetime.now(timezone.utc).isoformat()
    row_extra = dict(extra or {})
    row_extra.update({"queue_status": "queued", "queued_at": queued_at})
    return await save_message(
        db,
        session_id,
        HumanMessage(content=content),
        is_hidden=True,
        extra=row_extra,
    )


async def mark_channel_source_delivered(db: AsyncSession, row: SessionMessage) -> bool:
    """Mark a source-keyed channel row after its delivery boundary succeeds."""
    extra = dict(row.extra or {})
    source = extra.get("webbridge_source")
    if not isinstance(source, dict) or not source.get("key"):
        return False
    if source.get("state") == "delivered":
        return False
    source = dict(source)
    source["state"] = "delivered"
    extra["webbridge_source"] = source
    row.extra = extra
    db.add(row)
    await db.flush()
    return True


async def release_queued_user_messages(
    db: AsyncSession,
    session_id: UUID,
) -> list[SessionMessage]:
    rows = await db.exec(
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.role) == "user")
        .where(col(SessionMessage.exclude_from_context))
        .where(col(SessionMessage.extra)["queue_status"].as_string() == "queued")
        .order_by(
            col(SessionMessage.created_at).asc(),
            col(SessionMessage.id).asc(),
        )
    )
    queued = list(rows.all())
    released_at = datetime.now(timezone.utc)
    for i, row in enumerate(queued):
        extra = dict(row.extra or {})
        extra.pop("queue_status", None)
        extra.pop("queued_at", None)
        row.extra = extra or None
        row.exclude_from_context = False
        row.created_at = released_at + timedelta(microseconds=i)
        db.add(row)
    await db.flush()
    return queued


async def pop_queued_user_messages(
    db: AsyncSession,
    session_id: UUID,
) -> list[SessionMessage]:
    rows = await db.exec(
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.role) == "user")
        .where(col(SessionMessage.exclude_from_context))
        .where(col(SessionMessage.extra)["queue_status"].as_string() == "queued")
        .order_by(
            col(SessionMessage.created_at).asc(),
            col(SessionMessage.id).asc(),
        )
    )
    queued = list(rows.all())
    activated_at = datetime.now(timezone.utc)
    for i, row in enumerate(queued):
        extra = dict(row.extra or {})
        extra.pop("queue_status", None)
        row.extra = extra or None
        row.exclude_from_context = False
        row.created_at = activated_at + timedelta(microseconds=i)
        db.add(row)
    await db.flush()
    return queued


async def cancel_queued_user_message(
    db: AsyncSession,
    session_id: UUID,
    message_id: UUID,
) -> bool:
    row = await db.get(SessionMessage, message_id)
    if (
        row is None
        or row.session_id != session_id
        or not row.extra
        or row.extra.get("queue_status") != "queued"
    ):
        return False
    await db.delete(row)
    await db.flush()
    return True


async def exclude_messages_before_summary(
    db: AsyncSession,
    session_id: UUID,
    summary_message_id: UUID,
    keep_last_n: int = 0,
) -> int:
    """Mark messages older than ``summary_message_id`` as excluded from context.

    Excludes:
    - All previous ``is_summary=True`` rows (superseded summaries).
    - All regular (non-summary) messages created before the new summary,
      except the last ``keep_last_n`` which are kept verbatim.

    When ``keep_last_n > 0``, the *most recent* ``keep_last_n`` visible
    non-summary messages created **before** the summary are preserved so
    they remain in the LLM context window alongside the new summary.

    Returns the total number of messages excluded.
    """
    # Me fetch summary row to get its created_at timestamp
    summary_msg = await db.get(SessionMessage, summary_message_id)
    if summary_msg is None:
        logger.warning(
            "exclude_messages_before_summary_not_found summary_id={}",
            summary_message_id,
        )
        return 0

    # ── Exclude all previous summaries (superseded by the new one) ──────
    old_summaries_stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.is_summary))
        .where(col(SessionMessage.id) != summary_message_id)
        .where(~col(SessionMessage.exclude_from_context))
    )
    old_summaries = list((await db.exec(old_summaries_stmt)).all())
    for row in old_summaries:
        row.exclude_from_context = True
        db.add(row)

    # ── Exclude regular messages before the summary ──────────────────────
    # All visible non-summary messages created before the summary, oldest-first.
    # Use (created_at, id) order so same-timestamp rows *after* the summary
    # are not falsely excluded (common on coarse Windows clocks).
    stmt = (
        _before_boundary(
            select(SessionMessage)
            .where(col(SessionMessage.session_id) == session_id)
            .where(~col(SessionMessage.exclude_from_context))
            .where(~col(SessionMessage.is_summary)),
            summary_msg,
        ).order_by(
            col(SessionMessage.created_at).asc(),
            col(SessionMessage.id).asc(),
        )
    )
    rows = list((await db.exec(stmt)).all())

    # Me spare the tail when keep_last_n set
    if keep_last_n > 0 and len(rows) > keep_last_n:
        rows_to_exclude = rows[:-keep_last_n]
    else:
        rows_to_exclude = rows if keep_last_n == 0 else []

    for row in rows_to_exclude:
        row.exclude_from_context = True
        db.add(row)

    await db.flush()
    total_excluded = len(old_summaries) + len(rows_to_exclude)
    logger.info(
        "messages_excluded session_id={} count={} old_summaries={} kept={} before_summary={}",
        session_id,
        total_excluded,
        len(old_summaries),
        len(rows) - len(rows_to_exclude),
        summary_message_id,
    )
    return total_excluded


# Me keep backward-compat alias during transition
hide_messages_before_summary = exclude_messages_before_summary


# ── Session CRUD ─────────────────────────────────────────────────────────────


async def list_sessions_page(
    db: AsyncSession,
    *,
    before: str | None = None,
    limit: int = 20,
    mode: str | None = None,
    workspace: str | None = None,
    project_id: UUID | None = None,
) -> tuple[list[ChatSession], str | None, bool]:
    """Return a cursor-paginated page of top-level sessions (newest-first).

    Top-level sessions are those without a ``parent_session_id`` (team leads
    and scheduled tasks). Sub-sessions are excluded, and so are side chats
    (``session_type="side_chat"``) — they are opened from their source
    session's row, never listed standalone.

    Args:
        db: Async database session.
        before: ISO 8601 ``created_at`` cursor — return sessions older than this.
        limit: Maximum number of sessions to return (1–100).
        mode: Optional session mode filter.
        workspace: Optional workspace filter for coding sessions.

    Returns:
        A tuple of ``(sessions, next_cursor, has_more)`` where ``next_cursor``
        is the ISO 8601 ``created_at`` of the last session on this page, or
        ``None`` if this is the last page.

    Raises:
        ValueError: If *before* is not a valid ISO 8601 datetime string.
    """
    stmt = (
        select(ChatSession)
        .where(col(ChatSession.parent_session_id).is_(None))
        .where(col(ChatSession.session_type) != "side_chat")
        .order_by(col(ChatSession.created_at).desc())
    )

    if mode is not None:
        stmt = stmt.where(col(ChatSession.mode) == mode)
    if workspace is not None:
        stmt = stmt.where(col(ChatSession.workspace) == workspace)
    if project_id is not None:
        stmt = stmt.where(col(ChatSession.project_id) == project_id)

    if before:
        cursor_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        stmt = stmt.where(col(ChatSession.created_at) < cursor_dt)

    rows = (await db.exec(stmt.limit(limit + 1))).all()

    has_more = len(rows) > limit
    rows = list(rows[:limit])

    next_cursor: str | None = None
    if has_more and rows:
        last_created = rows[-1].created_at
        if last_created is not None:
            if last_created.tzinfo is None:
                last_created = last_created.replace(tzinfo=timezone.utc)
            next_cursor = last_created.isoformat().replace("+00:00", "Z")

    return rows, next_cursor, has_more


async def list_sessions_with_tag(
    db: AsyncSession,
    tag: str,
    *,
    limit: int = 100,
) -> list[ChatSession]:
    """Return the newest top-level sessions containing one server-owned tag.

    JSON membership differs between SQLite and Postgres, while WebBridge pairing
    lists are small and local. Read top-level session metadata once, filter the
    tag in Python, then apply the requested cap so old pairing-owned sessions do
    not disappear behind newer unrelated sessions.
    """
    bounded_limit = max(1, min(limit, 500))
    rows = (
        await db.exec(
            select(ChatSession)
            .where(col(ChatSession.parent_session_id).is_(None))
            .where(col(ChatSession.session_type) != "side_chat")
            .order_by(
                col(ChatSession.created_at).desc(),
                col(ChatSession.id).desc(),
            )
        )
    ).all()
    return [session for session in rows if tag in (session.tags or ())][:bounded_limit]


async def get_latest_top_level_session(
    db: AsyncSession,
    *,
    mode: str,
    workspace: str | None,
    project_id: UUID | None = None,
    folder_id: UUID | None = None,
    tags: list[str] | None = None,
    tag_match: Literal["exact", "contains"] = "exact",
) -> ChatSession | None:
    """Return the newest top-level session for a mode/workspace pair.

    When ``project_id`` is provided the lookup is scoped by project identity
    (mode + project_id) rather than by workspace path — a project session spans
    all of the project's repos, so it must never be matched/reused by the first
    repo's path alone (which could collide with an unrelated single-repo session
    or a different project sharing that path).

    ``folder_id`` scopes the lookup to one sidebar folder, so opening a
    folder never hands back a session filed elsewhere. Leaving it ``None``
    keeps the historical behaviour of matching regardless of folder.

    ``tags=None`` (the default) keeps the historical behaviour — no tag
    filtering at all. Any other value uses exact tag-SET equality unless
    ``tag_match="contains"`` is requested. Contains matching is useful for
    feature-context tags that must survive additional capability tags.
    """
    stmt = (
        select(ChatSession)
        .where(
            col(ChatSession.parent_session_id).is_(None),
            ChatSession.mode == mode,
        )
        .order_by(
            col(ChatSession.created_at).desc(),
            col(ChatSession.id).desc(),
        )
    )
    if folder_id is not None:
        stmt = stmt.where(col(ChatSession.folder_id) == folder_id)
    if project_id is not None:
        stmt = stmt.where(col(ChatSession.project_id) == project_id)
    else:
        # Plain (non-project) resolve: never reuse a project session by its
        # derived primary-repo path — a project session is scoped by project_id.
        stmt = stmt.where(col(ChatSession.project_id).is_(None))
        if workspace is None:
            stmt = stmt.where(col(ChatSession.workspace).is_(None))
        else:
            stmt = stmt.where(ChatSession.workspace == workspace)
    if tags is not None:
        requested = sorted(set(tags))
        if requested and tag_match == "exact":
            stmt = stmt.where(col(ChatSession.tags) == requested)
        elif not requested:
            stmt = stmt.where(
                or_(col(ChatSession.tags).is_(None), col(ChatSession.tags) == [])
            )
        elif tag_match == "contains":
            requested_set = set(requested)
            rows = (await db.exec(stmt)).all()
            return next(
                (
                    session
                    for session in rows
                    if requested_set.issubset(session.tags or ())
                ),
                None,
            )
    return (await db.exec(stmt.limit(1))).first()


async def update_session_title(
    db: AsyncSession, session_id: UUID, title: str
) -> ChatSession | None:
    """Update a top-level session title and return the refreshed session."""
    async with db.begin():
        session = await db.get(ChatSession, session_id)
        if not session or session.parent_session_id is not None:
            return None
        session.title = title
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session


async def delete_session(db: AsyncSession, session_id: UUID) -> bool:
    """Permanently delete a session and every app-owned dependent resource."""
    from app.services.coding_purge_service import purge_session

    return await purge_session(db, session_id)


class TeamHistoryMemberData(NamedTuple):
    """One sub-session and its paginated, non-summary messages."""

    session: ChatSession
    messages: list[SessionMessage]


_HISTORY_PAGE_SIZE = 100


class TeamHistoryData(NamedTuple):
    """Full history payload for a team lead session.

    Returned by :func:`get_team_history`.
    """

    lead_session: ChatSession
    lead_messages: list[SessionMessage]
    members: list[TeamHistoryMemberData]
    has_more: bool
    next_cursor: str | None


def _decode_history_cursor(
    value: str | datetime | None,
) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        return value, None
    timestamp, separator, message_id = value.rpartition("|")
    if not separator:
        return datetime.fromisoformat(value), None
    return datetime.fromisoformat(timestamp), UUID(message_id)


async def get_team_history(
    db: AsyncSession,
    lead_session_id: UUID,
    *,
    before: str | datetime | None = None,
) -> TeamHistoryData | None:
    """Fetch the latest page of history for a team lead session and its sub-sessions.

    Fetches up to ``_HISTORY_PAGE_SIZE`` messages per session ordered by
    ``created_at DESC`` (newest first), then reverses to chronological order
    for the caller.  Pass the ``next_cursor`` from a previous response as
    ``before`` to load older messages.

    Returns ``None`` if the lead session does not exist.
    """
    lead_session = await db.get(ChatSession, lead_session_id)
    if lead_session is None:
        return None

    sub_sessions = (
        await db.exec(
            select(ChatSession)
            .where(col(ChatSession.parent_session_id) == lead_session_id)
            .order_by(col(ChatSession.created_at).asc())
        )
    ).all()
    session_ids = [lead_session_id, *(session.id for session in sub_sessions)]
    before_at, before_id = _decode_history_cursor(before)
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id).in_(session_ids))
        .order_by(
            col(SessionMessage.created_at).desc(),
            col(SessionMessage.id).desc(),
        )
        .limit(_HISTORY_PAGE_SIZE + 1)
    )
    if before_at is not None:
        if before_id is None:
            stmt = stmt.where(col(SessionMessage.created_at) < before_at)
        else:
            stmt = stmt.where(
                or_(
                    col(SessionMessage.created_at) < before_at,
                    and_(
                        col(SessionMessage.created_at) == before_at,
                        col(SessionMessage.id) < before_id,
                    ),
                )
            )
    raw_page = list((await db.exec(stmt)).all())
    has_more = len(raw_page) > _HISTORY_PAGE_SIZE
    page = raw_page[:_HISTORY_PAGE_SIZE]
    # Summaries remain visible for compaction UI; only explicit
    # ``hidden_from_user`` rows are removed from the rendered page.
    visible_page = [row for row in page if not _is_hidden_from_user(row)]
    lead_msgs = list(
        reversed([row for row in visible_page if row.session_id == lead_session_id])
    )
    members = [
        TeamHistoryMemberData(
            session=sub,
            messages=list(
                reversed([row for row in visible_page if row.session_id == sub.id])
            ),
        )
        for sub in sub_sessions
    ]
    next_cursor = (
        f"{page[-1].created_at.isoformat()}|{page[-1].id}"
        if has_more and page
        else None
    )

    return TeamHistoryData(
        lead_session=lead_session,
        lead_messages=lead_msgs,
        members=members,
        has_more=has_more,
        next_cursor=next_cursor,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _deserialize_messages(
    db_messages: Sequence[SessionMessage], *, sanitize_tool_pairs: bool = False
) -> list[ChatMessage]:
    """Convert ORM rows into typed ChatMessage objects via TypeAdapter.

    Uses ``model_dump()`` → ``TypeAdapter.validate_python()`` so the
    discriminated union on ``role`` picks the right subclass automatically.
    ``BaseMessage.model_config = ConfigDict(extra="ignore")`` drops DB-only
    columns (``id``, ``session_id``, ``created_at``).

    For user messages with file attachments (stored in extra.attachments),
    re-hydrates ``parts`` from disk so the LLM sees images in every turn.

    Rows with unrecognised ``role`` values are silently skipped with a warning.
    """
    result: list[ChatMessage] = []
    for m in db_messages:
        try:
            d = m.model_dump()
            # Me coerce None → "" so ToolMessage(tool_call_id: str) no explode
            if d.get("tool_call_id") is None:
                d["tool_call_id"] = ""
            msg = _chat_message_adapter.validate_python(d)
            # Me stash DB row PK so checkpointer can do reliable PK lookups
            msg.db_id = m.id

            # Me re-hydrate multimodal parts for user messages that have file attachments
            if isinstance(msg, HumanMessage) and m.extra:
                attachments = m.extra.get("attachments")
                if attachments and isinstance(attachments, list):
                    parts = _build_parts(msg.content or "", attachments)
                    if parts:
                        msg.parts = parts

            result.append(msg)
        except Exception:
            # Me skip rows with unknown role — no crash the caller
            logger.warning(
                "deserialize_skip_unknown_role session_id={} message_id={} role={}",
                m.session_id,
                m.id,
                m.role,
            )

    # Strip tool calls whose arguments are not valid JSON — this happens when
    # the user interrupts the agent mid-stream before the LLM has finished
    # emitting the arguments. The partial JSON is persisted to the DB and would
    # cause a JSONDecodeError on the next turn when tool_executor tries to parse
    # it. Drop the bad tool calls from the assistant message and remove any
    # orphaned ToolMessage results that reference them.
    bad_tool_call_ids: set[str] = set()
    for msg in result:
        if not isinstance(msg, AssistantMessage) or not msg.tool_calls:
            continue
        clean: list = []
        for tc in msg.tool_calls:
            try:
                json.loads(tc.function.arguments)
                clean.append(tc)
            except (json.JSONDecodeError, ValueError):
                bad_tool_call_ids.add(tc.id)
                logger.debug(
                    "deserialize_drop_partial_tool_call tool={} id={} args_prefix={!r}",
                    tc.function.name,
                    tc.id,
                    tc.function.arguments[:80],
                )
        if len(clean) != len(msg.tool_calls):
            msg.tool_calls = clean or None

    if bad_tool_call_ids:
        kept: list[ChatMessage] = []
        for msg in result:
            if isinstance(msg, ToolMessage) and msg.tool_call_id in bad_tool_call_ids:
                row = _message_row_by_id(db_messages).get(msg.db_id)
                logger.debug(
                    "deserialize_drop_orphan_tool_message session_id={} message_id={} tool_call_id={}",
                    row.session_id if row else None,
                    msg.db_id,
                    msg.tool_call_id,
                )
                continue
            kept.append(msg)
        result = kept

    if sanitize_tool_pairs:
        result = _sanitize_tool_message_pairs(result, db_messages)

    return result


def _apply_llm_content_overrides(messages: list[ChatMessage]) -> list[ChatMessage]:
    for msg in messages:
        if not isinstance(msg, HumanMessage) or not msg.extra:
            continue
        if msg.extra.get("kind") == "user_shell":
            msg.content = USER_SHELL_LLM_CONTENT
    return messages


def _message_row_by_id(
    db_messages: Sequence[SessionMessage],
) -> dict[UUID | None, SessionMessage]:
    return {m.id: m for m in db_messages}


def _sanitize_tool_message_pairs(
    messages: list[ChatMessage], db_messages: Sequence[SessionMessage]
) -> list[ChatMessage]:
    """Drop LLM-invalid tool outputs and strip incomplete assistant tool calls.

    Mid-history assistant messages left with neither content nor tool_calls
    are dropped: some providers (e.g. Xiaomi mimo) reject empty assistant
    turns with HTTP 400 "assistant must provide content, reasoning_content
    or tool_calls". A *trailing* empty assistant message is kept — the team
    continue flow inspects the tail for an interrupted thinking-only row
    (``_is_interrupted_thinking_only_tail``) and must be able to see it;
    providers additionally skip empty assistant turns at serialization.
    """
    rows_by_id = _message_row_by_id(db_messages)
    result: list[ChatMessage] = []
    expected_tool_ids: set[str] = set()
    last_idx = len(messages) - 1

    for idx, msg in enumerate(messages):
        if isinstance(msg, AssistantMessage):
            expected_tool_ids.clear()
            if not msg.tool_calls:
                if msg.content or idx == last_idx:
                    result.append(msg)
                else:
                    row = rows_by_id.get(msg.db_id)
                    logger.debug(
                        "deserialize_drop_empty_assistant_message session_id={} message_id={}",
                        row.session_id if row else None,
                        msg.db_id,
                    )
                continue

            tool_call_ids = {tc.id for tc in msg.tool_calls if tc.id}
            following_tool_ids: set[str] = set()
            for next_msg in messages[idx + 1 :]:
                if not isinstance(next_msg, ToolMessage):
                    break
                if next_msg.tool_call_id:
                    following_tool_ids.add(next_msg.tool_call_id)

            missing = tool_call_ids - following_tool_ids
            if tool_call_ids and not missing:
                expected_tool_ids = set(tool_call_ids)
                result.append(msg)
            else:
                row = rows_by_id.get(msg.db_id)
                dropped = not msg.content and idx != last_idx
                logger.debug(
                    "deserialize_strip_incomplete_assistant_tool_calls session_id={} message_id={} missing_ids=[{}] dropped={}",
                    row.session_id if row else None,
                    msg.db_id,
                    ", ".join(sorted(missing or tool_call_ids)),
                    dropped,
                )
                if not dropped:
                    result.append(msg.model_copy(update={"tool_calls": None}))
            continue

        if isinstance(msg, ToolMessage):
            if msg.tool_call_id and msg.tool_call_id in expected_tool_ids:
                result.append(msg)
                expected_tool_ids.remove(msg.tool_call_id)
            else:
                row = rows_by_id.get(msg.db_id)
                logger.debug(
                    "deserialize_drop_orphan_tool_message session_id={} message_id={} tool_call_id={}",
                    row.session_id if row else None,
                    msg.db_id,
                    msg.tool_call_id,
                )
            continue

        expected_tool_ids.clear()
        result.append(msg)

    return result


def _build_parts(text: str, attachments: list[dict]) -> list | None:
    """Build LLM content parts from persisted attachment metadata.

    Uses ``build_parts_from_metas`` (fast path: ``converted_text`` in meta,
    slow path: read from ``att["path"]`` for images / native-PDF documents).

    Returns None if only the trailing user-text block would be produced
    (i.e. no file content — no point setting HumanMessage.parts in that case).
    """
    parts = build_parts_from_metas(text, attachments)
    # build_parts_from_metas always appends a trailing TextBlock for `text`.
    # If no file blocks were produced (all attachments missing), skip parts.
    has_file_blocks = any(
        not (hasattr(p, "text") and getattr(p, "text") == text) for p in parts
    )
    return parts if has_file_blocks else None


# ── Side Chat helpers ────────────────────────────────────────────────────────


async def get_side_chat_context(
    db: AsyncSession,
    source_session_id: UUID,
    *,
    max_messages: int = 50,
) -> list[ChatMessage]:
    """Load the last *max_messages* visible messages from *source_session_id*.

    Returns them in chronological order so they can be prepended to the side
    chat's own message list as read-only context for the LLM.  Messages with
    ``exclude_from_context=True`` are filtered out (same as
    :func:`get_messages_for_llm`).
    """
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == source_session_id)
        .where(~col(SessionMessage.exclude_from_context))
        .order_by(
            col(SessionMessage.created_at).desc(),
            col(SessionMessage.id).desc(),
        )
        .limit(max_messages)
    )
    db_messages = list((await db.exec(stmt)).all())
    db_messages.reverse()  # chronological order
    return await asyncio.to_thread(
        _deserialize_messages, db_messages, sanitize_tool_pairs=True
    )


async def create_side_chat_session(
    db: AsyncSession,
    main_session_id: UUID,
    *,
    title: str | None = None,
) -> ChatSession:
    """Create a side-chat session with read-only access to *main_session_id*.

    Copies workspace/project/mode settings from the main session so the side
    chat inherits the same environment.  The ``source_session_id`` foreign key
    uses ``ON DELETE SET NULL`` so a deleted main session doesn't cascade.

    Tagged ``"side_chat"`` (tier_policy.SIDE_CHAT_SESSION_TAG) so the team
    lead for this session — a dedicated per-session instance, never shared
    with the main session — restricts to read-only tools and gets the
    read-only system-prompt addendum (mirrors WebBridge session tagging).

    The main session's recent context is copied in as messages marked
    ``extra.hidden_from_user=True``: invisible on GET .../messages (so the
    panel doesn't open pre-filled with the whole main conversation) but
    still part of get_messages_for_llm's window, so the agent actually has
    the context "read-only access" promises.
    """
    main = await db.get(ChatSession, main_session_id)
    if main is None:
        raise ValueError(f"Main session {main_session_id} not found")

    effective_title = title or f"Side Chat: {main.title or 'Untitled'}"
    session = ChatSession(
        title=effective_title,
        session_type="side_chat",
        source_session_id=main_session_id,
        source_session_ref=main_session_id,
        agent_name=main.agent_name,
        mode=main.mode,
        workspace=main.workspace,
        project_id=main.project_id,
        tags=["side_chat"],
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)

    context_messages = await get_side_chat_context(db, main_session_id)
    base_time = datetime.now(timezone.utc)
    for i, msg in enumerate(context_messages):
        await save_message(
            db,
            session.id,
            msg,
            extra={"hidden_from_user": True, "side_chat_context": True},
            # Strictly monotonic and guaranteed to sort before the first real
            # message (created via the normal utcnow() default afterwards).
            created_at=base_time + timedelta(microseconds=i),
        )
    await db.flush()

    logger.info(
        "side_chat_created session_id={} source_session_id={} context_messages={}",
        session.id,
        main_session_id,
        len(context_messages),
    )
    return session
