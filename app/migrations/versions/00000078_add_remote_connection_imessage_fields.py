"""Add iMessage remote connection metadata.

Revision ID: 00000078
Revises: 00000077
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000078"
down_revision: str | Sequence[str] | None = "00000077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    if "endpoint_url" not in columns:
        op.add_column(
            "remote_connections",
            sa.Column("endpoint_url", sa.String(2048), nullable=True),
        )
    if "inbound_watermark_at" not in columns:
        op.add_column(
            "remote_connections",
            sa.Column("inbound_watermark_at", TZDateTime(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    if "inbound_watermark_at" in columns:
        op.drop_column("remote_connections", "inbound_watermark_at")
    if "endpoint_url" in columns:
        op.drop_column("remote_connections", "endpoint_url")
