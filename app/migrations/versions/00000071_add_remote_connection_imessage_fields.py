"""Add iMessage remote connection metadata.

Revision ID: 00000071
Revises: 00000070
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000071"
down_revision: str | Sequence[str] | None = "00000070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remote_connections",
        sa.Column("endpoint_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "remote_connections",
        sa.Column("inbound_watermark_at", TZDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("remote_connections", "inbound_watermark_at")
    op.drop_column("remote_connections", "endpoint_url")
