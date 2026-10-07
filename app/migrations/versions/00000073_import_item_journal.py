"""add per-item import journal and undo metadata

Revision ID: 00000073
Revises: 00000072
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "00000073"
down_revision: str | None = "00000072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions", sa.Column("source_item_id", sa.Text(), nullable=True)
    )
    op.create_index(
        "uq_chat_sessions_source_item_id",
        "chat_sessions",
        ["source", "source_item_id"],
        unique=True,
    )
    op.add_column(
        "import_jobs",
        sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "undo_state", sa.String(24), nullable=False, server_default="unavailable"
        ),
    )
    op.create_table(
        "import_job_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(32),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_item_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before_snapshot", sa.Text(), nullable=True),
        sa.Column("after_fingerprint", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "job_id", "source_item_id", name="uq_import_job_item_source"
        ),
    )
    op.create_index(
        "ix_import_job_items_job_id_id", "import_job_items", ["job_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_import_job_items_job_id_id", table_name="import_job_items")
    op.drop_table("import_job_items")
    op.drop_column("import_jobs", "undo_state")
    op.drop_column("import_jobs", "origin")
    op.drop_index("uq_chat_sessions_source_item_id", table_name="chat_sessions")
    op.drop_column("chat_sessions", "source_item_id")
