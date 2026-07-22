"""add session_type and source_session_id to chat_sessions

Revision ID: 00000024
Revises: 00000023
Create Date: 2025-08-25

Add two new columns to support the Side Chat feature:
- session_type: VARCHAR(20) NOT NULL DEFAULT 'main' — distinguishes main,
  team_member, and side_chat sessions.
- source_session_id: UUID FK→chat_sessions.id, nullable, indexed — for side
  chats, points to the main session whose context they read from.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000024"
down_revision: Union[str, Sequence[str], None] = "00000023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "session_type",
            sa.String(20),
            nullable=False,
            server_default="main",
        ),
    )
    op.add_column(
        "chat_sessions",
        sa.Column(
            "source_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chat_sessions_source_session",
        "chat_sessions",
        ["source_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_source_session", table_name="chat_sessions")
    op.drop_column("chat_sessions", "source_session_id")
    op.drop_column("chat_sessions", "session_type")
