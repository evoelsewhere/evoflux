"""Durable, non-secret metadata for remote connections and pairings."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class RemoteConnection(SQLModel, table=True):
    __tablename__: str = "remote_connections"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_remote_connections_enabled", "enabled"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    adapter: str = Field(sa_column=Column(sa.String(32), nullable=False))
    provider: str | None = Field(
        default=None,
        sa_column=Column(sa.String(32), nullable=True),
    )
    endpoint_url: str | None = Field(
        default=None,
        sa_column=Column(sa.String(2048), nullable=True),
    )
    inbound_watermark_cursor: str | None = Field(
        default=None,
        sa_column=Column(sa.String(64), nullable=True),
    )
    label: str = Field(sa_column=Column(sa.String(120), nullable=False))
    enabled: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    adapter_principal_id: str = Field(sa_column=Column(sa.String(128), nullable=False))
    adapter_username: str = Field(
        default="",
        sa_column=Column(sa.String(128), nullable=False, server_default=""),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class RemotePairing(SQLModel, table=True):
    __tablename__: str = "remote_pairings"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "connection_id",
            "principal_id",
            name="uq_remote_pairings_connection_principal",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "destination_id",
            name="uq_remote_pairings_connection_destination",
        ),
        sa.Index("ix_remote_pairings_connection", "connection_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    connection_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("remote_connections.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    principal_id: str = Field(sa_column=Column(sa.String(128), nullable=False))
    destination_id: str = Field(sa_column=Column(sa.String(128), nullable=False))
    label: str = Field(sa_column=Column(sa.String(120), nullable=False))
    display: str = Field(
        default="",
        sa_column=Column(sa.String(120), nullable=False, server_default=""),
    )
    notify_scope: str = Field(
        default="all",
        sa_column=Column(sa.String(20), nullable=False, server_default="all"),
    )
    response_mode: str = Field(
        default="live",
        sa_column=Column(sa.String(20), nullable=False, server_default="live"),
    )
    active_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    #: Optional phone-first pairing code hash (bcrypt).  Nullable so existing
    #: deep-link pairings and rows created before the phone-first flow are
    #: unaffected.
    pair_code_hash: str | None = Field(
        default=None,
        sa_column=Column(sa.String(128), nullable=True),
    )
    #: Wall-clock UTC expiry for the pairing code.  Nullable for the same
    #: reason as ``pair_code_hash``.
    pair_code_expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
