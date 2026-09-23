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
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("delegation_tasks")
    }
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("delegation_tasks")
    }
    if (
        "asdd_change_id" not in columns
        and "ix_delegation_tasks_asdd_change_id" not in indexes
    ):
        return

    with op.batch_alter_table("delegation_tasks", schema=None) as batch_op:
        if "ix_delegation_tasks_asdd_change_id" in indexes:
            batch_op.drop_index("ix_delegation_tasks_asdd_change_id")
        if "asdd_change_id" in columns:
            batch_op.drop_column("asdd_change_id")


def downgrade() -> None:
    with op.batch_alter_table("delegation_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("asdd_change_id", sa.String(length=80)))
        batch_op.create_index(
            "ix_delegation_tasks_asdd_change_id", ["asdd_change_id"], unique=False
        )
