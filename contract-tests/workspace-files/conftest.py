"""Fixtures for the ``workspace-files`` contract (temp workspaces only)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ws_helpers import Scrub


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_WORKSPACE_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "workspace"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A coding workspace passed as ``?workspace=``: two files and a folder."""
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("hello\n", encoding="utf-8", newline="")
    (root / "sub" / "b.py").write_text("x = 1\n", encoding="utf-8", newline="")
    return root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A folder beside the workspace holding a file no route may touch."""
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.txt").write_text("SECRET", encoding="utf-8", newline="")
    return folder


@pytest.fixture
def session_id(client: httpx.Client) -> str:
    """A Work session (no workspace set), so its folder is ``<workspace dir>/<id>``."""
    response = client.post("/api/team/sessions/resolve", json={"mode": "work", "create": True})
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def session_dir(workspace_root: Path, session_id: str) -> Path:
    return workspace_root / session_id
