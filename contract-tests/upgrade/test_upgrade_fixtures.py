"""Every v3.x release's database must open and serve under the current Python."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import sqlite3
from contextlib import closing

import httpx
import pytest

from fixtures import TAGS, upgrade_fixture, upgrade_manifest


@pytest.fixture(params=TAGS)
def tag(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def db_fixture(tag: str) -> Iterator[Path]:
    path = upgrade_fixture(tag)
    yield path
    path.unlink(missing_ok=True)
    path.parent.rmdir()


def test_each_fixture_opens_under_v3_1_1(client: httpx.Client, tag: str) -> None:
    manifest = upgrade_manifest(tag)
    response = client.get("/api/team/sessions")
    assert response.status_code == 200, response.text
    listed = response.text
    expected = manifest["created_ids"]["sessions"]
    assert len(expected) == 2
    for session_id in expected:
        assert session_id in listed, f"{tag}: session {session_id} not listed"


def test_manifest_matches_database(tag: str) -> None:
    manifest = upgrade_manifest(tag)
    db = upgrade_fixture(tag)
    try:
        with closing(sqlite3.connect(db)) as conn:
            revision = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            counts = {
                table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in manifest["row_counts"]
            }
    finally:
        db.unlink(missing_ok=True)
        db.parent.rmdir()
    assert revision == manifest["alembic_revision"]
    assert counts == manifest["row_counts"]


def test_oldest_fixture_is_present() -> None:
    # TAGS comes from the directory listing; without this the parametrized
    # tests would collect nothing and the gate would pass vacuously.
    assert "v3.0.0" in TAGS
