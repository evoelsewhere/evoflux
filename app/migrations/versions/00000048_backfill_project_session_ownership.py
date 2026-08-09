"""backfill project ownership for hidden standalone coding sessions

Revision ID: 00000048
Revises: 00000047
Create Date: 2026-08-10

Repositories owned by a Coding project are intentionally omitted from the
standalone Workspaces section. Older session resolution still allowed a
project-owned repository (or its worktree) to create a session with a NULL
project_id, leaving that session unreachable from both sidebar sections.

Only unambiguous memberships are repaired. A workspace shared by multiple
live Coding projects is left untouched because choosing one would silently
change its authorization scope.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000048"
down_revision: Union[str, Sequence[str], None] = "00000047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROJECT_MEMBERSHIP_FROM = """
FROM coding_workspaces AS opened
JOIN coding_workspaces AS owner
  ON owner.path = CASE
    WHEN opened.kind = 'worktree' AND opened.source_path IS NOT NULL
      THEN opened.source_path
    ELSE opened.path
  END
JOIN coding_project_workspaces AS link ON link.workspace_id = owner.id
JOIN coding_projects AS project ON project.id = link.project_id
WHERE opened.path = chat_sessions.workspace
  AND opened.hidden = FALSE
  AND opened.deleted_at IS NULL
  AND owner.hidden = FALSE
  AND owner.deleted_at IS NULL
  AND project.hidden = FALSE
  AND project.deleted_at IS NULL
  AND project.kind = 'coding'
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE chat_sessions
            SET project_id = (
              SELECT link.project_id
              {_PROJECT_MEMBERSHIP_FROM}
              LIMIT 1
            )
            WHERE mode = 'coding'
              AND project_id IS NULL
              AND workspace IS NOT NULL
              AND 1 = (
                SELECT COUNT(DISTINCT link.project_id)
                {_PROJECT_MEMBERSHIP_FROM}
              )
            """
        )
    )


def downgrade() -> None:
    # Ownership cannot be safely reversed: after upgrade there is no reliable
    # way to distinguish a repaired row from a legitimate project session.
    pass
