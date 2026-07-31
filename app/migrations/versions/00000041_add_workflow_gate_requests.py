"""add durable workflow gate requests

Revision ID: 00000041
Revises: 00000040
Create Date: 2026-08-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000041"
down_revision: Union[str, Sequence[str], None] = "00000040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_gate_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_run_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("answers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("resolved_at", TZDateTime(), nullable=True),
        sa.UniqueConstraint("request_id", name="uq_workflow_gate_requests_request"),
    )
    op.create_index(
        "ix_workflow_gate_requests_execution",
        "workflow_gate_requests",
        ["execution_id"],
    )
    op.create_index(
        "ix_workflow_gate_requests_status", "workflow_gate_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_gate_requests_status", table_name="workflow_gate_requests"
    )
    op.drop_index(
        "ix_workflow_gate_requests_execution", table_name="workflow_gate_requests"
    )
    op.drop_table("workflow_gate_requests")
