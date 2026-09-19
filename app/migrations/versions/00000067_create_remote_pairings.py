"""create remote connection and pairing tables

Revision ID: 00000067
Revises: 00000066
Create Date: 2026-09-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000067"
down_revision: Union[str, Sequence[str], None] = "00000066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "remote_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("adapter_principal_id", sa.String(length=128), nullable=False),
        sa.Column(
            "adapter_username", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
    )
    op.create_index(
        "ix_remote_connections_enabled", "remote_connections", ["enabled"]
    )

    op.create_table(
        "remote_pairings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("remote_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("destination_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("display", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "active_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("last_seen_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint(
            "connection_id",
            "principal_id",
            name="uq_remote_pairings_connection_principal",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "destination_id",
            name="uq_remote_pairings_connection_destination",
        ),
    )
    op.create_index(
        "ix_remote_pairings_connection", "remote_pairings", ["connection_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_remote_pairings_connection", table_name="remote_pairings")
    op.drop_table("remote_pairings")
    op.drop_index("ix_remote_connections_enabled", table_name="remote_connections")
    op.drop_table("remote_connections")
