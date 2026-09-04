"""create code index chunks

Revision ID: 00000045
Revises: 00000044
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000045"
down_revision: Union[str, Sequence[str], None] = "00000044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_index_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("component_key", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualified_name", sa.String(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("docstring", sa.Text(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["code_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "component_key", name="uq_code_index_chunk_component"
        ),
    )
    op.create_index(
        "ix_code_index_chunks_workspace_id",
        "code_index_chunks",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_code_index_chunk_workspace_file",
        "code_index_chunks",
        ["workspace_id", "file_path"],
        unique=False,
    )
    op.create_index(
        "ix_code_index_chunk_workspace_node",
        "code_index_chunks",
        ["workspace_id", "node_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_code_index_chunk_workspace_node", table_name="code_index_chunks")
    op.drop_index("ix_code_index_chunk_workspace_file", table_name="code_index_chunks")
    op.drop_index("ix_code_index_chunks_workspace_id", table_name="code_index_chunks")
    op.drop_table("code_index_chunks")
