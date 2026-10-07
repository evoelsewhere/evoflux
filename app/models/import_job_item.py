"""Per-item import journal used to report outcomes and safely undo imports."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImportJobItem(SQLModel, table=True):
    __tablename__: str = "import_job_items"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "job_id", "source_item_id", name="uq_import_job_item_source"
        ),
        sa.Index("ix_import_job_items_job_id_id", "job_id", "id"),
    )

    id: str = Field(sa_column=Column(sa.String(32), primary_key=True))
    job_id: str = Field(foreign_key="import_jobs.id", nullable=False)
    source_item_id: str = Field(sa_column=Column(sa.Text(), nullable=False))
    kind: str = Field(sa_column=Column(sa.String(40), nullable=False))
    label: str = Field(sa_column=Column(sa.Text(), nullable=False))
    operation: str = Field(sa_column=Column(sa.String(20), nullable=False))
    target_ref: str | None = Field(default=None, sa_column=Column(sa.Text()))
    outcome: str = Field(sa_column=Column(sa.String(24), nullable=False))
    reason: str | None = Field(default=None, sa_column=Column(sa.Text()))
    before_snapshot: str | None = Field(default=None, sa_column=Column(sa.Text()))
    after_fingerprint: str | None = Field(default=None, sa_column=Column(sa.String(64)))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(sa.DateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(sa.DateTime(), nullable=False),
    )
