"""drop the retired Artifact Fabric control plane

Revision ID: 00000051
Revises: 00000050
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000051"
down_revision: Union[str, Sequence[str], None] = "00000050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("artifact_reviews")
    op.drop_table("artifact_revisions")
    op.drop_table("artifact_jobs")


def downgrade() -> None:
    op.create_table(
        "artifact_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_format", sa.String(length=12), nullable=False),
        sa.Column(
            "lane", sa.String(length=32), nullable=False, server_default="native"
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="queued"
        ),
        sa.Column("workspace_root", sa.Text(), nullable=False),
        sa.Column("request_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_data", sa.JSON(), nullable=True),
        sa.Column("latest_revision_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.Column("completed_at", TZDateTime(), nullable=True),
        sa.Column("published_at", TZDateTime(), nullable=True),
    )
    op.create_index(
        "ix_artifact_jobs_session_created",
        "artifact_jobs",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_artifact_jobs_status_updated",
        "artifact_jobs",
        ["status", "updated_at"],
    )
    op.create_table(
        "artifact_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("artifact_format", sa.String(length=12), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("candidate_name", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("previews", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("qa", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("manifest_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("driver_version", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint(
            "job_id", "revision_number", name="uq_artifact_revisions_job_number"
        ),
    )
    op.create_index(
        "ix_artifact_revisions_job_created",
        "artifact_revisions",
        ["job_id", "created_at"],
    )
    op.create_index(
        "ix_artifact_revisions_hash",
        "artifact_revisions",
        ["content_sha256"],
    )
    op.create_table(
        "artifact_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column(
            "actor", sa.String(length=120), nullable=False, server_default="agent"
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", TZDateTime(), nullable=False),
    )
    op.create_index(
        "ix_artifact_reviews_revision_created",
        "artifact_reviews",
        ["revision_id", "created_at"],
    )
