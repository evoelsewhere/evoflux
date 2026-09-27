"""create remote use sessions

Revision ID: 00000069
Revises: 00000068
Create Date: 2026-09-25

Single-device remote session lock rows for Tailscale Serve remote use.
One live row at a time; idle sessions expire 30 minutes after the last
heartbeat and are released by the service's idle sweep.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

# revision identifiers, used by Alembic.
revision: str = "00000069"
down_revision: Union[str, Sequence[str], None] = "00000068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "remote_use_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_login", sa.String(length=255), nullable=False),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("released_at", TZDateTime(timezone=True), nullable=True),
        sa.Column("idle_expires_at", TZDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_remote_use_sessions_user_login", "remote_use_sessions", ["user_login"]
    )
    op.create_index(
        "ix_remote_use_sessions_released_at", "remote_use_sessions", ["released_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_remote_use_sessions_released_at", table_name="remote_use_sessions"
    )
    op.drop_index("ix_remote_use_sessions_user_login", table_name="remote_use_sessions")
    op.drop_table("remote_use_sessions")
