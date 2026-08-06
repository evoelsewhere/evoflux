"""add scheduler project routing target

Revision ID: 00000044
Revises: 00000043
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000044"
down_revision: Union[str, Sequence[str], None] = "00000043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_scheduled_task_project_id", ["project_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_scheduled_task_project_id",
            "coding_projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scheduled_task_project_id", type_="foreignkey")
        batch_op.drop_index("ix_scheduled_task_project_id")
        batch_op.drop_column("project_id")
