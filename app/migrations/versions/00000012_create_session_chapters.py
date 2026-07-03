"""create session chapters table

Revision ID: 00000012
Revises: 00000011
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

# revision identifiers, used by Alembic.
revision: str = "00000012"
down_revision: Union[str, Sequence[str], None] = "00000011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_chapters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("wiki_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["session_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("session_chapters", schema=None) as batch_op:
        batch_op.create_index("ix_session_chapters_session_id", ["session_id"])
        batch_op.create_index(
            "ix_session_chapters_session_created", ["session_id", "created_at"]
        )


def downgrade() -> None:
    op.drop_table("session_chapters")
