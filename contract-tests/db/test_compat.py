"""Compatibility of the concurrent SQLite build with v3's stock SQLite."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from backends import start_backend
from fixtures import TAGS, upgrade_fixture, upgrade_manifest

ROOT = Path(__file__).resolve().parents[2]
assert "v3.0.0" in TAGS, "the v3.0.0 upgrade fixture is required"
TARGET_DIR = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "server" / "target"))
if not TARGET_DIR.is_absolute():
    TARGET_DIR = ROOT / "server" / TARGET_DIR
EXAMPLE = (
    TARGET_DIR
    / "debug"
    / "examples"
    / ("db_stress.exe" if os.name == "nt" else "db_stress")
)


@pytest.fixture(params=["fresh", *TAGS])
def database(request, tmp_path):
    fixture = None if request.param == "fresh" else upgrade_fixture(request.param)
    try:
        backend = start_backend("python", tmp_path / "initial", fixture)
        backend.stop()
    finally:
        if fixture:
            fixture.unlink(missing_ok=True)
            fixture.parent.rmdir()
    db = tmp_path / "initial" / "data" / "evoflux.db"
    checkpoint(db)
    return db, request.param


def run_rust(db: Path, seconds: int = 60) -> dict:
    assert EXAMPLE.is_file(), f"missing stress binary: {EXAMPLE}"
    result = subprocess.run(
        [
            str(EXAMPLE),
            "--db",
            str(db),
            "--seconds",
            str(seconds),
            "--writers",
            "4",
            "--report",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=seconds + 60,
        check=True,
    )
    return json.loads(result.stdout)


def checkpoint(db: Path) -> None:
    """Checkpoint WAL before the backend harness copies the database file.

    The backend is force-killed first, and on Windows the first open can fail
    with ``disk I/O error`` while the dead process's WAL index state is
    released; a few retries cover that, a persistent failure still raises.
    """
    for attempt in range(5):
        try:
            with closing(sqlite3.connect(db, timeout=30)) as conn:
                busy, _frames, _checkpointed = conn.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
            break
        except sqlite3.OperationalError:
            if attempt == 4:
                raise
            time.sleep(1)
    assert busy == 0


def verify_stock(db: Path) -> None:
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    latest = os.environ.get("EVOFLUX_SQLITE_CLI")
    if latest:
        checked = subprocess.run(
            [latest, str(db), "PRAGMA integrity_check; PRAGMA foreign_key_check;"],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        assert checked.stdout.strip() == "ok", checked.stdout + checked.stderr


def test_after_rust_stress_stock_sqlite_integrity(database):
    db, _ = database
    tables = ("chat_sessions", "session_folders", "memory_facts")
    with closing(sqlite3.connect(db)) as conn:
        before = {
            table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    report = run_rust(db)
    assert report["acknowledged"] > 0
    assert report["failed"] == 0
    assert report["acknowledged"] == sum(report["counts"].values())
    with closing(sqlite3.connect(db)) as conn:
        for table in tables:
            assert conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == (
                before[table] + report["counts"][table]
            )
    verify_stock(db)


def test_after_rust_stress_v3_opens_and_serves(database, tmp_path):
    db, tag = database
    manifest = upgrade_manifest(tag) if tag != "fresh" else None
    with closing(sqlite3.connect(db)) as conn:
        before_stress = {
            table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in ("chat_sessions", "session_folders", "memory_facts")
        }
    if manifest is not None:
        with closing(sqlite3.connect(db)) as conn:
            manifest["alembic_revision"] = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            manifest["row_counts"] = {
                table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in manifest["row_counts"]
            }
    report = run_rust(db)
    assert report["acknowledged"] > 0 and report["failed"] == 0
    verify_stock(db)
    checkpoint(db)
    if manifest is not None:
        for table, count in report["counts"].items():
            manifest["row_counts"][table] += count
    backend = start_backend("python", tmp_path / "reopen", db)
    try:
        with closing(
            sqlite3.connect(tmp_path / "reopen" / "data" / "evoflux.db")
        ) as conn:
            for table, count in report["counts"].items():
                assert conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[
                    0
                ] == (before_stress[table] + count)
        with httpx.Client(
            base_url=backend.base_url,
            headers={"Authorization": f"Bearer {backend.token}"},
            timeout=30,
        ) as client:
            assert client.get("/api/health/live").status_code == 200
            response = client.get("/api/team/sessions")
            assert response.status_code == 200
            if tag != "fresh":
                for session_id in upgrade_manifest(tag)["created_ids"]["sessions"]:
                    assert session_id in response.text
    finally:
        backend.stop()
    verify_stock(db)
    run_contracts_on_database(db, tag, manifest, tmp_path)


def run_contracts_on_database(
    db: Path, tag: str, manifest: dict | None, tmp_path: Path
) -> None:
    """Run unmodified health/upgrade contracts using the stressed file as input."""
    suite = tmp_path / "stressed-contracts"
    suite.mkdir()
    for area in ("health", "upgrade"):
        shutil.copytree(ROOT / "contract-tests" / area, suite / area)
    conftest = (ROOT / "contract-tests" / "conftest.py").read_text(encoding="utf-8")
    conftest += """
@pytest.fixture
def db_fixture():
    return Path(os.environ["DB_COMPAT_SOURCE"])

def pytest_collection_modifyitems(items):
    import shutil
    import tempfile
    for item in items:
        module = item.module
        if hasattr(module, "upgrade_manifest"):
            def stressed_copy(tag):
                dest = Path(tempfile.mkdtemp(prefix="evoflux-db-contract-")) / "evoflux.db"
                shutil.copyfile(os.environ["DB_COMPAT_SOURCE"], dest)
                return dest
            module.upgrade_fixture = stressed_copy
            module.upgrade_manifest = lambda tag: json.loads(os.environ["DB_COMPAT_MANIFEST"])
"""
    (suite / "conftest.py").write_text(conftest, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        DB_COMPAT_SOURCE=str(db),
        DB_COMPAT_MANIFEST=json.dumps(manifest),
        PYTHONPATH=str(ROOT / "contract-tests"),
        TARGET="python",
    )
    areas = [str(suite / "health")]
    if tag != "fresh":
        areas.append(str(suite / "upgrade"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *areas, "-q", "--no-cov"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_two_process_stress(database, tmp_path):
    from two_process_stress import run_two_process_stress

    db, _ = database
    result = run_two_process_stress(db, tmp_path, EXAMPLE, seconds=120)
    print(json.dumps({key: value for key, value in result.items() if key != "db"}))
    assert result["rust_acknowledged"] > 0
    assert result["python_sessions"] > 0 and result["python_messages"] > 0
    assert result["actual_counts"] == result["expected_counts"]
    verify_stock(result["db"])


def test_two_process_stress_fifo_fallback(database, tmp_path):
    from two_process_stress import run_two_process_stress

    db, _ = database
    result = run_two_process_stress(db, tmp_path, EXAMPLE, seconds=120, mode="fifo")
    print(json.dumps({key: value for key, value in result.items() if key != "db"}))
    assert result["rust_acknowledged"] > 0
    assert result["python_sessions"] > 0 and result["python_messages"] > 0
    assert result["actual_counts"] == result["expected_counts"]
    verify_stock(result["db"])
