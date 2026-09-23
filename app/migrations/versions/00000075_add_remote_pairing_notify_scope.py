"""Add remote_pairings.notify_scope

Revision ID: 00000075
Revises: 00000074
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000075"
down_revision: str | Sequence[str] | None = "00000074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "notify_scope" not in columns:
        op.add_column(
            "remote_pairings",
            sa.Column(
                "notify_scope",
                sa.String(20),
                nullable=False,
                server_default="all",
            ),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "notify_scope" in columns:
        op.drop_column("remote_pairings", "notify_scope")
