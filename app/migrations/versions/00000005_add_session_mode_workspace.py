"""add session mode and workspace

Revision ID: 00000005
Revises: 00000004
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00000005"
down_revision: Union[str, Sequence[str], None] = "00000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "mode", sa.String(length=20), server_default="normal", nullable=False
            )
        )
        batch_op.add_column(sa.Column("workspace", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("workspace")
        batch_op.drop_column("mode")
