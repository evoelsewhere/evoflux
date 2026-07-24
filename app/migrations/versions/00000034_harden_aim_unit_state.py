"""harden AIM unit state

Revision ID: 00000034
Revises: 00000033
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000034"
down_revision: Union[str, Sequence[str], None] = "00000033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "aim_units",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "aim_units",
        sa.Column("last_transition_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("aim_units", "last_transition_id")
    op.drop_column("aim_units", "revision")
