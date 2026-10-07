"""add source and imported_at to chat_sessions and memory_facts

Revision ID: 00000071
Revises: 00000070

Adds ``source`` and ``imported_at`` columns to ``chat_sessions`` and
``memory_facts`` so imported data can be distinguished from native data.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "00000071"
down_revision: str = "00000070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── chat_sessions ───────────────────────────────────────────────────
    op.add_column(
        "chat_sessions",
        sa.Column("source", sa.String(50), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("imported_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_chat_sessions_source",
        "chat_sessions",
        ["source"],
    )

    # ── memory_facts ────────────────────────────────────────────────────
    op.add_column(
        "memory_facts",
        sa.Column("source", sa.String(50), nullable=True),
    )
    op.add_column(
        "memory_facts",
        sa.Column("imported_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_memory_facts_source",
        "memory_facts",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_facts_source", table_name="memory_facts")
    op.drop_column("memory_facts", "imported_at")
    op.drop_column("memory_facts", "source")

    op.drop_index("ix_chat_sessions_source", table_name="chat_sessions")
    op.drop_column("chat_sessions", "imported_at")
    op.drop_column("chat_sessions", "source")
