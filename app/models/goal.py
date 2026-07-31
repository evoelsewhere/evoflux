from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, ForeignKey, JSON
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionGoal(SQLModel, table=True):
    """One durable long-running objective attached to a top-level chat session."""

    __tablename__: str = "session_goals"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_session_goals_status_updated", "status", "updated_at"),
    )

    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    objective: str = Field(sa_column=Column(sa.Text(), nullable=False))
    status: str = Field(
        default="active",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="active"),
    )
    token_budget: int | None = Field(
        default=None,
        sa_column=Column(sa.BigInteger(), nullable=True),
    )
    tokens_used: int = Field(
        default=0,
        sa_column=Column(sa.BigInteger(), nullable=False, server_default="0"),
    )
    time_used_seconds: float = Field(
        default=0.0,
        sa_column=Column(sa.Float(), nullable=False, server_default="0"),
    )
    active_started_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    pause_reason: str | None = Field(
        default=None,
        max_length=50,
        sa_column=Column(sa.String(50), nullable=True),
    )
    blocker_fingerprint: str | None = Field(
        default=None,
        max_length=64,
        sa_column=Column(sa.String(64), nullable=True),
    )
    blocker_streak: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    status_details: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON(none_as_null=True).with_variant(
                pg.JSONB(none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )
    version: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
