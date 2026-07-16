"""add session_id to aim_runs

Revision ID: 00000022
Revises: 00000021
Create Date: 2026-07-17

Links each aim_run row to the AIM session that produced it so the Runs &
Reports panel can open the post-run Discussion transcript (spec v2.2 §5.3).
Nullable — runs recorded by old slash-commands or reindex have no session.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000022"
down_revision: Union[str, Sequence[str], None] = "00000021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("aim_runs", sa.Column("session_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("aim_runs", "session_id")
