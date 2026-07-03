"""create coding workspace registry

Revision ID: 00000010
Revises: 00000009
Create Date: 2026-06-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

# revision identifiers, used by Alembic.
revision: str = "00000010"
down_revision: Union[str, Sequence[str], None] = "00000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coding_workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="repo", nullable=False),
        sa.Column("source_path", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("managed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", TZDateTime(timezone=True), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_coding_workspaces_path"),
    )
    with op.batch_alter_table("coding_workspaces", schema=None) as batch_op:
        batch_op.create_index(
            "ix_coding_workspaces_source_path", ["source_path"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("coding_workspaces", schema=None) as batch_op:
        batch_op.drop_index("ix_coding_workspaces_source_path")
    op.drop_table("coding_workspaces")
