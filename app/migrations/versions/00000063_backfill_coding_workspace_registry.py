"""backfill the coding workspace registry from existing coding sessions

Revision ID: 00000063
Revises: 00000062
Create Date: 2026-09-12

The coding sidebar renders ``coding_workspaces`` rows only. Until now the row
was written by ``/sessions/resolve`` alone, and a repository opened through
the folder picker (or right after a clone) never reaches that write on its
first visit: the sidebar looks it up with ``existing_only``, finds no session,
and the chat stays a draft until the first message — which used to create the
session without registering anything. The repository was then invisible in
both sidebar sections, and stayed invisible across restarts, until the user
happened to open the same folder a second time.

The route now registers the workspace as well, but that only helps sessions
created from here on. Insert the missing rows for repositories that already
have a coding session.

Only rows that do not exist are inserted: a repository the user removed from
the sidebar is purged together with its sessions (see ``purge_workspace``), so
nothing here can resurrect one, and a row that exists keeps its own
hidden/name/kind state untouched.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime
from app.uuid7 import uuid7

revision: str = "00000063"
down_revision: Union[str, Sequence[str], None] = "00000062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_coding_workspaces = sa.table(
    "coding_workspaces",
    sa.column("id", sa.Uuid()),
    sa.column("path", sa.String()),
    sa.column("kind", sa.String(length=20)),
    sa.column("source_path", sa.String()),
    sa.column("name", sa.String(length=255)),
    sa.column("managed", sa.Boolean()),
    sa.column("hidden", sa.Boolean()),
    sa.column("deleted_at", TZDateTime(timezone=True)),
    sa.column("created_at", TZDateTime(timezone=True)),
    sa.column("updated_at", TZDateTime(timezone=True)),
)


def upgrade() -> None:
    conn = op.get_bind()
    unregistered = conn.execute(
        sa.text(
            """
            SELECT DISTINCT workspace
            FROM chat_sessions
            WHERE mode = 'coding'
              AND workspace IS NOT NULL
              AND TRIM(workspace) <> ''
              AND workspace NOT IN (SELECT path FROM coding_workspaces)
            """
        )
    ).all()
    if not unregistered:
        return

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        _coding_workspaces,
        [
            {
                "id": uuid7(),
                "path": path,
                # Worktree sessions are always created through the worktree
                # dialog, which registers both the worktree and its source
                # repository. Anything still missing a row is a plain repo.
                "kind": "repo",
                "source_path": None,
                "name": Path(path).name or path,
                "managed": False,
                "hidden": False,
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            }
            for (path,) in unregistered
        ],
    )


def downgrade() -> None:
    # Repaired rows are indistinguishable from rows the user's own activity
    # would have created, so removing them again would hide live workspaces.
    pass
