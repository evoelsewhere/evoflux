"""Alembic smoke test — the full migration chain upgrades a fresh SQLite DB.

Runs ``alembic upgrade head`` against a temp database using the real
``app/alembic.ini`` and asserts the latest schema state lands (currently:
WebBridge pairing, interaction, tab-binding, Teach Mode state, delegation
tasks, Git server connections, the Work mode rename, retired session-section
cleanup, durable goals, durable workflow gates, the AIM table drop, scheduler
routing, and application-database graph removal through revision 00000046).
Artifact Fabric jobs, revisions, and reviews land in revision 00000047;
revision 00000048 repairs project-owned Coding sessions hidden by the sidebar;
revision 00000049 removes the retired parallel Memory processing table.
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
            "artifact_jobs",
            "artifact_revisions",
            "artifact_reviews",
        } <= set(inspector.get_table_names())
        assert "session_chapters" not in inspector.get_table_names()
        assert "memory_processed_sources" not in inspector.get_table_names()
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
        assert {
            "artifact_format",
            "lane",
            "action",
            "status",
            "latest_revision_id",
        } <= {column["name"] for column in inspector.get_columns("artifact_jobs")}
        assert {
            "content_sha256",
            "blob_key",
            "qa",
            "manifest_data",
            "provenance",
            "driver_version",
            "protocol_version",
        } <= {column["name"] for column in inspector.get_columns("artifact_revisions")}
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
