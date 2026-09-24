"""Add remote connection provider metadata.

Revision ID: 00000079
Revises: 00000078
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000079"
down_revision: str | Sequence[str] | None = "00000078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    if "provider" not in columns:
        op.add_column(
            "remote_connections",
            sa.Column("provider", sa.String(32), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    if "provider" in columns:
        op.drop_column("remote_connections", "provider")
