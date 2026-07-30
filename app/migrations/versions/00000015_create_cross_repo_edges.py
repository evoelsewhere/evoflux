"""create code_cross_repo_edges table

Revision ID: 00000015
Revises: 00000014
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000015"
down_revision: Union[str, Sequence[str], None] = "00000014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_cross_repo_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("src_workspace_id", sa.Uuid(), nullable=False),
        sa.Column("src_node_id", sa.Uuid(), nullable=True),
        sa.Column("src_file_path", sa.String(), nullable=False),
        sa.Column("src_line", sa.Integer(), nullable=True),
        sa.Column("raw_reference", sa.String(), nullable=False),
        sa.Column("dst_name_hint", sa.String(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="unresolved",
        ),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("dst_workspace_id", sa.Uuid(), nullable=True),
        sa.Column("dst_node_id", sa.Uuid(), nullable=True),
        sa.Column("dst_qualified_name", sa.String(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["coding_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["src_workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["src_node_id"], ["code_nodes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dst_workspace_id"], ["coding_workspaces.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dst_node_id"], ["code_nodes.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("code_cross_repo_edges", schema=None) as batch_op:
        batch_op.create_index("ix_cre_project_status", ["project_id", "status"])
        batch_op.create_index(
            "ix_cre_project_src_ws", ["project_id", "src_workspace_id"]
        )
        batch_op.create_index(
            "ix_cre_project_dst_ws", ["project_id", "dst_workspace_id"]
        )


def downgrade() -> None:
    op.drop_table("code_cross_repo_edges")
