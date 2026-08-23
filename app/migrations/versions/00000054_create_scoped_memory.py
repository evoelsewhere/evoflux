"""create scoped durable memory tables

Revision ID: 00000054
Revises: 00000053
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000054"
down_revision: Union[str, Sequence[str], None] = "00000053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "confidence", sa.String(length=12), server_default="medium", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column(
            "origin", sa.String(length=24), server_default="extraction", nullable=False
        ),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", TZDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "content_hash",
            name="uq_memory_facts_scope_content",
        ),
    )
    op.create_index(
        "ix_memory_facts_scope_status_updated",
        "memory_facts",
        ["scope_type", "scope_id", "status", "updated_at"],
    )
    op.create_table(
        "memory_fact_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fact_id"], ["memory_facts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["session_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fact_id", "session_id", name="uq_memory_fact_evidence_session"
        ),
    )
    op.create_index(
        "ix_memory_fact_evidence_session",
        "memory_fact_evidence",
        ["session_id"],
    )
    op.create_table(
        "memory_extraction_states",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_assistant_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("pending_assistant_count", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="idle", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", TZDateTime(timezone=True), nullable=True),
        sa.Column("completed_at", TZDateTime(timezone=True), nullable=True),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("memory_extraction_states")
    op.drop_index("ix_memory_fact_evidence_session", table_name="memory_fact_evidence")
    op.drop_table("memory_fact_evidence")
    op.drop_index("ix_memory_facts_scope_status_updated", table_name="memory_facts")
    op.drop_table("memory_facts")
