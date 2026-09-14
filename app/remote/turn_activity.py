"""Turn-activity summary built from a turn's persisted messages.

Queries every :class:`~app.models.chat.SessionMessage` row created since a
turn started and reduces its tool calls into the bounded summary used by
the done-card's "N tool calls" line, and — via later drill-down capability
tokens minted in a subsequent task — the "Full diff"/"Tool log" buttons.

Note: the plan's interface section names ``app.models.chat.ChatMessage``,
but no such model exists in this codebase; the real persisted-message table
is ``SessionMessage`` (``app/models/chat.py``), whose fields (``session_id``,
``role``, ``tool_calls``, ``tool_call_id``, ``content``, ``created_at``)
match exactly what this module needs, so it is used here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import SessionMessage

_DIFF_TOOLS = frozenset({"write", "edit", "patch"})

__all__ = ["TurnActivity", "load_turn_activity"]


@dataclass(frozen=True)
class TurnActivity:
    tool_call_count: int
    summary_lines: list[str] = field(default_factory=list)
    tool_log_text: str = ""
    diff_text: str = ""


async def load_turn_activity(
    db: AsyncSession, session_id: str, *, since: datetime
) -> TurnActivity:
    # ``SessionMessage.session_id`` is a real ``sa.Uuid()`` column, so a
    # non-UUID session_id (e.g. a test double's placeholder string, or an
    # id from a caller that doesn't own a persisted chat session) can never
    # match a row — return the empty-activity placeholders instead of
    # raising, matching what an empty result set would produce anyway.
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return TurnActivity(
            tool_call_count=0,
            tool_log_text="No tool calls.",
            diff_text="No file changes.",
        )

    rows = (
        await db.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_uuid)
            .where(col(SessionMessage.created_at) >= since)
            .order_by(col(SessionMessage.created_at))
        )
    ).all()

    tool_calls: list[tuple[str, str]] = []
    for message in rows:
        for call in message.tool_calls or []:
            name = call.get("name", "unknown")
            args = call.get("arguments", {})
            tool_calls.append((name, str(args)))

    tool_log_lines = [f"{name}: {args}" for name, args in tool_calls]
    diff_lines = [f"{name}: {args}" for name, args in tool_calls if name in _DIFF_TOOLS]
    diff_paths = sorted({args for name, args in tool_calls if name in _DIFF_TOOLS})

    return TurnActivity(
        tool_call_count=len(tool_calls),
        summary_lines=diff_paths[:10],
        tool_log_text="\n".join(tool_log_lines) or "No tool calls.",
        diff_text="\n".join(diff_lines) or "No file changes.",
    )
