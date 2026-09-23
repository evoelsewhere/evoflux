"""drop workflow tables

Revision ID: 00000068
Revises: 00000067
Create Date: 2026-09-23

Removes the retired Workflows engine from the schema: the approval ledger,
the execution/node-run debug log, and the durable gate requests. None of
these rows were ever read back to resume work, so nothing is migrated.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000068"
down_revision: Union[str, Sequence[str], None] = "00000067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "ix_workflow_gate_requests_status", table_name="workflow_gate_requests"
    )
    op.drop_index(
        "ix_workflow_gate_requests_execution", table_name="workflow_gate_requests"
    )
    op.drop_table("workflow_gate_requests")
    op.drop_index("ix_workflow_node_runs_execution", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_executions_session", table_name="workflow_executions")
    op.drop_index("ix_workflow_executions_definition", table_name="workflow_executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_approvals")


def downgrade() -> None:
    op.create_table(
        "workflow_approvals",
        sa.Column("definition_hash", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("root", sa.String(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("approved_at", TZDateTime(), nullable=False),
    )

    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("definition_name", sa.String(length=120), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", TZDateTime(), nullable=False),
        sa.Column("ended_at", TZDateTime(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("retry_of_execution_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_workflow_executions_definition", "workflow_executions", ["definition_name"]
    )
    op.create_index(
        "ix_workflow_executions_session", "workflow_executions", ["session_id"]
    )

    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", TZDateTime(), nullable=False),
        sa.Column("ended_at", TZDateTime(), nullable=True),
    )
    op.create_index(
        "ix_workflow_node_runs_execution", "workflow_node_runs", ["execution_id"]
    )

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
