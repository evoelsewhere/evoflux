"""create Git server API connections

Revision ID: 00000037
Revises: 00000036
Create Date: 2026-07-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000037"
down_revision: Union[str, Sequence[str], None] = "00000036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "git_server_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column(
            "scope", sa.String(length=20), nullable=False, server_default="server"
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("token_env_var", sa.String(length=255), nullable=False, unique=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
    )
    op.create_index(
        "ix_git_server_connections_host",
        "git_server_connections",
        ["host"],
    )
    op.create_index(
        "ix_git_server_connections_workspace",
        "git_server_connections",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_git_server_connections_workspace",
        table_name="git_server_connections",
    )
    op.drop_index(
        "ix_git_server_connections_host",
        table_name="git_server_connections",
    )
    op.drop_table("git_server_connections")
