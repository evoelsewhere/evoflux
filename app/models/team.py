"""Durable coordination records for multi-agent teams."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey, JSON
import sqlalchemy.dialects.postgresql as pg
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class DelegationTask(SQLModel, table=True):
    """One independently trackable assignment to one team member."""

    __tablename__: str = "delegation_tasks"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index(
            "ix_delegation_tasks_session_status",
            "lead_session_id",
            "status",
        ),
        sa.Index(
            "ix_delegation_tasks_recipient_status",
            "lead_session_id",
            "recipient",
            "status",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    lead_session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    delegator: str = Field(sa_column=Column(sa.String(100), nullable=False))
    recipient: str = Field(sa_column=Column(sa.String(100), nullable=False))
    # blocked | pending | completed | cancelled | failed
    status: str = Field(
        default="pending",
        sa_column=Column(sa.String(20), nullable=False, server_default="pending"),
    )
    spec: dict = Field(
        default_factory=dict,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    dependencies: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    attempt: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    deadline_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    dispatched_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    final_handoff_message_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("session_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    result: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    last_rejection: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
