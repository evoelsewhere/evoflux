"""repair legacy orphan rows before enabling foreign-key enforcement

Revision ID: 00000053
Revises: 00000052

Older SQLite connections did not enable ``PRAGMA foreign_keys``. Deletions
therefore skipped declared CASCADE/SET NULL actions and left inaccessible rows.
This migration applies those actions explicitly and refuses to complete while
any declared foreign-key violation remains.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "00000053"
down_revision: Union[str, Sequence[str], None] = "00000052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    tables = {
        str(row[0])
        for row in bind.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    # Reproduce the recursive CASCADE of a missing team lead. The temporary
    # identity set lets dependent tables apply their own declared action before
    # the session rows disappear while enforcement is still disabled.
    op.execute("CREATE TEMP TABLE _evoflux_orphan_sessions (id TEXT PRIMARY KEY)")
    op.execute(
        """
        WITH RECURSIVE doomed(id) AS (
          SELECT child.id
          FROM chat_sessions AS child
          LEFT JOIN chat_sessions AS parent ON parent.id = child.parent_session_id
          WHERE child.parent_session_id IS NOT NULL AND parent.id IS NULL
          UNION
          SELECT child.id
          FROM chat_sessions AS child
          JOIN doomed AS parent ON child.parent_session_id = parent.id
        )
        INSERT INTO _evoflux_orphan_sessions(id) SELECT id FROM doomed
        """
    )
    op.execute(
        "DELETE FROM webbridge_teach_replays WHERE draft_id IN ("
        "SELECT id FROM webbridge_teach_drafts WHERE session_id IN "
        "(SELECT id FROM _evoflux_orphan_sessions))"
    )
    for table in (
        "session_goals",
        "webbridge_tab_bindings",
        "webbridge_teach_drafts",
        "delegation_tasks",
    ):
        column = "lead_session_id" if table == "delegation_tasks" else "session_id"
        op.execute(
            f"DELETE FROM {table} WHERE {column} IN "
            "(SELECT id FROM _evoflux_orphan_sessions)"
        )
    op.execute(
        "UPDATE delegation_tasks SET final_handoff_message_id = NULL "
        "WHERE final_handoff_message_id IN ("
        "SELECT id FROM session_messages WHERE session_id IN "
        "(SELECT id FROM _evoflux_orphan_sessions))"
    )
    op.execute(
        "DELETE FROM session_messages WHERE session_id IN "
        "(SELECT id FROM _evoflux_orphan_sessions)"
    )
    if "design_transaction_records" in tables:
        op.execute(
            "UPDATE design_transaction_records SET session_id = NULL "
            "WHERE session_id IN (SELECT id FROM _evoflux_orphan_sessions)"
        )
    op.execute(
        "UPDATE webbridge_interactions SET target_session_id = NULL "
        "WHERE target_session_id IN (SELECT id FROM _evoflux_orphan_sessions)"
    )
    op.execute(
        "UPDATE chat_sessions SET source_session_id = NULL WHERE source_session_id IN "
        "(SELECT id FROM _evoflux_orphan_sessions)"
    )
    op.execute(
        "DELETE FROM chat_sessions WHERE id IN "
        "(SELECT id FROM _evoflux_orphan_sessions)"
    )
    op.execute("DROP TABLE _evoflux_orphan_sessions")

    # Apply every remaining SET NULL / CASCADE action to legacy drift.
    op.execute(
        "UPDATE chat_sessions SET source_session_id = NULL "
        "WHERE source_session_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM chat_sessions parent WHERE parent.id = source_session_id)"
    )
    op.execute(
        "UPDATE chat_sessions SET project_id = NULL "
        "WHERE project_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM coding_projects p WHERE p.id = project_id)"
    )
    op.execute(
        "UPDATE chat_sessions SET folder_id = NULL "
        "WHERE folder_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM session_folders f WHERE f.id = folder_id)"
    )
    op.execute(
        "UPDATE scheduled_task SET project_id = NULL "
        "WHERE project_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM coding_projects p WHERE p.id = project_id)"
    )
    op.execute(
        "DELETE FROM coding_project_workspaces WHERE "
        "NOT EXISTS (SELECT 1 FROM coding_projects p WHERE p.id = project_id) "
        "OR NOT EXISTS (SELECT 1 FROM coding_workspaces w WHERE w.id = workspace_id)"
    )
    if {"design_transaction_records", "design_documents"} <= tables:
        op.execute(
            "DELETE FROM design_transaction_records WHERE "
            "NOT EXISTS (SELECT 1 FROM design_documents d WHERE d.id = document_id) "
            "OR document_id IN (SELECT d.id FROM design_documents d WHERE NOT EXISTS ("
            "SELECT 1 FROM coding_workspaces w WHERE w.id = d.workspace_id))"
        )
    if "design_documents" in tables:
        op.execute(
            "DELETE FROM design_documents WHERE NOT EXISTS ("
            "SELECT 1 FROM coding_workspaces w WHERE w.id = workspace_id)"
        )
    op.execute(
        "DELETE FROM git_server_connections WHERE NOT EXISTS ("
        "SELECT 1 FROM coding_workspaces w WHERE w.id = workspace_id)"
    )
    op.execute(
        "DELETE FROM delegation_tasks WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = lead_session_id)"
    )
    op.execute(
        "DELETE FROM session_goals WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = session_id)"
    )
    op.execute(
        "DELETE FROM webbridge_tab_bindings WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = session_id)"
    )
    op.execute(
        "DELETE FROM webbridge_teach_replays WHERE NOT EXISTS ("
        "SELECT 1 FROM webbridge_teach_drafts d WHERE d.id = draft_id)"
    )
    op.execute(
        "DELETE FROM webbridge_teach_drafts WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = session_id)"
    )
    op.execute(
        "DELETE FROM webbridge_teach_replays WHERE NOT EXISTS ("
        "SELECT 1 FROM webbridge_teach_drafts d WHERE d.id = draft_id)"
    )
    if "design_transaction_records" in tables:
        op.execute(
            "UPDATE design_transaction_records SET session_id = NULL "
            "WHERE session_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM chat_sessions s WHERE s.id = session_id)"
        )
    op.execute(
        "UPDATE webbridge_interactions SET target_session_id = NULL "
        "WHERE target_session_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = target_session_id)"
    )
    op.execute(
        "UPDATE delegation_tasks SET final_handoff_message_id = NULL "
        "WHERE final_handoff_message_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM session_messages m WHERE m.id = final_handoff_message_id)"
    )
    op.execute(
        "DELETE FROM session_messages WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_sessions s WHERE s.id = session_id)"
    )

    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"Foreign-key repair left {len(violations)} violation(s): {violations[:5]}"
        )


def downgrade() -> None:
    # Data repair is intentionally irreversible. Older application versions
    # can still read the repaired schema at revision 52.
    return
