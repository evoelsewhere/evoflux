"""create WebBridge pairing and interaction tables

Revision ID: 00000026
Revises: 00000025
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000026"
down_revision: Union[str, Sequence[str], None] = "00000025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webbridge_pairings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column(
            "browser",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "version",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("credential_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("last_seen_at", TZDateTime(), nullable=False),
        sa.Column("revoked_at", TZDateTime(), nullable=True),
    )
    op.create_index(
        "ix_webbridge_pairings_credential_hash",
        "webbridge_pairings",
        ["credential_hash"],
        unique=True,
    )

    op.create_table(
        "webbridge_interactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pairing_id",
            sa.Uuid(),
            sa.ForeignKey("webbridge_pairings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interaction_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("delivery", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "target_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False, server_default=""),
        sa.Column("tab_id", sa.Integer(), nullable=True),
        sa.Column("page_instance_id", sa.String(length=128), nullable=True),
        sa.Column("payload_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("processed_at", TZDateTime(), nullable=True),
        sa.Column("dispatch_lease_until", TZDateTime(), nullable=True),
        sa.UniqueConstraint(
            "pairing_id",
            "interaction_id",
            name="uq_webbridge_interactions_pairing_interaction",
        ),
    )
    op.create_index(
        "ix_webbridge_interactions_pairing_created",
        "webbridge_interactions",
        ["pairing_id", "created_at"],
    )
    op.create_index(
        "ix_webbridge_interactions_session",
        "webbridge_interactions",
        ["target_session_id"],
    )

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
    op.drop_index(
        "ix_webbridge_tab_bindings_expires", table_name="webbridge_tab_bindings"
    )
    op.drop_index(
        "ix_webbridge_tab_bindings_session", table_name="webbridge_tab_bindings"
    )
    op.drop_table("webbridge_tab_bindings")
    op.drop_index(
        "ix_webbridge_interactions_session", table_name="webbridge_interactions"
    )
    op.drop_index(
        "ix_webbridge_interactions_pairing_created",
        table_name="webbridge_interactions",
    )
    op.drop_table("webbridge_interactions")
    op.drop_index(
        "ix_webbridge_pairings_credential_hash", table_name="webbridge_pairings"
    )
    op.drop_table("webbridge_pairings")
