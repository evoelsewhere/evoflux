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
    # SQLite has no native ALTER for constraints — adding a column with an
    # inline ForeignKey via plain op.add_column() fails ("No support for
    # ALTER of constraints in SQLite dialect"). batch_alter_table recreates
    # the table under the hood, which is the supported path; see the
    # project_id / coding_projects FK in 00000014 for the same pattern.
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "session_type",
                sa.String(20),
                nullable=False,
                server_default="main",
            )
        )
        batch_op.add_column(sa.Column("source_session_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_chat_sessions_source_session", ["source_session_id"])
        batch_op.create_foreign_key(
            "fk_chat_sessions_source_session_id",
            "chat_sessions",
            ["source_session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_chat_sessions_source_session_id", type_="foreignkey"
        )
        batch_op.drop_index("ix_chat_sessions_source_session")
        batch_op.drop_column("source_session_id")
        batch_op.drop_column("session_type")
