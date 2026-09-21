"""Fix the iMessage inbound watermark's column type.

The prior column (``inbound_watermark_at``, a ``DateTime``) assumed a
timestamp cursor. Neither real provider's catchup API works that way: imsg's
``messages.after`` takes an exclusive integer ``since_rowid``, and
BlueBubbles pages by its own opaque string cursor. Nothing had ever written
a real value through the old column, so there is no data to migrate — the
replacement is a plain opaque string column each provider adapter
interprets on its own terms (see ``app/remote/imessage/provider.py``).

Revision ID: 00000073
Revises: 00000072
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000073"
down_revision: str | Sequence[str] | None = "00000072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("remote_connections", "inbound_watermark_at")
    op.add_column(
        "remote_connections",
        sa.Column("inbound_watermark_cursor", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("remote_connections", "inbound_watermark_cursor")
    op.add_column(
        "remote_connections",
        sa.Column("inbound_watermark_at", TZDateTime(), nullable=True),
    )
