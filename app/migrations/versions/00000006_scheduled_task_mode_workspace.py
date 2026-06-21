"""replace scheduled_task.agent with mode + workspace

Revision ID: 00000006
Revises: 00000005
Create Date: 2026-05-15

The ``agent`` column was never used for routing — scheduled tasks have
always been delivered to the team lead.  Replace it with ``mode`` +
``workspace`` so users can schedule reminders for either the default
team (``mode='normal'``) or a coding workspace
(``mode='coding'`` + workspace path).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00000006"
down_revision: Union[str, Sequence[str], None] = "00000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "mode",
                sa.String(length=20),
                nullable=False,
                server_default="normal",
            )
        )
        batch_op.add_column(sa.Column("workspace", sa.String(), nullable=True))
        batch_op.drop_column("agent")


def downgrade() -> None:
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "agent",
                sa.String(length=100),
                nullable=False,
                server_default="",
            )
        )
        batch_op.drop_column("workspace")
        batch_op.drop_column("mode")
