"""Add remote_pairings.notify_scope

Revision ID: 00000065
Revises: 00000064
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000065"
down_revision: str | Sequence[str] | None = "00000064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.drop_column("remote_pairings", "notify_scope")
