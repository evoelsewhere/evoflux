"""drop the summary index that misroutes timeline queries

Revision ID: 00000052
Revises: 00000051

SQLite was selecting ``(session_id, is_summary)`` for the global team history
timeline, scanning every row for each member and sorting into a temporary
B-tree. The ordering index already resolves latest-summary lookups in reverse
time order, while each session retains at most one active summary.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000052"
down_revision: Union[str, Sequence[str], None] = "00000051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_session_messages_session_summary", table_name="session_messages")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ANALYZE session_messages")


def downgrade() -> None:
    op.create_index(
        "ix_session_messages_session_summary",
        "session_messages",
        ["session_id", "is_summary"],
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ANALYZE session_messages")
