"""Perf-area fixtures: every test starts from the same seeded database."""

from __future__ import annotations

from pathlib import Path

import pytest

from backends import start_backend
from perf_seed import seed_database


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schema from a real v3.1.1 start (Alembic stays the only DDL author), then rows."""
    base = tmp_path_factory.mktemp("perf-seed")
    start_backend("python", base).stop()
    db = base / "data" / "evoflux.db"
    seed_database(db)
    return db


@pytest.fixture
def db_fixture(seeded_db: Path) -> Path:
    return seeded_db
