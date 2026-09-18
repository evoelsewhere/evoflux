"""Add remote_pairings.response_mode

Revision ID: 00000069
Revises: 00000068
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000069"
down_revision: str | Sequence[str] | None = "00000068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.drop_column("remote_pairings", "response_mode")
