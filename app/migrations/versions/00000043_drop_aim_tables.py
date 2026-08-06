"""drop AIM tables and delete AIM projects

Revision ID: 00000043
Revises: 00000042
Create Date: 2026-08-06

Removes the AIM product surface from the schema: deletes AIM sessions /
folders / projects, then drops the rebuildable AIM index tables. Keeps
``coding_projects.kind`` and the workflow retry columns introduced
alongside ``aim_claims`` in 00000035.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime

revision: str = "00000043"
down_revision: Union[str, Sequence[str], None] = "00000042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove AIM-owned product rows first so Work/Coding never see orphaned
    # ``mode='aim'`` sessions (or folders) after the mode triad shrinks.
    # Session messages cascade from chat_sessions; project_id FKs on sessions
    # are SET NULL, but we delete the sessions explicitly instead.
    op.execute(sa.text("DELETE FROM chat_sessions WHERE mode = 'aim'"))
    op.execute(sa.text("DELETE FROM session_folders WHERE mode = 'aim'"))
    op.execute(sa.text("DELETE FROM coding_projects WHERE kind = 'aim'"))
    op.drop_index("ix_aim_claims_project_lease", table_name="aim_claims")
    op.drop_table("aim_claims")
    op.drop_table("aim_links")
    op.drop_table("aim_runs")
    op.drop_table("aim_units")


def downgrade() -> None:
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
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_transition_id", sa.String(length=36), nullable=True),
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
        sa.Column("session_id", sa.Uuid(), nullable=True),
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

    op.create_table(
        "aim_claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("coding_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.Uuid(),
            sa.ForeignKey("aim_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_name", sa.String(length=120), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", TZDateTime(), nullable=False),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.UniqueConstraint("unit_id", name="uq_aim_claims_unit"),
    )
    op.create_index(
        "ix_aim_claims_project_lease",
        "aim_claims",
        ["project_id", "lease_expires_at"],
    )
