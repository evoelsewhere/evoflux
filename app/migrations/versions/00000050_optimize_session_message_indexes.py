"""optimize session message history indexes

Revision ID: 00000050
Revises: 00000049

The standalone session_id index is a prefix duplicate of both composite
indexes and adds write amplification to the hottest append table. History
cursors order by (created_at, id), so include the UUID tie-breaker in the
ordering index and refresh planner statistics after the replacement.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000050"
down_revision: Union[str, Sequence[str], None] = "00000049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_session_messages_session_id", table_name="session_messages")
    op.drop_index("ix_session_messages_session_created", table_name="session_messages")
    op.create_index(
        "ix_session_messages_session_created_id",
        "session_messages",
        ["session_id", "created_at", "id"],
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("ANALYZE session_messages")


def downgrade() -> None:
    op.drop_index(
        "ix_session_messages_session_created_id", table_name="session_messages"
    )
    op.create_index(
        "ix_session_messages_session_created",
        "session_messages",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_session_messages_session_id",
        "session_messages",
        ["session_id"],
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("ANALYZE session_messages")
