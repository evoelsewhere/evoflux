"""Create the EASD local runtime projection.

Revision ID: 00000055
Revises: 00000054

Repository YAML remains the collaborative source of truth. These tables are a
rebuildable local projection for session binding, queries, and agent execution.
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from alembic import op

from app.models.chat import TZDateTime

revision = "00000055"
down_revision = "00000054"
branch_labels = None
depends_on = None


def _json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(pg.JSONB(), "postgresql")


def _session_owner_where() -> sa.TextClause:
    return sa.text(
        "session_id IS NOT NULL AND status IN "
        "('authoring', 'draft', 'accepted', 'planning', 'plan_review', "
        "'planned', 'active', 'reviewing', 'verifying')"
    )


def upgrade() -> None:
    json_type = _json_type()
    op.create_table(
        "trace_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("workspace", sa.String(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("intent", json_type, nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column(
            "risk_tier", sa.String(length=20), server_default="standard", nullable=False
        ),
        sa.Column("active_spec_revision_id", sa.Uuid(), nullable=True),
        sa.Column("active_plan_revision_id", sa.Uuid(), nullable=True),
        sa.Column("convergence_report", json_type, nullable=True),
        sa.Column("converged_at", TZDateTime(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["coding_projects.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trace_runs_workspace_status", "trace_runs", ["workspace", "status"]
    )
    op.create_index(
        "ix_trace_runs_project_status", "trace_runs", ["project_id", "status"]
    )
    op.create_index("ix_trace_runs_session", "trace_runs", ["session_id"])
    op.create_index(
        "ix_trace_runs_active_spec_revision_id",
        "trace_runs",
        ["active_spec_revision_id"],
    )
    op.create_index(
        "ix_trace_runs_active_plan_revision_id",
        "trace_runs",
        ["active_plan_revision_id"],
    )
    op.create_index(
        "uq_trace_runs_active_session",
        "trace_runs",
        ["session_id"],
        unique=True,
        sqlite_where=_session_owner_where(),
        postgresql_where=_session_owner_where(),
    )

    op.create_table(
        "trace_spec_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column("spec", json_type, server_default="{}", nullable=False),
        sa.Column("authoring", json_type, nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("accepted_at", TZDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["trace_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "version", name="uq_trace_spec_revisions_run_version"
        ),
    )
    op.create_index(
        "ix_trace_spec_revisions_run_status_version",
        "trace_spec_revisions",
        ["run_id", "status", "version"],
    )

    op.create_table(
        "trace_plan_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("plan", json_type, server_default="{}", nullable=False),
        sa.Column("authoring", json_type, nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("accepted_at", TZDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["trace_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "version", name="uq_trace_plan_revisions_run_version"
        ),
    )
    op.create_index(
        "ix_trace_plan_revisions_run_status_version",
        "trace_plan_revisions",
        ["run_id", "status", "version"],
    )

    with op.batch_alter_table("delegation_tasks") as batch_op:
        batch_op.add_column(sa.Column("trace_run_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_delegation_tasks_trace_run_id",
            "trace_runs",
            ["trace_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_delegation_tasks_trace_run_id", ["trace_run_id"], unique=False
        )

    op.create_table(
        "trace_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("delegation_task_id", sa.Uuid(), nullable=True),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("criterion_ids", json_type, server_default="[]", nullable=False),
        sa.Column("producer", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("revision", sa.String(length=120), nullable=True),
        sa.Column("artifact_hash", sa.String(length=128), nullable=True),
        sa.Column("payload", json_type, server_default="{}", nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["trace_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delegation_task_id"], ["delegation_tasks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "source_key", name="uq_trace_evidence_run_source_key"
        ),
    )
    op.create_index(
        "ix_trace_evidence_run_created", "trace_evidence", ["run_id", "created_at"]
    )
    op.create_index("ix_trace_evidence_task", "trace_evidence", ["delegation_task_id"])

    op.create_table(
        "trace_deviations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("criterion_id", sa.String(length=100), nullable=True),
        sa.Column("delegation_task_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="open", nullable=False
        ),
        sa.Column("blocking", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("proposed_change", json_type, server_default="{}", nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_spec_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=False),
        sa.Column("updated_at", TZDateTime(), nullable=False),
        sa.Column("resolved_at", TZDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["trace_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delegation_task_id"], ["delegation_tasks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trace_deviations_run_status", "trace_deviations", ["run_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_trace_deviations_run_status", table_name="trace_deviations")
    op.drop_table("trace_deviations")
    op.drop_index("ix_trace_evidence_task", table_name="trace_evidence")
    op.drop_index("ix_trace_evidence_run_created", table_name="trace_evidence")
    op.drop_table("trace_evidence")
    with op.batch_alter_table("delegation_tasks") as batch_op:
        batch_op.drop_index("ix_delegation_tasks_trace_run_id")
        batch_op.drop_constraint("fk_delegation_tasks_trace_run_id", type_="foreignkey")
        batch_op.drop_column("trace_run_id")
    op.drop_index(
        "ix_trace_plan_revisions_run_status_version", table_name="trace_plan_revisions"
    )
    op.drop_table("trace_plan_revisions")
    op.drop_index(
        "ix_trace_spec_revisions_run_status_version", table_name="trace_spec_revisions"
    )
    op.drop_table("trace_spec_revisions")
    op.drop_index("uq_trace_runs_active_session", table_name="trace_runs")
    op.drop_index("ix_trace_runs_active_plan_revision_id", table_name="trace_runs")
    op.drop_index("ix_trace_runs_active_spec_revision_id", table_name="trace_runs")
    op.drop_index("ix_trace_runs_session", table_name="trace_runs")
    op.drop_index("ix_trace_runs_project_status", table_name="trace_runs")
    op.drop_index("ix_trace_runs_workspace_status", table_name="trace_runs")
    op.drop_table("trace_runs")
