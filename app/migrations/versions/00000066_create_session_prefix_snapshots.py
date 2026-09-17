"""create persistent session prompt-prefix snapshots"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000066"
down_revision: Union[str, Sequence[str], None] = "00000065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_prefix_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("system_hash", sa.String(length=64), nullable=False),
        sa.Column("tools_hash", sa.String(length=64), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("watermark_message_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "profile_key",
            name="uq_session_prefix_snapshots_profile",
        ),
    )
    op.create_index(
        "ix_session_prefix_snapshots_session_updated",
        "session_prefix_snapshots",
        ["session_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_prefix_snapshots_session_updated",
        table_name="session_prefix_snapshots",
    )
    op.drop_table("session_prefix_snapshots")
