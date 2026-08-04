"""create session folders and link chat sessions to them

Revision ID: 00000042
Revises: 00000041
Create Date: 2026-08-04

Sidebar folders for Work-mode sessions. ``chat_sessions.folder_id`` is
nullable with ON DELETE SET NULL: deleting a folder un-files its sessions
instead of destroying conversations. Existing rows stay unfiled (NULL).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000042"
down_revision: Union[str, Sequence[str], None] = "00000041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_folders",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="work"),
        sa.Column(
            "share_context", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
    )
    op.create_index(
        "ix_session_folders_mode_sort",
        "session_folders",
        ["mode", "sort_order"],
    )
    # SQLite cannot ALTER a column into a foreign key, so the constraint is
    # declared through batch_alter_table (a table rebuild there, a plain
    # ALTER on Postgres).
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("folder_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_chat_sessions_folder_id",
            "session_folders",
            ["folder_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_chat_sessions_folder_id", "chat_sessions", ["folder_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_folder_id", table_name="chat_sessions")
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_constraint("fk_chat_sessions_folder_id", type_="foreignkey")
        batch_op.drop_column("folder_id")
    op.drop_index("ix_session_folders_mode_sort", table_name="session_folders")
    op.drop_table("session_folders")
