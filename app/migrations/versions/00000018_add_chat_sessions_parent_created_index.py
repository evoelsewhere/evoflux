"""add index on chat_sessions (parent_session_id, created_at)

Revision ID: 00000018
Revises: 00000017
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000018"
down_revision: Union[str, Sequence[str], None] = "00000017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # chat_sessions had no index covering created_at, so the session-list
    # pagination and latest-top-level-session lookups (both filter on
    # parent_session_id and ORDER BY created_at DESC) degraded to full
    # scans as history grows — see chat_service.list_sessions_page /
    # get_latest_top_level_session.
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_chat_sessions_parent_created",
            ["parent_session_id", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_chat_sessions_parent_created")
