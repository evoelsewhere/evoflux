"""Add run execution options: preferred_model, compact_before_run, auto_pilot.

Revision ID: 00000062
Revises: 00000061
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "00000062"
down_revision = "00000061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trace_runs",
        sa.Column("preferred_model", sa.String(255), nullable=True),
    )
    op.add_column(
        "trace_runs",
        sa.Column(
            "compact_before_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "trace_runs",
        sa.Column(
            "auto_pilot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("trace_runs", "auto_pilot")
    op.drop_column("trace_runs", "compact_before_run")
    op.drop_column("trace_runs", "preferred_model")
