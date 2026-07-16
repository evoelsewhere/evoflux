"""Workflow tables (plan §5): a per-hash approval ledger and a best-effort
execution debug log.

``workflow_executions``/``workflow_node_runs`` are **never read to resume
anything** — all live state is the runner's in-memory ``ExecutionState``;
these rows exist so a human can debug what a run did after the fact.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class WorkflowApproval(SQLModel, table=True):
    """One approved definition content-hash (plan §7). Editing the file
    changes the hash → the definition needs re-approval."""

    __tablename__: str = "workflow_approvals"  # type: ignore[reportIncompatibleVariableOverride]

    definition_hash: str = Field(sa_column=Column(sa.String(64), primary_key=True))
    name: str = Field(sa_column=Column(sa.String(120), nullable=False))
    # "workspace:<path>" | "global" | "builtin" — approvals never transfer
    # across roots (a workspace file shadowing a global name re-approves).
    root: str = Field(sa_column=Column(sa.String(), nullable=False))
    manifest: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    approved_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


class WorkflowExecution(SQLModel, table=True):
    __tablename__: str = "workflow_executions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_workflow_executions_definition", "definition_name"),
        sa.Index("ix_workflow_executions_session", "session_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    definition_name: str = Field(sa_column=Column(sa.String(120), nullable=False))
    definition_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    # Ordinary chat session it ran in; no FK (FK enforcement is off anyway).
    session_id: UUID = Field(sa_column=Column(sa.Uuid(), nullable=False))
    # running | waiting_gate | completed | failed | stopped
    # (waiting_gate covers ANY human pause — gate or input node)
    status: str = Field(
        default="running",
        sa_column=Column(sa.String(20), nullable=False, server_default="running"),
    )
    error: str | None = Field(default=None, sa_column=Column(Text()))
    outputs: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON(), nullable=False, server_default="{}"),
    )
    started_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    ended_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))


class WorkflowNodeRun(SQLModel, table=True):
    __tablename__: str = "workflow_node_runs"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_workflow_node_runs_execution", "execution_id"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    execution_id: UUID = Field(sa_column=Column(sa.Uuid(), nullable=False))
    node_id: str = Field(sa_column=Column(sa.String(120), nullable=False))
    # foreach item index (NULL for non-foreach nodes)
    iteration: int | None = Field(default=None, sa_column=Column(sa.Integer()))
    # running | succeeded | failed | skipped
    status: str = Field(
        default="running",
        sa_column=Column(sa.String(20), nullable=False, server_default="running"),
    )
    # Capped at 32 KB by the writer — debug log, not an artifact store.
    output: dict | None = Field(default=None, sa_column=Column(JSON()))
    error: str | None = Field(default=None, sa_column=Column(Text()))
    started_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    ended_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
