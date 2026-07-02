"""create code_ambiguous_edges table

Revision ID: 00000016
Revises: 00000015
Create Date: 2026-07-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000016"
down_revision: Union[str, Sequence[str], None] = "00000015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_ambiguous_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("src_id", sa.Uuid(), nullable=False),
        sa.Column("dst_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("candidate_node_ids", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["coding_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["src_id"],
            ["code_nodes.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_cae_workspace_src",
        "code_ambiguous_edges",
        ["workspace_id", "src_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cae_workspace_src", table_name="code_ambiguous_edges")
    op.drop_table("code_ambiguous_edges")
