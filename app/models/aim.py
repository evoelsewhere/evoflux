"""AIM (AI Innovation Modernization) migration-project state.

These three tables are a **local, rebuildable index**, not the system of
record — per ``documents/research/aim-framework.md`` §3.5, the actual
source of truth for a migration project's state is the KB repo itself
(``aim.yaml`` for project config, frontmatter in ``modules/<module>/<unit>.md``
for per-unit state, ``runs/<unit>/<run-id>/`` for run reports). These tables
exist purely so a dashboard/API can query by ``(project_id, phase)`` etc.
without walking the KB's markdown files on every request; ``app.services.aim
.reindex`` rebuilds them from the KB at any time.

Scoped to a :class:`~app.models.chat.CodingProject` with ``kind="aim"``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy import JSON, Column, ForeignKey, Text
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class AimUnit(SQLModel, table=True):
    """One migration unit (program, job, screen, table, api, ...).

    Identity is ``(project_id, module, name)`` — ``module`` namespaces the
    unit when the base source spans multiple repos, so ids from different
    repos (or different contributors extracting concurrently) never collide.
    """

    __tablename__: str = "aim_units"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id", "module", "name", name="uq_aim_units_project_module_name"
        ),
        sa.Index("ix_aim_units_project_phase", "project_id", "phase"),
        sa.Index("ix_aim_units_project_wave", "project_id", "wave"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    project_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(), ForeignKey("coding_projects.id", ondelete="CASCADE"), nullable=False
        ),
    )
    # Namespaces the unit across a multi-repo base source — e.g. "core-batch".
    module: str = Field(sa_column=Column(sa.String(120), nullable=False))
    # Unit name within its module — e.g. "PAYROLL01".
    name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    # Rulebook-defined taxonomy: program | job | copybook | screen | table |
    # api | ... — deliberately a free string, not an enum, since it varies
    # per rulebook (see rulebook.yaml's ``unit_kinds``).
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    # inventory -> understood -> designed -> converted -> equivalent -> cutover
    phase: str = Field(
        default="inventory",
        sa_column=Column(sa.String(20), nullable=False, server_default="inventory"),
    )
    wave: int | None = Field(default=None, sa_column=Column(sa.Integer()))
    # Free-text claim marker (a person's handle) — EvoFlux has no user model,
    # so this is not a foreign key. See aim-kb-conventions skill: "claim a
    # unit before working on it".
    assignee: str | None = Field(default=None, sa_column=Column(sa.String(120)))
    source_paths: list = Field(
        default_factory=list, sa_column=Column(JSON(), nullable=False, server_default="[]")
    )
    target_paths: list = Field(
        default_factory=list, sa_column=Column(JSON(), nullable=False, server_default="[]")
    )
    # Other units this one depends on, as "<module>/<name>" strings.
    depends_on: list = Field(
        default_factory=list, sa_column=Column(JSON(), nullable=False, server_default="[]")
    )
    # Free-form, rulebook/appraiser-defined — e.g. {"score": "medium", "reasons": [...]}.
    complexity: dict = Field(
        default_factory=dict, sa_column=Column(JSON(), nullable=False, server_default="{}")
    )
    # Relative path to this unit's doc in the KB repo, e.g.
    # "modules/core-batch/PAYROLL01.md" — the reindex source for this row.
    kb_doc_path: str | None = Field(default=None, sa_column=Column(sa.String()))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class AimRun(SQLModel, table=True):
    """A compare/convert/test run recorded against a unit.

    Indexed from ``runs/<unit>/<run-id>/meta.yaml`` in the KB (or written
    directly by the ``aim_compare``/``aim_units`` tools at run time) — either
    way this table is a queryable mirror, never edited by hand.
    """

    __tablename__: str = "aim_runs"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_aim_runs_unit_created", "unit_id", "created_at"),
        sa.Index("ix_aim_runs_unit_kind", "unit_id", "kind"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    unit_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(), ForeignKey("aim_units.id", ondelete="CASCADE"), nullable=False
        ),
    )
    # compare | convert | test
    kind: str = Field(sa_column=Column(sa.String(20), nullable=False))
    # pass | fail | acceptable_diff | error
    verdict: str = Field(sa_column=Column(sa.String(20), nullable=False))
    # e.g. "smoke", "full", or a specific case id — free string.
    case_set: str | None = Field(default=None, sa_column=Column(sa.String(60)))
    stats: dict = Field(
        default_factory=dict, sa_column=Column(JSON(), nullable=False, server_default="{}")
    )
    report_path: str | None = Field(default=None, sa_column=Column(sa.String()))
    # Deliberately NOT a foreign key — the Workflows engine's execution rows
    # are a best-effort debug log (see workflows-feature-plan.md §5), and a
    # run predates AIM-4/the Workflows engine entirely when triggered by a
    # plain slash command.
    workflow_execution_id: str | None = Field(default=None, sa_column=Column(sa.String()))
    # The AIM session that produced this run — NOT a DB foreign key (runs
    # recorded by plain slash commands predate the workflow engine, and the
    # chat_sessions table may live in a different DB shard eventually).
    session_id: UUID | None = Field(default=None, sa_column=Column(sa.Uuid(), nullable=True))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )


class AimLink(SQLModel, table=True):
    """One edge in the project's traceability matrix.

    Refs are opaque, prefixed strings so the matrix can point at anything —
    a business rule, a unit, a line of code, a test case, a run — without a
    web of nullable foreign keys: ``rule:BR-CORE-0001``, ``unit:<uuid>``,
    ``code:<repo>/path#L120``, ``test:<case-id>``, ``run:<uuid>``.
    """

    __tablename__: str = "aim_links"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_aim_links_project_from", "project_id", "from_ref"),
        sa.Index("ix_aim_links_project_to", "project_id", "to_ref"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    project_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(), ForeignKey("coding_projects.id", ondelete="CASCADE"), nullable=False
        ),
    )
    from_ref: str = Field(sa_column=Column(sa.String(255), nullable=False))
    to_ref: str = Field(sa_column=Column(sa.String(255), nullable=False))
    # Free string describing the relationship — e.g. "implements", "tested_by",
    # "cites", "acceptable_difference".
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    note: str | None = Field(default=None, sa_column=Column(Text()))
    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(TZDateTime(), nullable=False)
    )
