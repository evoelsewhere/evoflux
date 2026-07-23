"""keep one WebBridge tab binding per pairing and session

Revision ID: 00000032
Revises: 00000031
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "00000032"
down_revision: Union[str, Sequence[str], None] = "00000031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, pairing_id, session_id "
            "FROM webbridge_tab_bindings "
            "ORDER BY updated_at DESC, created_at DESC"
        )
    ).mappings()
    seen: set[tuple[object, object]] = set()
    duplicate_ids: list[object] = []
    for row in rows:
        key = (row["pairing_id"], row["session_id"])
        if key in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(key)
    for duplicate_id in duplicate_ids:
        connection.execute(
            sa.text("DELETE FROM webbridge_tab_bindings WHERE id = :id"),
            {"id": duplicate_id},
        )
    op.create_index(
        "uq_webbridge_tab_bindings_pairing_session",
        "webbridge_tab_bindings",
        ["pairing_id", "session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_webbridge_tab_bindings_pairing_session",
        table_name="webbridge_tab_bindings",
    )
