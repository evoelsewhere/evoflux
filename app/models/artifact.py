"""Durable control-plane records for Artifact Fabric.

The database stores lifecycle and provenance only. Large document bytes and
page/slide previews live in the content-addressed artifact store.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from uuid_extensions import uuid7

import sqlalchemy as sa
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class ArtifactJob(SQLModel, table=True):
    """One inspect, validate, or preview/publish lifecycle."""

    __tablename__: str = "artifact_jobs"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_artifact_jobs_session_created", "session_id", "created_at"),
        sa.Index("ix_artifact_jobs_status_updated", "status", "updated_at"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    session_id: UUID | None = Field(default=None, sa_column=Column(sa.Uuid()))
    artifact_format: str = Field(sa_column=Column(sa.String(12), nullable=False))
    lane: str = Field(
        default="native",
        sa_column=Column(sa.String(32), nullable=False, server_default="native"),
    )
    action: str = Field(sa_column=Column(sa.String(20), nullable=False))
    # queued | running | completed | review_ready | published | failed | cancelled
    status: str = Field(
        default="queued",
        sa_column=Column(sa.String(24), nullable=False, server_default="queued"),
    )
    workspace_root: str = Field(sa_column=Column(Text(), nullable=False))
    request_data: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    result_data: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    error_data: dict | None = Field(default=None, sa_column=Column(JSON()))
    latest_revision_id: UUID | None = Field(default=None, sa_column=Column(sa.Uuid()))
    version: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    completed_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    published_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))


class ArtifactRevision(SQLModel, table=True):
    """Immutable candidate bytes and the QA evidence produced for them."""

    __tablename__: str = "artifact_revisions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "job_id", "revision_number", name="uq_artifact_revisions_job_number"
        ),
        sa.Index("ix_artifact_revisions_job_created", "job_id", "created_at"),
        sa.Index("ix_artifact_revisions_hash", "content_sha256"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    job_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            sa.ForeignKey("artifact_jobs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    revision_number: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    artifact_format: str = Field(sa_column=Column(sa.String(12), nullable=False))
    media_type: str = Field(sa_column=Column(sa.String(160), nullable=False))
    candidate_name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    content_sha256: str = Field(sa_column=Column(sa.String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(sa.BigInteger(), nullable=False))
    blob_key: str = Field(sa_column=Column(Text(), nullable=False))
    previews: list = Field(
        default_factory=list,
        sa_column=Column(JSON(), nullable=False, server_default="[]"),
    )
    qa: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    manifest_data: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    provenance: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    driver_version: str = Field(sa_column=Column(sa.String(64), nullable=False))
    protocol_version: int = Field(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


class ArtifactReview(SQLModel, table=True):
    """Audit record for accepting or rejecting one immutable revision."""

    __tablename__: str = "artifact_reviews"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_artifact_reviews_revision_created", "revision_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    revision_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            sa.ForeignKey("artifact_revisions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    decision: str = Field(sa_column=Column(sa.String(16), nullable=False))
    actor: str = Field(
        default="agent",
        sa_column=Column(sa.String(120), nullable=False, server_default="agent"),
    )
    comment: str | None = Field(default=None, sa_column=Column(Text()))
    evidence: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


__all__ = ["ArtifactJob", "ArtifactReview", "ArtifactRevision"]
