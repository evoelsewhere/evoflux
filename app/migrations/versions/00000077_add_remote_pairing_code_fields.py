"""Add remote_pairings pair_code_hash and pair_code_expires_at

Revision ID: 00000077
Revises: 00000076
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000077"
down_revision: str | Sequence[str] | None = "00000076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "pair_code_hash" not in columns:
        op.add_column(
            "remote_pairings",
            sa.Column("pair_code_hash", sa.String(128), nullable=True),
        )
    if "pair_code_expires_at" not in columns:
        op.add_column(
            "remote_pairings",
            sa.Column("pair_code_expires_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_pairings")
    }
    if "pair_code_expires_at" in columns:
        op.drop_column("remote_pairings", "pair_code_expires_at")
    if "pair_code_hash" in columns:
        op.drop_column("remote_pairings", "pair_code_hash")
