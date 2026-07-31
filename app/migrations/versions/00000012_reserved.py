"""reserved migration

Revision ID: 00000012
Revises: 00000011
Create Date: 2026-06-30
"""

from typing import Sequence, Union

revision: str = "00000012"
down_revision: Union[str, Sequence[str], None] = "00000011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
