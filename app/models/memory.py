"""Durable, scoped long-term memory models.

The Markdown wiki remains the human-readable projection, while these tables
hold the canonical facts, provenance, and extraction cursor used at runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid7  # ty: ignore[unresolved-import]

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, ForeignKey, JSON
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryFact(SQLModel, table=True):
    """One deduplicated semantic fact within an explicit memory scope."""

    __tablename__: str = "memory_facts"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "content_hash",
            name="uq_memory_facts_scope_content",
        ),
        sa.Index(
            "ix_memory_facts_scope_status_updated",
            "scope_type",
            "scope_id",
            "status",
            "updated_at",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    scope_type: str = Field(sa_column=Column(sa.String(20), nullable=False))
    # Empty string is the stable identifier for the one user-global scope.
    # Avoid NULL here: SQL UNIQUE permits multiple NULL values.
    scope_id: str = Field(default="", sa_column=Column(sa.String(), nullable=False))
    kind: str = Field(sa_column=Column(sa.String(24), nullable=False))
    content: str = Field(sa_column=Column(sa.Text(), nullable=False))
    content_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    confidence: str = Field(
        default="medium",
        sa_column=Column(sa.String(12), nullable=False, server_default="medium"),
    )
    status: str = Field(
        default="active",
        sa_column=Column(sa.String(16), nullable=False, server_default="active"),
    )
    origin: str = Field(
        default="extraction",
        sa_column=Column(sa.String(24), nullable=False, server_default="extraction"),
    )
    occurrences: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    details: dict = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


class MemoryFactEvidence(SQLModel, table=True):
    """Provenance linking a fact to every session that established it."""

    __tablename__: str = "memory_fact_evidence"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "fact_id", "session_id", name="uq_memory_fact_evidence_session"
        ),
        sa.Index("ix_memory_fact_evidence_session", "session_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    fact_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("memory_facts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    source_message_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("session_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    occurrences: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


class MemoryExtractionState(SQLModel, table=True):
    """Durable extraction cursor and retry state for one lead session."""

    __tablename__: str = "memory_extraction_states"  # type: ignore[reportIncompatibleVariableOverride]

    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    last_assistant_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    pending_assistant_count: int | None = Field(default=None)
    content_hash: str | None = Field(
        default=None, sa_column=Column(sa.String(64), nullable=True)
    )
    status: str = Field(
        default="idle",
        sa_column=Column(sa.String(16), nullable=False, server_default="idle"),
    )
    attempts: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    error: str | None = Field(default=None, sa_column=Column(sa.Text(), nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    completed_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


__all__ = ["MemoryExtractionState", "MemoryFact", "MemoryFactEvidence"]
