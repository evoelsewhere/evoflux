"""preserve side chat source identity

Revision ID: 00000025
Revises: 00000024
Create Date: 2026-07-22

``source_session_id`` intentionally uses ON DELETE SET NULL so side chats
survive deletion of their source session. Keep a second, non-FK UUID copy for
route authorization after the foreign key is cleared.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000025"
down_revision: Union[str, Sequence[str], None] = "00000024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("source_session_ref", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE chat_sessions "
            "SET source_session_ref = source_session_id "
            "WHERE session_type = 'side_chat' AND source_session_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "source_session_ref")
