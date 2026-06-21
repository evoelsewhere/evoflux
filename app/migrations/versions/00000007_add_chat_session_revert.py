"""add chat session revert boundary

Revision ID: 00000007
Revises: 00000006
Create Date: 2026-05-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00000007"
down_revision: Union[str, Sequence[str], None] = "00000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revert", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("revert")
