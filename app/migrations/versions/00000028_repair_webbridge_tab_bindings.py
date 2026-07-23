"""repair missing WebBridge tab bindings table

Revision ID: 00000028
Revises: 00000027
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime


revision: str = "00000028"
down_revision: Union[str, Sequence[str], None] = "00000027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("webbridge_tab_bindings"):
        return

    op.create_table(
        "webbridge_tab_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pairing_id",
            sa.Uuid(),
            sa.ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tab_id", sa.Integer(), nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.Text(), nullable=False, server_default=""),
        sa.Column("page_instance_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.Column("expires_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint(
            "pairing_id",
            "tab_id",
            name="uq_webbridge_tab_bindings_pairing_tab",
        ),
    )
    op.create_index(
        "ix_webbridge_tab_bindings_session",
        "webbridge_tab_bindings",
        ["session_id"],
    )
    op.create_index(
        "ix_webbridge_tab_bindings_expires",
        "webbridge_tab_bindings",
        ["expires_at"],
    )


def downgrade() -> None:
    # Revision 00000026 declares this table for clean installs, so preserve it.
    pass
