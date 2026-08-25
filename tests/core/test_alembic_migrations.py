"""Alembic smoke test — the full migration chain upgrades a fresh SQLite DB.

Runs ``alembic upgrade head`` against a temp database using the real
``app/alembic.ini`` and asserts the latest schema state lands (currently:
WebBridge pairing, interaction, tab-binding, Teach Mode state, delegation
tasks, Git server connections, the Work mode rename, retired session-section
cleanup, durable goals, durable workflow gates, the AIM table drop, scheduler
routing, and application-database graph removal through revision 00000046).
Revision 00000048 repairs project-owned Coding sessions hidden by the sidebar;
revision 00000049 removes the retired parallel Memory processing table, and
revision 00000051 removes the retired Artifact Fabric tables.
Complements ``tests/core/test_db_extra.py``, which only covers
``run_migrations`` error paths with mocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from pydantic import SecretStr

import app
from app.core.config import settings
from app.core.schema_version import SCHEMA_HEAD


def test_alembic_upgrade_head_adds_latest_schema(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "migrate.sqlite"
    # env.py reads the URL from settings, not from the .ini — point it at the
    # temp DB for the duration of the upgrade.
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        columns = {c["name"] for c in sa.inspect(engine).get_columns("chat_sessions")}
        assert "tags" in columns
        assert "session_type" in columns
        assert "source_session_id" in columns
        assert "source_session_ref" in columns
        fk_columns = {
            col
            for fk in sa.inspect(engine).get_foreign_keys("chat_sessions")
            for col in fk["constrained_columns"]
        }
        assert "source_session_id" in fk_columns
        inspector = sa.inspect(engine)
        assert {
            "webbridge_pairings",
            "webbridge_interactions",
            "webbridge_tab_bindings",
            "webbridge_teach_drafts",
            "webbridge_teach_replays",
            "git_server_connections",
        } <= set(inspector.get_table_names())
        assert {
            "artifact_jobs",
            "artifact_revisions",
            "artifact_reviews",
        }.isdisjoint(inspector.get_table_names())
        assert "session_chapters" not in inspector.get_table_names()
        assert "memory_processed_sources" not in inspector.get_table_names()
        assert {
            "memory_facts",
            "memory_fact_evidence",
            "memory_extraction_states",
        } <= set(inspector.get_table_names())
        assert {
            "trace_runs",
            "trace_spec_revisions",
            "trace_plan_revisions",
            "trace_evidence",
            "trace_deviations",
        } <= set(inspector.get_table_names())
        active_run_index = next(
            index
            for index in inspector.get_indexes("trace_runs")
            if index["name"] == "uq_trace_runs_active_session"
        )
        assert active_run_index["unique"] == 1
        with engine.connect() as conn:
            active_run_index_sql = conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_master WHERE type='index' "
                    "AND name='uq_trace_runs_active_session'"
                )
            ).scalar_one()
        assert "authoring" in active_run_index_sql
        assert "planning" in active_run_index_sql
        assert "reviewing" in active_run_index_sql
        run_columns = {column["name"] for column in inspector.get_columns("trace_runs")}
        assert "intent" in run_columns
        assert "active_plan_revision_id" in run_columns
        delegation_columns = {
            column["name"] for column in inspector.get_columns("delegation_tasks")
        }
        assert "trace_run_id" in delegation_columns
        deviation_columns = {
            column["name"] for column in inspector.get_columns("trace_deviations")
        }
        assert "spec_hash" in deviation_columns
        revision_columns = {
            column["name"] for column in inspector.get_columns("trace_spec_revisions")
        }
        assert "authoring" in revision_columns
        plan_columns = {
            column["name"] for column in inspector.get_columns("trace_plan_revisions")
        }
        assert {"spec_hash", "plan", "authoring", "content_hash"} <= plan_columns
        assert "session_goals" in inspector.get_table_names()
        assert {
            "code_nodes",
            "code_edges",
            "code_index_state",
            "code_index_chunks",
            "code_cross_repo_edges",
            "code_ambiguous_edges",
        }.isdisjoint(inspector.get_table_names())
        goal_columns = {
            column["name"] for column in inspector.get_columns("session_goals")
        }
        assert {
            "session_id",
            "objective",
            "status",
            "token_budget",
            "tokens_used",
            "time_used_seconds",
            "active_started_at",
            "pause_reason",
            "blocker_fingerprint",
            "blocker_streak",
            "status_details",
            "version",
            "completed_at",
        } <= goal_columns
        interaction_columns = {
            column["name"] for column in inspector.get_columns("webbridge_interactions")
        }
        assert {
            "request_hash",
            "prompt",
            "dispatch_lease_until",
        } <= interaction_columns
        teach_draft_columns = {
            column["name"] for column in inspector.get_columns("webbridge_teach_drafts")
        }
        assert {
            "pairing_id",
            "session_id",
            "actions",
            "parameter_names",
            "capture_warnings",
            "status",
            "replay_count",
            "replay_execution_id",
            "replay_next_step",
            "replay_state",
            "replay_in_flight_step",
        } <= teach_draft_columns
        teach_replay_columns = {
            column["name"]
            for column in inspector.get_columns("webbridge_teach_replays")
        }
        assert {
            "draft_id",
            "execution_id",
            "idempotency_key",
            "request_hash",
            "start_step",
            "end_step",
            "state",
            "steps",
            "response_draft",
        } <= teach_replay_columns
        assert "aim_units" not in inspector.get_table_names()
        assert "aim_runs" not in inspector.get_table_names()
        assert "aim_links" not in inspector.get_table_names()
        assert "aim_claims" not in inspector.get_table_names()
        assert "workflow_gate_requests" in inspector.get_table_names()
        workflow_execution_columns = {
            column["name"] for column in inspector.get_columns("workflow_executions")
        }
        assert {"inputs", "retry_of_execution_id"} <= workflow_execution_columns
        gate_request_columns = {
            column["name"] for column in inspector.get_columns("workflow_gate_requests")
        }
        assert {
            "execution_id",
            "node_run_id",
            "node_id",
            "kind",
            "request_id",
            "question",
            "options",
            "status",
            "answers",
            "created_at",
            "resolved_at",
        } <= gate_request_columns
        binding_unique_indexes = {
            index["name"]
            for index in inspector.get_indexes("webbridge_tab_bindings")
            if index.get("unique")
        }
        assert "uq_webbridge_tab_bindings_pairing_session" in binding_unique_indexes
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == SCHEMA_HEAD
    finally:
        engine.dispose()


def test_legacy_easd_revision_60_migrates_forward_without_data_loss(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "legacy-easd-60.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000055")

    run_id = uuid4().hex
    now = datetime.now(timezone.utc)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO trace_runs "
                    "(id, workspace, title, status, risk_tier, created_at, updated_at) "
                    "VALUES (:id, :workspace, :title, :status, :risk_tier, "
                    ":created_at, :updated_at)"
                ),
                {
                    "id": run_id,
                    "workspace": "/tmp/legacy-easd",
                    "title": "Preserve this run",
                    "status": "accepted",
                    "risk_tier": "standard",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.execute(sa.text("DROP INDEX uq_trace_runs_active_session"))
            conn.execute(
                sa.text(
                    "CREATE UNIQUE INDEX uq_trace_runs_active_session "
                    "ON trace_runs (session_id) "
                    "WHERE session_id IS NOT NULL AND status IN "
                    "('authoring', 'planning', 'active', 'reviewing', 'verifying')"
                )
            )
            conn.execute(sa.text("UPDATE alembic_version SET version_num = '00000060'"))
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            preserved_title = conn.execute(
                sa.text("SELECT title FROM trace_runs WHERE id = :id"),
                {"id": run_id},
            ).scalar_one()
            active_run_index_sql = conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_master WHERE type='index' "
                    "AND name='uq_trace_runs_active_session'"
                )
            ).scalar_one()

        assert version == SCHEMA_HEAD
        assert preserved_title == "Preserve this run"
        assert "'accepted'" in active_run_index_sql
        assert "'plan_review'" in active_run_index_sql
        assert "'planned'" in active_run_index_sql
    finally:
        engine.dispose()


def test_work_mode_migration_rewrites_forge_rows_and_defaults(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "work-mode-rename.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )
    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000037")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO chat_sessions "
                    "(id, mode, permission_mode, session_type, created_at, updated_at) "
                    "VALUES ('legacy-forge-session', 'forge', 'auto', 'main', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        inspector = sa.inspect(engine)
        chat_mode = next(
            column
            for column in inspector.get_columns("chat_sessions")
            if column["name"] == "mode"
        )
        task_mode = next(
            column
            for column in inspector.get_columns("scheduled_task")
            if column["name"] == "mode"
        )
        with engine.connect() as conn:
            mode = conn.execute(
                sa.text(
                    "SELECT mode FROM chat_sessions WHERE id = 'legacy-forge-session'"
                )
            ).scalar_one()
        assert mode == "work"
        assert chat_mode["default"] == "'work'"
        assert task_mode["default"] == "'work'"
    finally:
        engine.dispose()


def test_project_session_ownership_migration_repairs_only_unambiguous_rows(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "project-session-ownership.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )
    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000047")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    now = datetime.now(timezone.utc)
    project_a_id = uuid4().hex
    project_b_id = uuid4().hex
    owned_workspace_id = uuid4().hex
    worktree_workspace_id = uuid4().hex
    ambiguous_workspace_id = uuid4().hex
    owned_session_id = uuid4().hex
    worktree_session_id = uuid4().hex
    ambiguous_session_id = uuid4().hex
    standalone_session_id = uuid4().hex
    try:
        metadata = sa.MetaData()
        projects = sa.Table("coding_projects", metadata, autoload_with=engine)
        workspaces = sa.Table("coding_workspaces", metadata, autoload_with=engine)
        links = sa.Table("coding_project_workspaces", metadata, autoload_with=engine)
        sessions = sa.Table("chat_sessions", metadata, autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(
                projects.insert(),
                [
                    {
                        "id": project_a_id,
                        "name": "Project A",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": project_b_id,
                        "name": "Project B",
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )
            conn.execute(
                workspaces.insert(),
                [
                    {
                        "id": owned_workspace_id,
                        "path": "/repo/owned",
                        "kind": "repo",
                        "source_path": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": worktree_workspace_id,
                        "path": "/repo/worktree",
                        "kind": "worktree",
                        "source_path": "/repo/owned",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ambiguous_workspace_id,
                        "path": "/repo/shared",
                        "kind": "repo",
                        "source_path": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )
            conn.execute(
                links.insert(),
                [
                    {
                        "id": uuid4().hex,
                        "project_id": project_a_id,
                        "workspace_id": owned_workspace_id,
                        "created_at": now,
                    },
                    {
                        "id": uuid4().hex,
                        "project_id": project_a_id,
                        "workspace_id": ambiguous_workspace_id,
                        "created_at": now,
                    },
                    {
                        "id": uuid4().hex,
                        "project_id": project_b_id,
                        "workspace_id": ambiguous_workspace_id,
                        "created_at": now,
                    },
                ],
            )
            conn.execute(
                sessions.insert(),
                [
                    {
                        "id": owned_session_id,
                        "mode": "coding",
                        "workspace": "/repo/owned",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": worktree_session_id,
                        "mode": "coding",
                        "workspace": "/repo/worktree",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ambiguous_session_id,
                        "mode": "coding",
                        "workspace": "/repo/shared",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": standalone_session_id,
                        "mode": "coding",
                        "workspace": "/repo/standalone",
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        sessions = sa.Table("chat_sessions", sa.MetaData(), autoload_with=engine)
        with engine.connect() as conn:
            ownership = dict(
                conn.execute(
                    sa.select(sessions.c.id, sessions.c.project_id).where(
                        sessions.c.id.in_(
                            [
                                owned_session_id,
                                worktree_session_id,
                                ambiguous_session_id,
                                standalone_session_id,
                            ]
                        )
                    )
                ).all()
            )
        assert ownership[owned_session_id] == project_a_id
        assert ownership[worktree_session_id] == project_a_id
        assert ownership[ambiguous_session_id] is None
        assert ownership[standalone_session_id] is None
    finally:
        engine.dispose()


def test_webbridge_prompt_repair_migrates_drifted_revision_26_database(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "webbridge-prompt-repair.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000026")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("ALTER TABLE webbridge_interactions DROP COLUMN prompt")
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        columns = {
            column["name"]
            for column in sa.inspect(engine).get_columns("webbridge_interactions")
        }
        assert "prompt" in columns
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == SCHEMA_HEAD
    finally:
        engine.dispose()


def test_webbridge_tab_binding_repair_migrates_drifted_revision_27_database(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "webbridge-bindings-repair.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000027")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE webbridge_tab_bindings"))
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        inspector = sa.inspect(engine)
        assert "webbridge_tab_bindings" in inspector.get_table_names()
        assert {
            "pairing_id",
            "tab_id",
            "session_id",
            "origin",
            "page_instance_id",
            "expires_at",
        } <= {
            column["name"] for column in inspector.get_columns("webbridge_tab_bindings")
        }
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == SCHEMA_HEAD
    finally:
        engine.dispose()


def test_webbridge_dispatch_lease_repair_migrates_drifted_revision_28_database(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "webbridge-dispatch-lease-repair.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000028")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "ALTER TABLE webbridge_interactions "
                    "DROP COLUMN dispatch_lease_until"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        columns = {
            column["name"]
            for column in sa.inspect(engine).get_columns("webbridge_interactions")
        }
        assert "dispatch_lease_until" in columns
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == SCHEMA_HEAD
    finally:
        engine.dispose()


def test_side_chat_source_ref_migration_backfills_existing_rows(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "backfill.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000024")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    source_id = uuid4()
    side_chat_id = uuid4()
    unrelated_id = uuid4()
    now = datetime.now(timezone.utc)
    try:
        sessions = sa.Table("chat_sessions", sa.MetaData(), autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(
                sessions.insert(),
                [
                    {
                        "id": source_id.hex,
                        "title": "Main",
                        "session_type": "main",
                        "source_session_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": side_chat_id.hex,
                        "title": "Side",
                        "session_type": "side_chat",
                        "source_session_id": source_id.hex,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": unrelated_id.hex,
                        "title": "Unrelated",
                        "session_type": "main",
                        "source_session_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )

        command.upgrade(cfg, "00000025")

        migrated = sa.Table("chat_sessions", sa.MetaData(), autoload_with=engine)
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.select(migrated.c.id, migrated.c.source_session_ref).where(
                        migrated.c.id.in_([side_chat_id.hex, unrelated_id.hex])
                    )
                ).all()
            )

        assert rows[side_chat_id.hex] == source_id.hex
        assert rows[unrelated_id.hex] is None
    finally:
        engine.dispose()


def test_foreign_key_repair_applies_declared_cascade_and_set_null(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "foreign-key-repair.sqlite"
    monkeypatch.setattr(
        settings, "DATABASE_URL", SecretStr(f"sqlite+aiosqlite:///{db_path}")
    )
    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "00000052")

    valid_session = "1" * 32
    orphan_child = "2" * 32
    orphan_descendant = "3" * 32
    valid_message = "4" * 32
    orphan_message = "5" * 32
    doomed_message = "6" * 32
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO chat_sessions "
                    "(id, created_at, updated_at, mode, permission_mode, session_type, "
                    "source_session_id, project_id) VALUES "
                    "(:id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'work', 'auto', "
                    "'main', :missing, :missing)"
                ),
                {"id": valid_session, "missing": "f" * 32},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO chat_sessions "
                    "(id, parent_session_id, created_at, updated_at, mode, "
                    "permission_mode, session_type) VALUES "
                    "(:id, :parent, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "'work', 'auto', 'team_member')"
                ),
                [
                    {"id": orphan_child, "parent": "e" * 32},
                    {"id": orphan_descendant, "parent": orphan_child},
                ],
            )
            conn.execute(
                sa.text(
                    "INSERT INTO session_messages "
                    "(id, session_id, role, is_summary, exclude_from_context, created_at) "
                    "VALUES (:id, :session, 'user', 0, 0, CURRENT_TIMESTAMP)"
                ),
                [
                    {"id": valid_message, "session": valid_session},
                    {"id": orphan_message, "session": "d" * 32},
                    {"id": doomed_message, "session": orphan_child},
                ],
            )
            conn.execute(
                sa.text(
                    "INSERT INTO delegation_tasks "
                    "(id, lead_session_id, delegator, recipient, "
                    "final_handoff_message_id, created_at, updated_at) VALUES "
                    "(:id, :lead, 'lead', 'worker', :message, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                [
                    {"id": "7" * 32, "lead": "c" * 32, "message": None},
                    {
                        "id": "8" * 32,
                        "lead": valid_session,
                        "message": "b" * 32,
                    },
                    {
                        "id": "9" * 32,
                        "lead": valid_session,
                        "message": doomed_message,
                    },
                ],
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall() == []
            sessions = conn.execute(
                sa.text("SELECT id, source_session_id, project_id FROM chat_sessions")
            ).fetchall()
            assert sessions == [(valid_session, None, None)]
            messages = (
                conn.execute(sa.text("SELECT id FROM session_messages ORDER BY id"))
                .scalars()
                .all()
            )
            assert messages == [valid_message]
            delegations = conn.execute(
                sa.text(
                    "SELECT id, final_handoff_message_id FROM delegation_tasks "
                    "ORDER BY id"
                )
            ).fetchall()
            assert delegations == [("8" * 32, None), ("9" * 32, None)]
    finally:
        engine.dispose()
