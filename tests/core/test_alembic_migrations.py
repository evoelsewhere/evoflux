"""Alembic smoke test — the full migration chain upgrades a fresh SQLite DB.

Runs ``alembic upgrade head`` against a temp database using the real
``app/alembic.ini`` and asserts the latest schema state lands (currently:
``chat_sessions.session_type``/``source_session_id`` from revision 00000024).
Complements ``tests/core/test_db_extra.py``, which only covers
``run_migrations`` error paths with mocks.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from pydantic import SecretStr

import app
from app.core.config import settings


def test_alembic_upgrade_head_adds_side_chat_fields(tmp_path, monkeypatch):
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
        fk_columns = {
            col
            for fk in sa.inspect(engine).get_foreign_keys("chat_sessions")
            for col in fk["constrained_columns"]
        }
        assert "source_session_id" in fk_columns
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == "00000024"
    finally:
        engine.dispose()
