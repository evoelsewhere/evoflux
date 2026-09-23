"""Add remote_pairings.response_mode

Revision ID: 00000076
Revises: 00000075
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000076"
down_revision: str | Sequence[str] | None = "00000075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "response_mode" not in columns:
        op.add_column(
            "remote_pairings",
            sa.Column(
                "response_mode",
                sa.String(20),
                nullable=False,
                server_default="live",
            ),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "response_mode" in columns:
        op.drop_column("remote_pairings", "response_mode")
