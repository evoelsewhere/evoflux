"""add AIM claims and workflow retry lineage

Revision ID: 00000035
Revises: 00000034
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000035"
down_revision: Union[str, Sequence[str], None] = "00000034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "workflow_executions",
        sa.Column("retry_of_execution_id", sa.Uuid(), nullable=True),
    )
    op.create_table(
        "aim_claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("coding_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.Uuid(),
            sa.ForeignKey("aim_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_name", sa.String(length=120), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", TZDateTime(), nullable=False),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint("unit_id", name="uq_aim_claims_unit"),
    )
    op.create_index(
        "ix_aim_claims_project_lease",
        "aim_claims",
        ["project_id", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_aim_claims_project_lease", table_name="aim_claims")
    op.drop_table("aim_claims")
    op.drop_column("workflow_executions", "retry_of_execution_id")
    op.drop_column("workflow_executions", "inputs")
