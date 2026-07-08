"""rename mode 'normal' to 'forge'

Revision ID: 00000019
Revises: 00000018
Create Date: 2026-07-08

The default (non-coding) team mode was called ``normal`` in code and DB
while the UI has always shown it as "Forge". Unify on ``forge``
everywhere: rewrite persisted rows and move the server defaults.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000019"
down_revision: Union[str, Sequence[str], None] = "00000018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE chat_sessions SET mode = 'forge' WHERE mode = 'normal'")
    op.execute("UPDATE scheduled_task SET mode = 'forge' WHERE mode = 'normal'")
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


def downgrade() -> None:
    op.execute("UPDATE chat_sessions SET mode = 'normal' WHERE mode = 'forge'")
    op.execute("UPDATE scheduled_task SET mode = 'normal' WHERE mode = 'forge'")
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="normal",
        )
    with op.batch_alter_table("scheduled_task", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="normal",
        )
