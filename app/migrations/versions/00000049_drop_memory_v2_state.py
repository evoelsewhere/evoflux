"""drop obsolete parallel memory processing state

Revision ID: 00000049
Revises: 00000048

EvoFlux now has one Memory pipeline: Dream writes the canonical knowledge
graph and both automatic recall and ``memory_search`` read from it.  The old
content-hash processing table belonged to a second, unused maintenance loop.
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

revision: str = "00000049"
down_revision: Union[str, Sequence[str], None] = "00000048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("memory_processed_sources")


def downgrade() -> None:
    import_module(
        "app.migrations.versions.00000009_create_memory_processed_sources"
    ).upgrade()
