"""EASD Specification-Driven and Agent-Driven Development records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, ForeignKey, JSON
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


def _json_column(*, nullable: bool, server_default: str | None = None) -> Column:
    json_type = JSON().with_variant(pg.JSONB(), "postgresql")
    if server_default is None:
        return Column(json_type, nullable=nullable)
    return Column(json_type, nullable=nullable, server_default=server_default)


class TraceRun(SQLModel, table=True):
    """One EASD Development Run in a Coding workspace or project."""

    __tablename__: str = "trace_runs"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_trace_runs_workspace_status", "workspace", "status"),
        sa.Index("ix_trace_runs_project_status", "project_id", "status"),
        sa.Index("ix_trace_runs_session", "session_id"),
        sa.Index(
            "uq_trace_runs_active_session",
            "session_id",
            unique=True,
            sqlite_where=sa.text(
                "session_id IS NOT NULL AND status IN "
                "('authoring', 'draft', 'accepted', 'planning', 'plan_review', "
                "'planned', 'active', 'reviewing', 'verifying')"
            ),
            postgresql_where=sa.text(
                "session_id IS NOT NULL AND status IN "
                "('authoring', 'draft', 'accepted', 'planning', 'plan_review', "
                "'planned', 'active', 'reviewing', 'verifying')"
            ),
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    project_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    workspace: str = Field(sa_column=Column(sa.String(), nullable=False))
    session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    title: str = Field(sa_column=Column(sa.String(240), nullable=False))
    intent: dict | None = Field(
        default=None,
        sa_column=_json_column(nullable=True),
    )
    # intent | authoring | draft | accepted | planning | plan_review | planned |
    # active | reviewing | verifying | converged | failed | cancelled
    status: str = Field(
        default="draft",
        sa_column=Column(sa.String(20), nullable=False, server_default="draft"),
    )
    # trivial | standard | cross_layer | critical
    risk_tier: str = Field(
        default="standard",
        sa_column=Column(sa.String(20), nullable=False, server_default="standard"),
    )
    # Deliberately not FKs: both revision tables reference this table, and
    # SQLite cannot add those circular relationships after CREATE TABLE. The
    # service validates run/spec/plan ownership before assignment.
    active_spec_revision_id: UUID | None = Field(default=None, index=True)
    active_plan_revision_id: UUID | None = Field(default=None, index=True)
    convergence_report: dict | None = Field(
        default=None,
        sa_column=_json_column(nullable=True),
    )
    converged_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    # --- Run execution options ---
    # Preferred model override for the next agent run step. When set, the agent
    # runtime uses this model instead of the workspace default.
    preferred_model: str | None = Field(
        default=None,
        sa_column=Column(sa.String(255), nullable=True),
    )
    # When True, compact (summarize) the session context before each run step.
    compact_before_run: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.text("0")),
    )
    # When True, automatically advance through run steps without waiting for
    # human approval between spec -> plan -> implement -> review -> verify.
    auto_pilot: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.text("0")),
    )


class TraceSpecRevision(SQLModel, table=True):
    """Immutable normalized specification revision for one EASD run."""

    __tablename__: str = "trace_spec_revisions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "run_id", "version", name="uq_trace_spec_revisions_run_version"
        ),
        sa.Index(
            "ix_trace_spec_revisions_run_status_version",
            "run_id",
            "status",
            "version",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("trace_runs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    version: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    # draft | accepted | superseded
    status: str = Field(
        default="draft",
        sa_column=Column(sa.String(20), nullable=False, server_default="draft"),
    )
    spec: dict = Field(
        default_factory=dict,
        sa_column=_json_column(nullable=False, server_default="{}"),
    )
    authoring: dict | None = Field(
        default=None,
        sa_column=_json_column(nullable=True),
    )
    content_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    accepted_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )


class TracePlanRevision(SQLModel, table=True):
    """Immutable normalized plan revision for one accepted EASD spec hash."""

    __tablename__: str = "trace_plan_revisions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "run_id", "version", name="uq_trace_plan_revisions_run_version"
        ),
        sa.Index(
            "ix_trace_plan_revisions_run_status_version",
            "run_id",
            "status",
            "version",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("trace_runs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    version: int = Field(sa_column=Column(sa.Integer(), nullable=False))
    # draft | accepted | superseded
    status: str = Field(
        default="draft",
        sa_column=Column(sa.String(20), nullable=False, server_default="draft"),
    )
    spec_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    plan: dict = Field(
        default_factory=dict,
        sa_column=_json_column(nullable=False, server_default="{}"),
    )
    authoring: dict | None = Field(
        default=None,
        sa_column=_json_column(nullable=True),
    )
    content_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    accepted_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )


class TraceEvidence(SQLModel, table=True):
    """Evidence for one or more acceptance criteria at one spec revision."""

    __tablename__: str = "trace_evidence"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "run_id", "source_key", name="uq_trace_evidence_run_source_key"
        ),
        sa.Index("ix_trace_evidence_run_created", "run_id", "created_at"),
        sa.Index("ix_trace_evidence_task", "delegation_task_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("trace_runs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    delegation_task_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("delegation_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    spec_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    criterion_ids: list[str] = Field(
        default_factory=list,
        sa_column=_json_column(nullable=False, server_default="[]"),
    )
    producer: str = Field(sa_column=Column(sa.String(120), nullable=False))
    # machine | review | manual | waiver
    kind: str = Field(sa_column=Column(sa.String(20), nullable=False))
    # passed | failed | inconclusive | waived
    result: str = Field(sa_column=Column(sa.String(20), nullable=False))
    summary: str = Field(sa_column=Column(sa.Text(), nullable=False))
    revision: str | None = Field(default=None, max_length=120)
    artifact_hash: str | None = Field(default=None, max_length=128)
    payload: dict = Field(
        default_factory=dict,
        sa_column=_json_column(nullable=False, server_default="{}"),
    )
    source_key: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )


class TraceDeviation(SQLModel, table=True):
    """Explicit implementation/specification deviation and its resolution."""

    __tablename__: str = "trace_deviations"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_trace_deviations_run_status", "run_id", "status"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("trace_runs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    spec_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    criterion_id: str | None = Field(default=None, max_length=100)
    delegation_task_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("delegation_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # open | approved | rejected | resolved
    status: str = Field(
        default="open",
        sa_column=Column(sa.String(20), nullable=False, server_default="open"),
    )
    blocking: bool = Field(
        default=True,
        sa_column=Column(sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    description: str = Field(sa_column=Column(sa.Text(), nullable=False))
    proposed_change: dict = Field(
        default_factory=dict,
        sa_column=_json_column(nullable=False, server_default="{}"),
    )
    resolution: str | None = Field(default=None, sa_column=Column(sa.Text()))
    resolved_spec_hash: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )
    resolved_at: datetime | None = Field(
        default=None,
        sa_column=Column(TZDateTime(), nullable=True),
    )


__all__ = [
    "TraceDeviation",
    "TraceEvidence",
    "TracePlanRevision",
    "TraceRun",
    "TraceSpecRevision",
]
