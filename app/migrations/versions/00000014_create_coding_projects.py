"""create coding_projects and coding_project_workspaces tables

Revision ID: 00000014
Revises: 00000013
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000014"
down_revision: Union[str, Sequence[str], None] = "00000013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coding_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "hidden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_coding_projects_created_at", "coding_projects", ["created_at"]
    )

    op.create_table(
        "coding_project_workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["coding_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["coding_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "workspace_id", name="uq_coding_project_workspaces_pair"
        ),
    )
    op.create_index(
        "ix_coding_project_workspaces_project",
        "coding_project_workspaces",
        ["project_id"],
    )
    op.create_index(
        "ix_coding_project_workspaces_workspace",
        "coding_project_workspaces",
        ["workspace_id"],
    )

    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("project_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_index("ix_chat_sessions_project_id", ["project_id"])
        batch_op.create_foreign_key(
            "fk_chat_sessions_project_id",
            "coding_projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_chat_sessions_project_id", type_="foreignkey")
        batch_op.drop_index("ix_chat_sessions_project_id")
        batch_op.drop_column("project_id")

    op.drop_index(
        "ix_coding_project_workspaces_workspace", "coding_project_workspaces"
    )
    op.drop_index(
        "ix_coding_project_workspaces_project", "coding_project_workspaces"
    )
    op.drop_table("coding_project_workspaces")
    op.drop_index("ix_coding_projects_created_at", "coding_projects")
    op.drop_table("coding_projects")
