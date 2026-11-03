"""Isolated session workspace for document contract tests."""

import sqlite3
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def session_workspace(backend, tmp_path: Path):
    session = uuid.UUID(int=1)
    root = tmp_path / "session-files"
    root.mkdir()
    with sqlite3.connect(tmp_path / "data" / "evoflux.db", timeout=30) as db:
        db.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at, workspace) "
            "VALUES (?, ?, ?, ?, ?)",
            (session.hex, "Contract", "2026-01-01", "2026-01-01", str(root)),
        )
    return str(session), root
