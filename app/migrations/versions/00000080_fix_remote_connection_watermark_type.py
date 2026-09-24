"""Fix the iMessage inbound watermark's column type.

The prior column (``inbound_watermark_at``, a ``DateTime``) assumed a
timestamp cursor. Neither real provider's catchup API works that way: imsg's
``messages.after`` takes an exclusive integer ``since_rowid``, and
BlueBubbles pages by its own opaque string cursor. Nothing had ever written
a real value through the old column, so there is no data to migrate — the
replacement is a plain opaque string column each provider adapter
interprets on its own terms (see ``app/remote/imessage/provider.py``).

Revision ID: 00000080
Revises: 00000079
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000080"
down_revision: str | Sequence[str] | None = "00000079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    has_old = "inbound_watermark_at" in columns
    has_cursor = "inbound_watermark_cursor" in columns
    if has_old:
        count = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT COUNT(*) FROM remote_connections "
                    "WHERE inbound_watermark_at IS NOT NULL"
                )
            )
            .scalar_one()
        )
        if count:
            raise RuntimeError(
                "Cannot convert stored remote timestamp watermarks to provider "
                "cursors automatically; export or clear those values before retrying."
            )
    if has_old or not has_cursor:
        with op.batch_alter_table("remote_connections") as batch_op:
            if has_old:
                batch_op.drop_column("inbound_watermark_at")
            if not has_cursor:
                batch_op.add_column(
                    sa.Column("inbound_watermark_cursor", sa.String(64), nullable=True)
                )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("remote_connections")
    }
    with op.batch_alter_table("remote_connections") as batch_op:
        if "inbound_watermark_cursor" in columns:
            batch_op.drop_column("inbound_watermark_cursor")
        if "inbound_watermark_at" not in columns:
            batch_op.add_column(
                sa.Column("inbound_watermark_at", TZDateTime(), nullable=True)
            )
