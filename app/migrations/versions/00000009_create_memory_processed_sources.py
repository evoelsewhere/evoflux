"""create memory_processed_sources table

Revision ID: 00000009
Revises: 00000008
Create Date: 2026-05-31

Domain: MemoryProcessedSource. Tracks content-aware Dream v2 processing
state for raw memory sources.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

# revision identifiers, used by Alembic.
revision: str = "00000009"
down_revision: Union[str, Sequence[str], None] = "00000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create memory_processed_sources table."""
    op.create_table(
        "memory_processed_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("processed_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("pages_changed", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_memory_processed_sources_source",
        ),
    )
    with op.batch_alter_table("memory_processed_sources", schema=None) as batch_op:
        batch_op.create_index(
            "ix_memory_processed_sources_source_type", ["source_type"], unique=False
        )
        batch_op.create_index(
            "ix_memory_processed_sources_source_id", ["source_id"], unique=False
        )


def downgrade() -> None:
    """Drop memory_processed_sources table."""
    with op.batch_alter_table("memory_processed_sources", schema=None) as batch_op:
        batch_op.drop_index("ix_memory_processed_sources_source_id")
        batch_op.drop_index("ix_memory_processed_sources_source_type")
    op.drop_table("memory_processed_sources")
