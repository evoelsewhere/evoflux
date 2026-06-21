"""add per-session model settings

Revision ID: 00000008
Revises: 00000007
Create Date: 2026-05-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00000008"
down_revision: Union[str, Sequence[str], None] = "00000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("thinking_level", sa.String(length=50), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("thinking_level")
        batch_op.drop_column("model")
