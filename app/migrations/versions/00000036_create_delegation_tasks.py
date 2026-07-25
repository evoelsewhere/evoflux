"""create durable delegation task ledger

Revision ID: 00000036
Revises: 00000035
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000036"
down_revision: Union[str, Sequence[str], None] = "00000035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delegation_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "lead_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delegator", sa.String(length=100), nullable=False),
        sa.Column("recipient", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("spec", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("dependencies", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deadline_at", TZDateTime(), nullable=True),
        sa.Column("dispatched_at", TZDateTime(), nullable=True),
        sa.Column("completed_at", TZDateTime(), nullable=True),
        sa.Column(
            "final_handoff_message_id",
            sa.Uuid(),
            sa.ForeignKey("session_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("last_rejection", sa.JSON(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
    )
    op.create_index(
        "ix_delegation_tasks_session_status",
        "delegation_tasks",
        ["lead_session_id", "status"],
    )
    op.create_index(
        "ix_delegation_tasks_recipient_status",
        "delegation_tasks",
        ["lead_session_id", "recipient", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delegation_tasks_recipient_status",
        table_name="delegation_tasks",
    )
    op.drop_index(
        "ix_delegation_tasks_session_status",
        table_name="delegation_tasks",
    )
    op.drop_table("delegation_tasks")
