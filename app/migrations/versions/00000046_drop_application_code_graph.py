"""drop application-database code graph

Revision ID: 00000046
Revises: 00000045

The replacement is a regeneratable SQLite target per repository. Application
data no longer owns index state, symbol rows, or persisted cross-repo guesses.
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

revision: str = "00000046"
down_revision: Union[str, Sequence[str], None] = "00000045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These FTS tables were managed outside Alembic by the removed services.
    op.execute("DROP TABLE IF EXISTS code_index_chunk_fts")
    op.execute("DROP TABLE IF EXISTS code_node_fts")
    op.drop_table("code_index_chunks")
    op.drop_table("code_ambiguous_edges")
    op.drop_table("code_cross_repo_edges")
    op.drop_table("code_edges")
    op.drop_table("code_index_state")
    op.drop_table("code_nodes")


def downgrade() -> None:
    # Reuse the original table definitions so a downgrade restores the exact
    # schema that revision 45 exposed, including indexes and constraints.
    for module_name in (
        "00000011_create_code_graph",
        "00000015_create_cross_repo_edges",
        "00000016_create_ambiguous_edges",
        "00000017_add_code_node_qualified_name_index",
        "00000045_create_code_index_chunks",
    ):
        import_module(f"app.migrations.versions.{module_name}").upgrade()
