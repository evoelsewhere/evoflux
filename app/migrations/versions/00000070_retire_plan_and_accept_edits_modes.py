"""retire the plan and accept-edits permission modes

Revision ID: 00000070
Revises: 00000069
Create Date: 2026-09-28

Permission modes are now ``ask`` (Ask for approval), ``auto`` (Approve for
me) and ``bypass`` (Full access). Sessions saved in the removed ``plan`` or
``accept-edits`` mode move to ``ask``, the closest remaining mode that never
runs an edit or command the user has not approved.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000070"
down_revision: Union[str, Sequence[str], None] = "00000069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE chat_sessions SET permission_mode = 'ask' "
        "WHERE permission_mode IN ('plan', 'accept-edits')"
    )


def downgrade() -> None:
    # Which sessions used a removed mode is not recorded; they stay on ``ask``.
    pass
