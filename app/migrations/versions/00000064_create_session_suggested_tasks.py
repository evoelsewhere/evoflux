"""create the session suggested task table

Revision ID: 00000064
Revises: 00000063
Create Date: 2026-09-15

Backs the suggestion chips an agent raises for out-of-scope work. The rows
outlive the turn that created them, so the table is not derivable from the
transcript and needs its own storage.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000064"
down_revision: Union[str, Sequence[str], None] = "00000063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_suggested_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("tldr", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cwd", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("spawned_session_id", sa.Uuid(), nullable=True),
        sa.Column("worktree_path", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("dismiss_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["spawned_session_id"], ["chat_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "fingerprint",
            name="uq_session_suggested_tasks_fingerprint",
        ),
    )
    op.create_index(
        "ix_session_suggested_tasks_session_status",
        "session_suggested_tasks",
        ["session_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_suggested_tasks_session_status",
        table_name="session_suggested_tasks",
    )
    op.drop_table("session_suggested_tasks")
