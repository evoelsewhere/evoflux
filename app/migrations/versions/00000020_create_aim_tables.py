"""create aim tables and coding_projects.kind

Revision ID: 00000020
Revises: 00000019
Create Date: 2026-07-16

Adds the AIM (AI Innovation Modernization) state layer: a ``kind``
discriminator on ``coding_projects`` ("coding" | "aim"), plus three tables
(``aim_units``, ``aim_runs``, ``aim_links``) that index a migration
project's state. These historical tables were a rebuildable index — the KB
repo (git) was the actual source of truth — so this migration only creates
empty tables. Revision 00000043 later removes the AIM product surface.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000020"
down_revision: Union[str, Sequence[str], None] = "00000019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coding_projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=20),
                nullable=False,
                server_default="coding",
            )
        )

    op.create_table(
        "aim_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "phase", sa.String(length=20), nullable=False, server_default="inventory"
        ),
        sa.Column("wave", sa.Integer(), nullable=True),
        sa.Column("assignee", sa.String(length=120), nullable=True),
        sa.Column("source_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("target_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("complexity", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("kb_doc_path", sa.String(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["coding_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "module", "name", name="uq_aim_units_project_module_name"
        ),
    )
    with op.batch_alter_table("aim_units", schema=None) as batch_op:
        batch_op.create_index("ix_aim_units_project_phase", ["project_id", "phase"])
        batch_op.create_index("ix_aim_units_project_wave", ["project_id", "wave"])

    op.create_table(
        "aim_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("case_set", sa.String(length=60), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("report_path", sa.String(), nullable=True),
        sa.Column("workflow_execution_id", sa.String(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["aim_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("aim_runs", schema=None) as batch_op:
        batch_op.create_index("ix_aim_runs_unit_created", ["unit_id", "created_at"])
        batch_op.create_index("ix_aim_runs_unit_kind", ["unit_id", "kind"])

    op.create_table(
        "aim_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("from_ref", sa.String(length=255), nullable=False),
        sa.Column("to_ref", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["coding_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("aim_links", schema=None) as batch_op:
        batch_op.create_index("ix_aim_links_project_from", ["project_id", "from_ref"])
        batch_op.create_index("ix_aim_links_project_to", ["project_id", "to_ref"])


def downgrade() -> None:
    op.drop_table("aim_links")
    op.drop_table("aim_runs")
    op.drop_table("aim_units")
    with op.batch_alter_table("coding_projects", schema=None) as batch_op:
        batch_op.drop_column("kind")
