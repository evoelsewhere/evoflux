"""create code knowledge graph tables

Revision ID: 00000011
Revises: 00000010
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

# revision identifiers, used by Alembic.
revision: str = "00000011"
down_revision: Union[str, Sequence[str], None] = "00000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualified_name", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(), nullable=True),
        sa.Column("docstring", sa.Text(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("code_nodes", schema=None) as batch_op:
        batch_op.create_index("ix_code_nodes_workspace_id", ["workspace_id"])
        batch_op.create_index(
            "ix_code_nodes_workspace_file", ["workspace_id", "file_path"]
        )
        batch_op.create_index("ix_code_nodes_workspace_name", ["workspace_id", "name"])
        batch_op.create_index("ix_code_nodes_workspace_kind", ["workspace_id", "kind"])

    op.create_table(
        "code_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("src_id", sa.Uuid(), nullable=False),
        sa.Column("dst_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["src_id"], ["code_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dst_id"], ["code_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("code_edges", schema=None) as batch_op:
        batch_op.create_index("ix_code_edges_workspace_id", ["workspace_id"])
        batch_op.create_index("ix_code_edges_src", ["workspace_id", "src_id", "kind"])
        batch_op.create_index("ix_code_edges_dst", ["workspace_id", "dst_id", "kind"])
        batch_op.create_index(
            "ix_code_edges_workspace_file", ["workspace_id", "file_path"]
        )

    op.create_table(
        "code_index_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("node_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("edge_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "file_path",
            name="uq_code_index_state_workspace_file",
        ),
    )
    with op.batch_alter_table("code_index_state", schema=None) as batch_op:
        batch_op.create_index("ix_code_index_state_workspace_id", ["workspace_id"])
        batch_op.create_index("ix_code_index_state_workspace", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("code_index_state")
    op.drop_table("code_edges")
    op.drop_table("code_nodes")
