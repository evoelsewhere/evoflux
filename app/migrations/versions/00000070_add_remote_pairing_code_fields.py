"""Add remote_pairings pair_code_hash and pair_code_expires_at

Revision ID: 00000070
Revises: 00000069
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000070"
down_revision: str | Sequence[str] | None = "00000069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remote_pairings",
        sa.Column("pair_code_hash", sa.String(128), nullable=True),
    )
    op.add_column(
        "remote_pairings",
        sa.Column("pair_code_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("remote_pairings", "pair_code_expires_at")
    op.drop_column("remote_pairings", "pair_code_hash")
