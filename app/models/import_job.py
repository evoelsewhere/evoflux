"""Import job history model for tracking import operations."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImportJob(SQLModel, table=True):
    __tablename__: str = "import_jobs"  # type: ignore[reportIncompatibleVariableOverride]

    id: str = Field(sa_column=Column(sa.String(32), primary_key=True))
    source: str = Field(sa_column=Column(sa.String(50), nullable=False, index=True))
    source_path: str = Field(sa_column=Column(sa.Text(), nullable=False))
    detected_format: str = Field(sa_column=Column(sa.String(50), nullable=False))
    origin: str = Field(
        default="manual",
        sa_column=Column(sa.String(20), nullable=False, server_default="manual"),
    )
    undo_state: str = Field(
        default="unavailable",
        sa_column=Column(
            sa.String(24), nullable=False, server_default="unavailable"
        ),
    )
    status: str = Field(
        default="completed",
        sa_column=Column(sa.String(20), nullable=False, server_default="completed"),
    )
    imported_counts: str = Field(
        default="{}",
        sa_column=Column(sa.Text(), nullable=False, server_default="{}"),
    )
    skipped_counts: str = Field(
        default="{}",
        sa_column=Column(sa.Text(), nullable=False, server_default="{}"),
    )
    error_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    item_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(sa.DateTime(), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(sa.DateTime(), nullable=True),
    )
