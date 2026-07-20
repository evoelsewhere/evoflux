"""add tags to chat_sessions

Revision ID: 00000023
Revises: 00000022
Create Date: 2026-07-19

Nullable JSON array of session tags (e.g. ["webbridge"]). Tags are set at
creation time by the team session resolve endpoint and matched by tag-set
equality: a tagged resolve never reuses an untagged session and vice versa.
The "webbridge" tag additionally scopes the team lead's tool access to the
webbridge tool only (see app/agent/mode/team/tier_policy.py). NULL means an
untagged session — all pre-existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000023"
down_revision: Union[str, Sequence[str], None] = "00000022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("tags", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_sessions", "tags")
