"""Remote tailnet session rows behind the single-device remote-use lock."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime
from app.uuid7 import uuid7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RemoteUseSession(SQLModel, table=True):
    """One remote tailnet session claiming the single-device lock.

    A row is *live* while ``released_at`` is NULL and ``idle_expires_at``
    (``last_seen_at`` plus the 30-minute idle window) has not passed. Only
    one live row may exist at a time: a claim from a different
    ``user_login``/``device_label`` pair while another row is live fails
    with HTTP 409.
    """

    __tablename__ = "remote_use_sessions"
    __table_args__ = (
        sa.Index("ix_remote_use_sessions_user_login", "user_login"),
        sa.Index("ix_remote_use_sessions_released_at", "released_at"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    #: Tailnet login carried by the Tailscale Serve identity header.
    user_login: str = Field(
        max_length=255, sa_column=Column(sa.String(255), nullable=False)
    )
    #: Device the claim came from: explicit label header or User-Agent.
    device_label: str | None = Field(
        default=None,
        max_length=128,
        sa_column=Column(sa.String(128), nullable=True),
    )
    claimed_at: datetime = Field(sa_column=Column(TZDateTime(), nullable=False))
    last_seen_at: datetime = Field(sa_column=Column(TZDateTime(), nullable=False))
    released_at: datetime | None = Field(
        default=None, sa_column=Column(TZDateTime(), nullable=True)
    )
    idle_expires_at: datetime = Field(sa_column=Column(TZDateTime(), nullable=False))
