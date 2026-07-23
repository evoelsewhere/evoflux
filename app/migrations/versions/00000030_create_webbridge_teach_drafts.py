"""create WebBridge Teach Mode drafts

Revision ID: 00000030
Revises: 00000029
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime


revision: str = "00000030"
down_revision: Union[str, Sequence[str], None] = "00000029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webbridge_teach_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pairing_id",
            sa.Uuid(),
            sa.ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tab_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("parameter_names", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="draft"
        ),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("approved_at", TZDateTime(), nullable=True),
        sa.Column("last_replayed_at", TZDateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_webbridge_teach_drafts_pairing_created",
        "webbridge_teach_drafts",
        ["pairing_id", "created_at"],
    )
    op.create_index(
        "ix_webbridge_teach_drafts_session",
        "webbridge_teach_drafts",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webbridge_teach_drafts_session", table_name="webbridge_teach_drafts"
    )
    op.drop_index(
        "ix_webbridge_teach_drafts_pairing_created",
        table_name="webbridge_teach_drafts",
    )
    op.drop_table("webbridge_teach_drafts")
