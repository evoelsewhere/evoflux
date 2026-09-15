"""Out-of-scope work an agent noticed and parked instead of doing inline."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime
from app.uuid7 import uuid7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: A suggestion waiting for the user, one they turned into a session, and one
#: they (or the agent) retired. ``started`` is terminal here: the spawned
#: session owns the work from that point on.
STATUSES = ("pending", "started", "dismissed")


class SessionSuggestedTask(SQLModel, table=True):
    """One parked suggestion raised during a session.

    The row is the durable half of the chip the UI renders. It outlives the
    turn that raised it — and the transcript position of the ``spawn_task``
    call — because the point of the feature is that the user can come back to
    the suggestion long after the agent moved on.
    """

    __tablename__: str = "session_suggested_tasks"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        # One suggestion per distinct finding per session. Re-raising a
        # dismissed finding is a no-op rather than a fresh chip: the user
        # already said no, and an agent that re-reads the same file every few
        # turns would otherwise refill the dock with it.
        sa.UniqueConstraint(
            "session_id",
            "fingerprint",
            name="uq_session_suggested_tasks_fingerprint",
        ),
        sa.Index(
            "ix_session_suggested_tasks_session_status",
            "session_id",
            "status",
            "created_at",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    title: str = Field(sa_column=Column(sa.String(120), nullable=False))
    tldr: str = Field(sa_column=Column(sa.Text(), nullable=False))
    #: The full instruction handed to the spawned session. Self-contained by
    #: contract — the new session never sees the conversation that raised it.
    prompt: str = Field(sa_column=Column(sa.Text(), nullable=False))
    #: Project root the spawned session should open. ``None`` means "inherit
    #: the parent session's workspace", resolved at start time rather than
    #: here so a session that later moves workspace still starts correctly.
    cwd: str | None = Field(default=None, sa_column=Column(sa.String(), nullable=True))
    status: str = Field(
        default="pending",
        max_length=16,
        sa_column=Column(sa.String(16), nullable=False, server_default="pending"),
    )
    #: Set when the user starts the task. ``SET NULL`` rather than ``CASCADE``:
    #: deleting the spawned session should leave the record that it happened.
    spawned_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    #: Worktree path created for the spawned session, when started isolated.
    worktree_path: str | None = Field(
        default=None, sa_column=Column(sa.String(), nullable=True)
    )
    fingerprint: str = Field(
        max_length=64, sa_column=Column(sa.String(64), nullable=False)
    )
    dismiss_reason: str | None = Field(
        default=None, sa_column=Column(sa.String(200), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
