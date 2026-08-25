"""create workflow tables

Revision ID: 00000021
Revises: 00000020
Create Date: 2026-07-16

Workflows engine (documents/plans/workflows-feature-plan.md §5): a
per-content-hash approval ledger plus a best-effort execution debug log.
Execution rows are never read back to resume anything — live state is the
runner's in-memory ExecutionState — so empty tables are all this needs.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000021"
down_revision: Union[str, Sequence[str], None] = "00000020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_workflow_node_runs_execution", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_executions_session", table_name="workflow_executions")
    op.drop_index("ix_workflow_executions_definition", table_name="workflow_executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_approvals")
