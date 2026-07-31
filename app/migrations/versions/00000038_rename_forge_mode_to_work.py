"""rename mode 'forge' to 'work'

Revision ID: 00000038
Revises: 00000037
Create Date: 2026-07-31

The default non-project team mode is now named ``work`` end to end. Rewrite
persisted sessions and scheduled tasks and move both server defaults while
keeping the application boundary compatible with older ``forge`` clients.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000038"
down_revision: Union[str, Sequence[str], None] = "00000037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE chat_sessions SET mode = 'work' WHERE mode IN ('normal', 'forge')"
    )
    op.execute(
        "UPDATE scheduled_task SET mode = 'work' WHERE mode IN ('normal', 'forge')"
    )
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="work",
        )
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="work",
        )


def downgrade() -> None:
    op.execute("UPDATE chat_sessions SET mode = 'forge' WHERE mode = 'work'")
    op.execute("UPDATE scheduled_task SET mode = 'forge' WHERE mode = 'work'")
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="forge",
        )
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="forge",
        )
