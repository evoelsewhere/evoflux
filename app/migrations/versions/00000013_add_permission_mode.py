"""add permission_mode to chat_sessions

Revision ID: 00000013
Revises: 00000012
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000013"
down_revision: Union[str, Sequence[str], None] = "00000012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "permission_mode",
                sa.String(length=20),
                server_default="auto",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("permission_mode")
