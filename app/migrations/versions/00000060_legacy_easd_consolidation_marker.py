"""Recognize the legacy pre-consolidation EASD migration head.

Revision ID: 00000060
Revises: 00000055

Development builds originally introduced the EASD projection across revisions
00000055 through 00000060. Before release, those schema changes were
consolidated into 00000055, but local databases created by the development
builds retained the 00000060 stamp. Keeping this no-op lineage marker lets
Alembic move those databases forward without replaying changes already present
in the consolidated migration.
"""

from __future__ import annotations

revision = "00000060"
down_revision = "00000055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
