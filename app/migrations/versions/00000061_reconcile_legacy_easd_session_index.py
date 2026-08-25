"""Reconcile the legacy EASD active-session uniqueness index.

Revision ID: 00000061
Revises: 00000060
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "00000061"
down_revision = "00000060"
branch_labels = None
depends_on = None

_ACTIVE_STATUSES = (
    "'authoring', 'draft', 'accepted', 'planning', 'plan_review', "
    "'planned', 'active', 'reviewing', 'verifying'"
)


def _session_owner_where() -> sa.TextClause:
    return sa.text(f"session_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES})")


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT session_id FROM trace_runs "
                "WHERE session_id IS NOT NULL "
                f"AND status IN ({_ACTIVE_STATUSES}) "
                "GROUP BY session_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot reconcile the EASD active-session index: multiple active "
            f"runs share session '{duplicate[0]}'. Resolve the duplicate runs "
            "before restarting EvoFlux."
        )

    with op.batch_alter_table("trace_runs") as batch_op:
        batch_op.drop_index("uq_trace_runs_active_session")
        batch_op.create_index(
            "uq_trace_runs_active_session",
            ["session_id"],
            unique=True,
            sqlite_where=_session_owner_where(),
            postgresql_where=_session_owner_where(),
        )


def downgrade() -> None:
    # Revision 00000060 had no single released index definition: it identifies
    # several development schemas consolidated into 00000055. Retain the safe
    # canonical index if Alembic is used manually to restamp to that marker.
    pass
