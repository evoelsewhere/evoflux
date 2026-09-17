"""bind delegation to an ASDD change slug and drop the tables nothing creates

Revision ID: 00000065
Revises: 00000064
Create Date: 2026-09-16

ASDD keeps a change in the repository: `proposal.md` carries its status,
`specs/<capability>/spec.md` carries the contract, `evidence/` carries the
proof. Nothing in this database describes a change any more.

The migrations that created the five `trace_*` tables are gone, so a new
database never has them. A database created before that still does, and this
drops them — removal, not compatibility. There is no path that reads those rows
again, and the downgrade does not recreate them: the data has no shape to come
back to.

`delegation_tasks.trace_run_id` becomes `asdd_change_id`: a slug, not a foreign
key. A delegated mission records which change asked for it, and nothing here
breaks when that change is edited, renamed or archived.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000065"
down_revision: Union[str, Sequence[str], None] = "00000064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAD_TABLES = (
    "trace_evidence",
    "trace_deviations",
    "trace_plan_revisions",
    "trace_spec_revisions",
    "trace_runs",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "delegation_tasks" in existing:
        columns = {
            column["name"] for column in inspector.get_columns("delegation_tasks")
        }
        indexes = {index["name"] for index in inspector.get_indexes("delegation_tasks")}
        # SQLite's batch mode rebuilds the table and replays every index it
        # found, so an index on the column being dropped has to go first or the
        # replay fails on a column that no longer exists.
        if "ix_delegation_tasks_trace_run_id" in indexes:
            op.drop_index(
                "ix_delegation_tasks_trace_run_id", table_name="delegation_tasks"
            )
        # `batch_alter_table` is required on SQLite, which cannot drop a column
        # that participates in a foreign key without rebuilding the table.
        with op.batch_alter_table("delegation_tasks") as batch:
            if "asdd_change_id" not in columns:
                batch.add_column(
                    sa.Column("asdd_change_id", sa.String(length=80), nullable=True)
                )
            if "trace_run_id" in columns:
                batch.drop_column("trace_run_id")
        op.create_index(
            "ix_delegation_tasks_asdd_change_id",
            "delegation_tasks",
            ["asdd_change_id"],
            unique=False,
        )

    for table in _DEAD_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    op.drop_index("ix_delegation_tasks_asdd_change_id", table_name="delegation_tasks")
    with op.batch_alter_table("delegation_tasks") as batch:
        batch.add_column(sa.Column("trace_run_id", sa.Uuid(), nullable=True))
        batch.drop_column("asdd_change_id")
