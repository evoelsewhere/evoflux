"""add Teach Mode capture warnings

Revision ID: 00000031
Revises: 00000030
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "00000031"
down_revision: Union[str, Sequence[str], None] = "00000030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webbridge_teach_drafts",
        sa.Column("capture_warnings", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("webbridge_teach_drafts", "capture_warnings")
