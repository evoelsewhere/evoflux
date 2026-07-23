"""Durable identity and inbound interaction state for WebBridge."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, ForeignKey, JSON, Text
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class WebBridgePairing(SQLModel, table=True):
    __tablename__: str = "webbridge_pairings"  # type: ignore[reportIncompatibleVariableOverride]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    label: str = Field(sa_column=Column(sa.String(120), nullable=False))
    browser: str = Field(
        default="unknown",
        sa_column=Column(sa.String(40), nullable=False, server_default="unknown"),
    )
    version: str = Field(
        default="unknown",
        sa_column=Column(sa.String(40), nullable=False, server_default="unknown"),
    )
    credential_hash: str = Field(
        sa_column=Column(sa.String(64), nullable=False, unique=True, index=True)
    )
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    revoked_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))


class WebBridgeInteraction(SQLModel, table=True):
    __tablename__: str = "webbridge_interactions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "pairing_id",
            "interaction_id",
            name="uq_webbridge_interactions_pairing_interaction",
        ),
        sa.Index(
            "ix_webbridge_interactions_pairing_created", "pairing_id", "created_at"
        ),
        sa.Index("ix_webbridge_interactions_session", "target_session_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    pairing_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    interaction_id: str = Field(sa_column=Column(sa.String(128), nullable=False))
    request_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    kind: str = Field(sa_column=Column(sa.String(80), nullable=False))
    delivery: str = Field(sa_column=Column(sa.String(20), nullable=False))
    status: str = Field(sa_column=Column(sa.String(20), nullable=False))
    target_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    message_id: UUID | None = Field(default=None, sa_column=Column(sa.Uuid()))
    origin: str = Field(default="", sa_column=Column(Text(), nullable=False))
    tab_id: int | None = Field(default=None, sa_column=Column(sa.Integer()))
    page_instance_id: str | None = Field(default=None, sa_column=Column(sa.String(128)))
    payload_metadata: dict = Field(
        default_factory=dict,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    prompt: str | None = Field(default=None, sa_column=Column(Text()))
    error_code: str | None = Field(default=None, sa_column=Column(sa.String(80)))
    error: str | None = Field(default=None, sa_column=Column(Text()))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    processed_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    dispatch_lease_until: datetime | None = Field(
        default=None, sa_column=Column(TZDateTime())
    )


class WebBridgeTeachDraft(SQLModel, table=True):
    """A user-recorded, review-gated semantic browser trace."""

    __tablename__: str = "webbridge_teach_drafts"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index(
            "ix_webbridge_teach_drafts_pairing_created", "pairing_id", "created_at"
        ),
        sa.Index("ix_webbridge_teach_drafts_session", "session_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    pairing_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
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
    tab_id: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    title: str = Field(sa_column=Column(sa.String(255), nullable=False))
    origin: str = Field(sa_column=Column(Text(), nullable=False))
    start_url: str = Field(sa_column=Column(Text(), nullable=False))
    actions: list[dict] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    parameter_names: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    capture_warnings: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    # draft | approved | replay_failed. Approval remains valid across replay attempts.
    status: str = Field(
        default="draft",
        sa_column=Column(sa.String(20), nullable=False, server_default="draft"),
    )
    replay_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    approved_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    last_replayed_at: datetime | None = Field(
        default=None, sa_column=Column(TZDateTime())
    )
    last_error: str | None = Field(default=None, sa_column=Column(Text()))


class WebBridgeTabBinding(SQLModel, table=True):
    __tablename__: str = "webbridge_tab_bindings"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "pairing_id",
            "tab_id",
            name="uq_webbridge_tab_bindings_pairing_tab",
        ),
        sa.UniqueConstraint(
            "pairing_id",
            "session_id",
            name="uq_webbridge_tab_bindings_pairing_session",
        ),
        sa.Index("ix_webbridge_tab_bindings_session", "session_id"),
        sa.Index("ix_webbridge_tab_bindings_expires", "expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    pairing_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    tab_id: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    origin: str = Field(default="", sa_column=Column(Text(), nullable=False))
    page_instance_id: str | None = Field(default=None, sa_column=Column(sa.String(128)))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    expires_at: datetime = Field(sa_column=Column(TZDateTime(), nullable=False))
