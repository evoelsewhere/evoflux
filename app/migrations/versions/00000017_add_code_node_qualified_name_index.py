"""add index on code_nodes.qualified_name

Revision ID: 00000017
Revises: 00000016
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000017"
down_revision: Union[str, Sequence[str], None] = "00000016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # code_nodes had indexes on (workspace_id, file_path/name/kind) but none
    # covering qualified_name, silently degrading every exact-qualified-name
    # lookup (cross-repo FQN resolution, find_nodes_by_name) to an unindexed
    # scan — see cross_repo.py's _build_sibling_indexes for the call site
    # this was measured against (2,751 rows on a real project).
    with op.batch_alter_table("code_nodes", schema=None) as batch_op:
        batch_op.create_index(
            "ix_code_nodes_workspace_qualified_name",
            ["workspace_id", "qualified_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("code_nodes", schema=None) as batch_op:
        batch_op.drop_index("ix_code_nodes_workspace_qualified_name")
