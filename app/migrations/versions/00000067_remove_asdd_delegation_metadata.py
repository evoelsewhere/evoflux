"""remove retired ASDD delegation metadata

Revision ID: 00000067
Revises: 00000066
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "00000067"
down_revision: Union[str, Sequence[str], None] = "00000066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("delegation_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_delegation_tasks_asdd_change_id")
        batch_op.drop_column("asdd_change_id")


def downgrade() -> None:
    with op.batch_alter_table("delegation_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("asdd_change_id", sa.String(length=80)))
        batch_op.create_index(
            "ix_delegation_tasks_asdd_change_id", ["asdd_change_id"], unique=False
        )
