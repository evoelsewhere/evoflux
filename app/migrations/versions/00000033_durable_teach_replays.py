"""persist durable idempotent Teach replay state

Revision ID: 00000033
Revises: 00000032
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime


revision: str = "00000033"
down_revision: Union[str, Sequence[str], None] = "00000032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webbridge_teach_drafts",
        sa.Column("replay_execution_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "webbridge_teach_drafts",
        sa.Column("replay_next_step", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "webbridge_teach_drafts",
        sa.Column(
            "replay_state", sa.String(length=20), nullable=False, server_default="idle"
        ),
    )
    op.add_column(
        "webbridge_teach_drafts",
        sa.Column("replay_in_flight_step", sa.Integer(), nullable=True),
    )
    op.create_table(
        "webbridge_teach_replays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "draft_id",
            sa.Uuid(),
            sa.ForeignKey("webbridge_teach_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("start_step", sa.Integer(), nullable=False),
        sa.Column("end_step", sa.Integer(), nullable=False),
        sa.Column(
            "state", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("in_flight_step", sa.Integer(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("next_step", sa.Integer(), nullable=True),
        sa.Column("response_draft", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint(
            "draft_id",
            "idempotency_key",
            name="uq_webbridge_teach_replays_draft_key",
        ),
    )
    op.create_index(
        "ix_webbridge_teach_replays_draft_created",
        "webbridge_teach_replays",
        ["draft_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webbridge_teach_replays_draft_created",
        table_name="webbridge_teach_replays",
    )
    op.drop_table("webbridge_teach_replays")
    op.drop_column("webbridge_teach_drafts", "replay_in_flight_step")
    op.drop_column("webbridge_teach_drafts", "replay_state")
    op.drop_column("webbridge_teach_drafts", "replay_next_step")
    op.drop_column("webbridge_teach_drafts", "replay_execution_id")
