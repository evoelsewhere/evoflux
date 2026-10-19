"""Index session messages carrying WebBridge artifact metadata.

Revision ID: 00000075
Revises: 00000074
Create Date: 2026-10-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "00000075"
down_revision = "00000074"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_session_messages_webbridge_artifact"
_WHERE = sa.text("""instr(CAST(extra AS TEXT), '"webbridge_artifact"') > 0""")


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.create_index(
        _INDEX_NAME,
        "session_messages",
        ["id", "session_id", "extra"],
        unique=False,
        sqlite_where=_WHERE,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(_INDEX_NAME, table_name="session_messages")
