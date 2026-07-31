"""remove the retired session-section storage

Revision ID: 00000039
Revises: 00000038
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000039"
down_revision: Union[str, Sequence[str], None] = "00000038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Databases upgraded through the former revision still contain this
    # retired table; fresh databases do not.
    op.execute("DROP TABLE IF EXISTS session_chapters")


def downgrade() -> None:
    # The removed feature is intentionally not restored.
    pass
