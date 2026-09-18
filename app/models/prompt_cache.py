"""Persistent prompt-prefix snapshots used by automatic-cache providers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey, JSON
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime
from app.uuid7 import uuid7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionPrefixSnapshot(SQLModel, table=True):
    """One frozen system/tool prefix for a session and runtime profile.

    The profile key separates intentional rotations (model, agent, permission,
    or base-prompt changes). ``tools_hash`` rotates the same profile when the
    model-visible tool contract changes. The snapshot itself is never sent to
    the UI; it is a runtime cache-affinity artifact.
    """

    __tablename__: str = "session_prefix_snapshots"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "session_id",
            "profile_key",
            name="uq_session_prefix_snapshots_profile",
        ),
        sa.Index(
            "ix_session_prefix_snapshots_session_updated",
            "session_id",
            "updated_at",
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
    profile_key: str = Field(
        max_length=64,
        sa_column=Column(sa.String(64), nullable=False),
    )
    system_prompt: str = Field(sa_column=Column(sa.Text(), nullable=False))
    system_hash: str = Field(
        max_length=64,
        sa_column=Column(sa.String(64), nullable=False),
    )
    tools_hash: str = Field(
        max_length=64,
        sa_column=Column(sa.String(64), nullable=False),
    )
    tools: list[dict] = Field(
        default_factory=list,
        sa_column=Column(JSON(), nullable=False),
    )
    revision: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    # Optional watermark for future checkpoint/fork parity. The current
    # checkpointer can safely leave it null because the snapshot's cache
    # semantics are keyed by profile + tool hash, not by the last message.
    watermark_message_id: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


__all__ = ["SessionPrefixSnapshot"]
