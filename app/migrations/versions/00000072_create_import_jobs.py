"""create import_jobs history table

Revision ID: 00000072
Revises: 00000071

Creates the ``import_jobs`` table to track every import operation:
source, path, counts, status, and timestamps.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "00000072"
down_revision: str = "00000071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("detected_format", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("imported_counts", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("skipped_counts", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_import_jobs_created_at",
        "import_jobs",
        ["created_at"],
    )
    op.create_index(
        "ix_import_jobs_source",
        "import_jobs",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_jobs_source", table_name="import_jobs")
    op.drop_index("ix_import_jobs_created_at", table_name="import_jobs")
    op.drop_table("import_jobs")
