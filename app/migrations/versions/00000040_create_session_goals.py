"""create durable session goals

Revision ID: 00000040
Revises: 00000039
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000040"
down_revision: Union[str, Sequence[str], None] = "00000039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_goals",
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("token_budget", sa.BigInteger(), nullable=True),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("time_used_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active_started_at", TZDateTime(), nullable=True),
        sa.Column("pause_reason", sa.String(length=50), nullable=True),
        sa.Column("blocker_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("blocker_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_details", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.Column("completed_at", TZDateTime(), nullable=True),
    )
    op.create_index(
        "ix_session_goals_status_updated",
        "session_goals",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_goals_status_updated", table_name="session_goals")
    op.drop_table("session_goals")
