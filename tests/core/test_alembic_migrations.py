"""Alembic smoke test — the full migration chain upgrades a fresh SQLite DB.

Runs ``alembic upgrade head`` against a temp database using the real
``app/alembic.ini`` and asserts the latest schema state lands (currently:
WebBridge pairing, interaction, and tab-binding state from revision 00000026).
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
        } <= set(inspector.get_table_names())
        interaction_columns = {
            column["name"] for column in inspector.get_columns("webbridge_interactions")
        }
        assert {
            "request_hash",
            "prompt",
            "dispatch_lease_until",
        } <= interaction_columns
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == "00000026"
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
