"""Fixtures for the ``terminal-processes`` contract (temp workspaces only)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("hello\n", encoding="utf-8", newline="")
    return root


@pytest.fixture
def session_id() -> str:
    """A UUID with no session row: the terminal routes do not need one."""
    return str(uuid.uuid4())


@pytest.fixture
def workspace_root_of_backend(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_WORKSPACE_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "workspace"
