"""Tests for the explorer's file-mutation endpoints.

Covers the routes behind the file tree's right-click menu:

  POST   /api/team/{sid}/files/create          → new file / folder
  POST   /api/team/{sid}/files/copy            → duplicate
  POST   /api/team/{sid}/files/move            → rename, folders included
  DELETE /api/team/{sid}/files/{path}          → delete, folders need recursive
  POST   /api/team/workspace/files/create      → same four, for a coding
  POST   /api/team/workspace/files/copy          workspace addressed by its
  POST   /api/team/workspace/files/move          absolute root
  DELETE /api/team/workspace/files/entry

Requirements validated:
  - Traversal and absolute paths are rejected before any filesystem work
  - Existing destinations are refused rather than clobbered
  - Folders are only deleted when the caller asks for it explicitly
  - A folder cannot be copied or moved into itself
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("setup_db")


@pytest.fixture
def app_no_team():
    from app.api.app import create_app
    from app.services.team_manager import set_team

    app = create_app()
    set_team(None)
    yield app
    set_team(None)


@pytest.fixture
def client(app_no_team):
    return TestClient(app_no_team)


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid7())


@pytest.fixture
def workspace(tmp_path, monkeypatch, session_id):
    """A session workspace on disk, wired into the route module."""
    from app.api.routes.team import files as team_routes

    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: root)
    return root


class TestSessionWorkspaceMutations:
    def test_creates_file_and_folder(self, client, session_id, workspace):
        resp = client.post(
            f"/api/team/{session_id}/files/create",
            params={"path": "notes/today.md", "kind": "file"},
        )
        assert resp.status_code == 200
        assert (workspace / "notes" / "today.md").is_file()

        resp = client.post(
            f"/api/team/{session_id}/files/create",
            params={"path": "notes/archive", "kind": "directory"},
        )
        assert resp.status_code == 200
        assert (workspace / "notes" / "archive").is_dir()

    def test_create_refuses_existing_entry(self, client, session_id, workspace):
        (workspace / "notes.md").write_text("hi")
        resp = client.post(
            f"/api/team/{session_id}/files/create", params={"path": "notes.md"}
        )
        assert resp.status_code == 409
        assert (workspace / "notes.md").read_text() == "hi"

    def test_create_rejects_traversal(self, client, session_id, workspace):
        resp = client.post(
            f"/api/team/{session_id}/files/create", params={"path": "../escape.md"}
        )
        assert resp.status_code == 400
        assert not (workspace.parent / "escape.md").exists()

    def test_duplicates_file_and_folder(self, client, session_id, workspace):
        (workspace / "report.md").write_text("body")
        (workspace / "assets").mkdir()
        (workspace / "assets" / "logo.svg").write_text("<svg/>")

        resp = client.post(
            f"/api/team/{session_id}/files/copy",
            json={"from_path": "report.md", "to_path": "report copy.md"},
        )
        assert resp.status_code == 200
        assert (workspace / "report copy.md").read_text() == "body"

        resp = client.post(
            f"/api/team/{session_id}/files/copy",
            json={"from_path": "assets", "to_path": "assets copy"},
        )
        assert resp.status_code == 200
        assert (workspace / "assets copy" / "logo.svg").read_text() == "<svg/>"

    def test_copy_refuses_nesting_a_folder_in_itself(
        self, client, session_id, workspace
    ):
        (workspace / "assets").mkdir()
        resp = client.post(
            f"/api/team/{session_id}/files/copy",
            json={"from_path": "assets", "to_path": "assets/inner"},
        )
        assert resp.status_code == 400

    def test_renames_a_folder(self, client, session_id, workspace):
        (workspace / "old").mkdir()
        (workspace / "old" / "a.txt").write_text("a")

        resp = client.post(
            f"/api/team/{session_id}/files/move",
            json={"from_path": "old", "to_path": "new"},
        )
        assert resp.status_code == 200
        assert (workspace / "new" / "a.txt").read_text() == "a"
        assert not (workspace / "old").exists()

    def test_move_refuses_existing_destination(self, client, session_id, workspace):
        (workspace / "a.txt").write_text("a")
        (workspace / "b.txt").write_text("b")

        resp = client.post(
            f"/api/team/{session_id}/files/move",
            json={"from_path": "a.txt", "to_path": "b.txt"},
        )
        assert resp.status_code == 409
        assert (workspace / "b.txt").read_text() == "b"

    def test_folder_delete_requires_recursive(self, client, session_id, workspace):
        (workspace / "logs").mkdir()
        (workspace / "logs" / "run.log").write_text("...")

        resp = client.delete(f"/api/team/{session_id}/files/logs")
        assert resp.status_code == 400
        assert (workspace / "logs").is_dir()

        resp = client.delete(
            f"/api/team/{session_id}/files/logs", params={"recursive": "true"}
        )
        assert resp.status_code == 200
        assert not (workspace / "logs").exists()

    def test_deletes_a_file(self, client, session_id, workspace):
        (workspace / "notes.md").write_text("hi")
        resp = client.delete(f"/api/team/{session_id}/files/notes.md")
        assert resp.status_code == 200
        assert not (workspace / "notes.md").exists()


@pytest.fixture
def coding_workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


class TestCodingWorkspaceMutations:
    def test_creates_file_and_folder(self, client, coding_workspace):
        resp = client.post(
            "/api/team/workspace/files/create",
            params={
                "workspace": str(coding_workspace),
                "path": "src/main.py",
                "kind": "file",
            },
        )
        assert resp.status_code == 200
        assert (coding_workspace / "src" / "main.py").is_file()

        resp = client.post(
            "/api/team/workspace/files/create",
            params={
                "workspace": str(coding_workspace),
                "path": "src/utils",
                "kind": "directory",
            },
        )
        assert resp.status_code == 200
        assert (coding_workspace / "src" / "utils").is_dir()

    def test_create_rejects_unknown_kind(self, client, coding_workspace):
        resp = client.post(
            "/api/team/workspace/files/create",
            params={
                "workspace": str(coding_workspace),
                "path": "x",
                "kind": "symlink",
            },
        )
        assert resp.status_code == 422

    def test_create_rejects_traversal(self, client, coding_workspace):
        resp = client.post(
            "/api/team/workspace/files/create",
            params={"workspace": str(coding_workspace), "path": "../escape.py"},
        )
        assert resp.status_code == 400
        assert not (coding_workspace.parent / "escape.py").exists()

    def test_renames_then_duplicates(self, client, coding_workspace):
        (coding_workspace / "main.py").write_text("print(1)")

        resp = client.post(
            "/api/team/workspace/files/move",
            params={"workspace": str(coding_workspace)},
            json={"from_path": "main.py", "to_path": "app.py"},
        )
        assert resp.status_code == 200
        assert (coding_workspace / "app.py").read_text() == "print(1)"

        resp = client.post(
            "/api/team/workspace/files/copy",
            params={"workspace": str(coding_workspace)},
            json={"from_path": "app.py", "to_path": "app copy.py"},
        )
        assert resp.status_code == 200
        assert (coding_workspace / "app copy.py").read_text() == "print(1)"

    def test_move_reports_missing_source(self, client, coding_workspace):
        resp = client.post(
            "/api/team/workspace/files/move",
            params={"workspace": str(coding_workspace)},
            json={"from_path": "nope.py", "to_path": "yes.py"},
        )
        assert resp.status_code == 404

    def test_folder_delete_requires_recursive(self, client, coding_workspace):
        (coding_workspace / "build").mkdir()
        (coding_workspace / "build" / "out.js").write_text("//")

        resp = client.delete(
            "/api/team/workspace/files/entry",
            params={"workspace": str(coding_workspace), "path": "build"},
        )
        assert resp.status_code == 400
        assert (coding_workspace / "build").is_dir()

        resp = client.delete(
            "/api/team/workspace/files/entry",
            params={
                "workspace": str(coding_workspace),
                "path": "build",
                "recursive": "true",
            },
        )
        assert resp.status_code == 200
        assert not (coding_workspace / "build").exists()

    def test_delete_reports_missing_file(self, client, coding_workspace):
        resp = client.delete(
            "/api/team/workspace/files/entry",
            params={"workspace": str(coding_workspace), "path": "ghost.py"},
        )
        assert resp.status_code == 404

    def test_rejects_unknown_workspace(self, client, tmp_path):
        resp = client.post(
            "/api/team/workspace/files/create",
            params={"workspace": str(tmp_path / "missing"), "path": "a.py"},
        )
        assert resp.status_code == 422
