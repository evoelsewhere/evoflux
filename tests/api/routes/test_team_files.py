"""Tests for the team workspace-files listing endpoint.

Covers:
  GET /api/team/{session_id}/files    → recursive listing of agent workspace

Requirements validated:
  - session_id validated as UUID (400 on malformed)
  - Missing workspace dir returns an empty list (not 404) — fresh session
  - Nested files are surfaced with POSIX-separated relative paths
  - Dotfiles/dot-dirs are excluded
  - MIME types are guessed from the extension
  - Symlinks escaping the workspace root are skipped
  - Truncation flag flips when the file cap is exceeded
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.models.chat import ChatSession

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


class TestWorkspaceMedia:
    def test_workspace_media_defaults_to_inline_for_previews(
        self, client, session_id, tmp_path, monkeypatch
    ):
        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/media/chart.png")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"].startswith("inline;")

    def test_workspace_media_can_force_attachment_download(
        self, client, session_id, tmp_path, monkeypatch
    ):
        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/media/chart.png?download=1")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"].startswith("attachment;")


class TestWorkspaceFilesListing:
    def test_invalid_session_id_returns_400(self, client):
        resp = client.get("/api/team/not-a-uuid/files")
        assert resp.status_code == 400

    def test_missing_workspace_returns_empty_list(
        self, client, session_id, tmp_path, monkeypatch
    ):
        """Fresh session: workspace dir doesn't exist yet — endpoint returns []
        rather than 404.  The UI needs a stable contract to render an empty
        state."""
        fake_root = tmp_path / "does-not-exist"

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["files"] == []
        assert body["truncated"] is False

    def test_lists_flat_files(self, client, session_id, tmp_path, monkeypatch):
        fake_root = tmp_path / "ws"
        fake_root.mkdir(parents=True)
        (fake_root / "notes.txt").write_text("hi")
        (fake_root / "readme.md").write_text("# hello")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        assert resp.status_code == 200
        body = resp.json()
        paths = sorted(f["path"] for f in body["files"])
        assert paths == ["notes.txt", "readme.md"]
        # Each entry has the expected shape.
        for entry in body["files"]:
            assert entry["name"]
            assert entry["size"] >= 0
            assert isinstance(entry["mtime"], float)
            assert entry["mime"]

    def test_lists_nested_files_with_posix_paths(
        self, client, session_id, tmp_path, monkeypatch
    ):
        fake_root = tmp_path / "ws"
        (fake_root / "output").mkdir(parents=True)
        (fake_root / "output" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (fake_root / "output" / "nested").mkdir()
        (fake_root / "output" / "nested" / "data.json").write_text("{}")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        assert resp.status_code == 200
        paths = sorted(f["path"] for f in resp.json()["files"])
        # POSIX separators — safe to concat into ``/media/{path}``.
        assert paths == ["output/chart.png", "output/nested/data.json"]

    def test_mime_guessed_from_extension(
        self, client, session_id, tmp_path, monkeypatch
    ):
        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (fake_root / "notes.txt").write_text("hi")
        (fake_root / "blob.bin").write_bytes(b"\x00\x01\x02")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        by_name = {f["name"]: f for f in resp.json()["files"]}
        assert by_name["chart.png"]["mime"].startswith("image/")
        assert by_name["notes.txt"]["mime"].startswith("text/")
        # Unknown extension falls back to the octet-stream default.
        assert by_name["blob.bin"]["mime"] == "application/octet-stream"

    def test_generated_dirs_excluded_other_dotentries_allowed(
        self, client, session_id, tmp_path, monkeypatch
    ):
        """VCS/generated cache dirs are always pruned, but other dot-prefixed
        files and folders flow through so the InputBar @-mention picker can tag
        things like ``.evoflux/`` skills, ``.github/`` workflows, or
        ``.env.example``. Filtering beyond common generated dirs is delegated to
        ``.gitignore``."""
        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / "visible.txt").write_text("ok")
        (fake_root / ".env.example").write_text("KEY=")
        (fake_root / ".git").mkdir()
        (fake_root / ".git" / "HEAD").write_text("ref: …")
        (fake_root / ".ruff_cache").mkdir()
        (fake_root / ".ruff_cache" / "cache").write_text("x")
        (fake_root / ".pytest_cache").mkdir()
        (fake_root / ".pytest_cache" / "cache").write_text("x")
        (fake_root / ".github").mkdir()
        (fake_root / ".github" / "ci.yml").write_text("jobs: {}")
        (fake_root / "sub").mkdir()
        (fake_root / "sub" / ".swp").write_text("tmp")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        paths = sorted(f["path"] for f in resp.json()["files"])
        assert paths == [
            ".env.example",
            ".github/ci.yml",
            "sub/.swp",
            "visible.txt",
        ]
        assert not any(p.startswith(".git/") for p in paths)
        assert not any(p.startswith(".ruff_cache/") for p in paths)
        assert not any(p.startswith(".pytest_cache/") for p in paths)

    def test_gitignore_negation_reincludes_dot_subdir(
        self, client, session_id, tmp_path, monkeypatch
    ):
        """``.gitignore`` with ``.evoflux/*`` + ``!.evoflux/skills/``
        should hide the ignored siblings but surface the re-included subtree
        so users can @-mention their tracked skill files."""
        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / ".gitignore").write_text(
            ".evoflux/*\n!.evoflux/skills/\n",
            encoding="utf-8",
        )
        oad = fake_root / ".evoflux"
        oad.mkdir()
        (oad / "data").mkdir()
        (oad / "data" / "runtime.db").write_text("x")
        (oad / "skills").mkdir()
        (oad / "skills" / "SKILL.md").write_text("# skill")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        paths = sorted(f["path"] for f in resp.json()["files"])
        assert ".evoflux/skills/SKILL.md" in paths
        assert ".evoflux/data/runtime.db" not in paths

    def test_symlink_escaping_root_is_skipped(
        self, client, session_id, tmp_path, monkeypatch
    ):
        """A symlink inside the workspace that points outside must not leak
        the external file's metadata into the listing."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("top-secret")

        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        (fake_root / "visible.txt").write_text("ok")
        # Create symlink inside workspace → outside.  On platforms that
        # don't allow symlinks (rare), skip cleanly.
        try:
            (fake_root / "escape.txt").symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not supported on this platform")

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        paths = [f["path"] for f in resp.json()["files"]]
        assert "escape.txt" not in paths
        assert "visible.txt" in paths

    def test_truncation_when_over_cap(self, client, session_id, tmp_path, monkeypatch):
        """Beyond ``_MAX_FILES_LISTED`` the walk stops and ``truncated`` flips
        — a defensive ceiling so a pathological workspace can't blow up the
        response."""
        from app.api.routes.team import files as team_routes

        fake_root = tmp_path / "ws"
        fake_root.mkdir()
        # Generate one more file than the cap so truncation kicks in.
        cap = team_routes._MAX_FILES_LISTED
        for i in range(cap + 5):
            (fake_root / f"f{i:04d}.txt").write_text("x")

        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: fake_root)

        resp = client.get(f"/api/team/{session_id}/files")
        body = resp.json()
        assert body["truncated"] is True
        assert len(body["files"]) == cap

    # NB: The previous mtime-based "revert boundary" filter is gone. After
    # the move to the Git snapshot service (see app/services/snapshot_service.py),
    # the workspace filesystem is authoritative — restoring a snapshot
    # physically removes files added after that point, so the listing
    # and media endpoints simply report what's on disk. The snapshot
    # round-trip is covered by tests/services/test_snapshot_service.py.


class TestCodingLspDiagnostics:
    def test_diagnoses_unsaved_buffer(self, client, tmp_path, monkeypatch):
        source = tmp_path / "main.py"
        source.write_text("value = 1\n")
        lsp_client = SimpleNamespace(
            diagnostics=AsyncMock(
                return_value=[
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 5},
                        },
                        "severity": 1,
                        "message": "Type mismatch",
                    }
                ]
            )
        )

        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(
            team_routes, "get_language_server", AsyncMock(return_value=lsp_client)
        )

        response = client.post(
            "/api/team/workspace/lsp/diagnostics",
            params={"workspace": str(tmp_path)},
            json={"path": "main.py", "content": "value: int = 'bad'\n"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["language"] == "python"
        assert body["diagnostics"][0]["message"] == "Type mismatch"
        lsp_client.diagnostics.assert_awaited_once_with(
            source.resolve(), "value: int = 'bad'\n"
        )
        from app.services.problems_service import list_problems

        problems = list_problems(tmp_path)
        assert len(problems) == 1
        assert problems[0].source == "lsp"
        assert problems[0].path == "main.py"

    def test_reports_unavailable_language_server(self, client, tmp_path, monkeypatch):
        source = tmp_path / "main.py"
        source.write_text("value = 1\n")

        from app.api.routes.team import files as team_routes
        from app.agent.lsp_manager import LanguageServerUnavailable

        async def unavailable(*_args, **_kwargs):
            raise LanguageServerUnavailable("Install pyright-langserver")

        monkeypatch.setattr(team_routes, "get_language_server", unavailable)
        response = client.post(
            "/api/team/workspace/lsp/diagnostics",
            params={"workspace": str(tmp_path)},
            json={"path": "main.py", "content": "value = 1\n"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "unavailable"

    def test_unsupported_file_type_is_not_an_error(self, client, tmp_path):
        source = tmp_path / "notes.txt"
        source.write_text("hello\n")
        response = client.post(
            "/api/team/workspace/lsp/diagnostics",
            params={"workspace": str(tmp_path)},
            json={"path": "notes.txt", "content": "hello\n"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "unsupported"


class TestCodingLspSemantic:
    def test_returns_unapplied_rename_edit(self, client, tmp_path, monkeypatch):
        source = tmp_path / "main.py"
        source.write_text("value = 1\n")
        workspace_edit = {
            "changes": {
                source.as_uri(): [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 5},
                        },
                        "newText": "renamed",
                    }
                ]
            }
        }
        lsp_client = SimpleNamespace(
            capabilities={"renameProvider": True},
            rename=AsyncMock(return_value=workspace_edit),
        )
        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(
            team_routes, "get_language_server", AsyncMock(return_value=lsp_client)
        )

        response = client.post(
            "/api/team/workspace/lsp/semantic",
            params={"workspace": str(tmp_path)},
            json={
                "action": "rename",
                "path": "main.py",
                "content": "value = 1\n",
                "line": 1,
                "column": 2,
                "new_name": "renamed",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["result"] == workspace_edit
        assert body["capabilities"] == {"renameProvider": True}
        lsp_client.rename.assert_awaited_once_with(
            source.resolve(), 1, 2, "renamed", "value = 1\n"
        )

    def test_code_actions_receive_current_diagnostics(
        self, client, tmp_path, monkeypatch
    ):
        source = tmp_path / "main.py"
        source.write_text("value = 1\n")
        lsp_client = SimpleNamespace(
            capabilities={},
            diagnostics=AsyncMock(return_value=[{"message": "Type mismatch"}]),
            code_actions=AsyncMock(
                return_value=[{"title": "Fix mismatch", "kind": "quickfix"}]
            ),
        )
        from app.api.routes.team import files as team_routes

        monkeypatch.setattr(
            team_routes, "get_language_server", AsyncMock(return_value=lsp_client)
        )

        response = client.post(
            "/api/team/workspace/lsp/semantic",
            params={"workspace": str(tmp_path)},
            json={
                "action": "code_actions",
                "path": "main.py",
                "content": "value = 1\n",
                "line": 1,
                "column": 1,
                "end_line": 1,
                "end_column": 6,
            },
        )

        assert response.status_code == 200
        assert response.json()["result"][0]["kind"] == "quickfix"
        lsp_client.code_actions.assert_awaited_once_with(
            source.resolve(),
            start_line=1,
            start_column=1,
            end_line=1,
            end_column=6,
            diagnostics=[{"message": "Type mismatch"}],
            content="value = 1\n",
        )

    def test_position_action_requires_coordinates(self, client, tmp_path):
        source = tmp_path / "main.py"
        source.write_text("value = 1\n")

        response = client.post(
            "/api/team/workspace/lsp/semantic",
            params={"workspace": str(tmp_path)},
            json={"action": "hover", "path": "main.py"},
        )

        assert response.status_code == 422

    def test_semantic_path_cannot_escape_repository(self, client, tmp_path):
        outside = tmp_path.parent / "outside.py"
        outside.write_text("value = 1\n")

        response = client.post(
            "/api/team/workspace/lsp/semantic",
            params={"workspace": str(tmp_path)},
            json={"action": "document_symbols", "path": "../outside.py"},
        )

        assert response.status_code == 400


class TestSessionWorkspaceSelection:
    def test_get_workspace_root_does_not_scan_files(
        self, client, session_id, tmp_path, monkeypatch
    ):
        from app.api.routes.team import files as team_routes

        workspace = tmp_path / "not-created-yet"
        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: workspace)

        def fail_if_scanned(*args, **kwargs):
            raise AssertionError("workspace root lookup must not scan files")

        monkeypatch.setattr(team_routes, "_list_workspace_files", fail_if_scanned)

        resp = client.get(f"/api/team/{session_id}/workspace")

        assert resp.status_code == 200
        assert resp.json() == {
            "session_id": session_id,
            "workspace_root": str(workspace.resolve()),
        }

    def test_get_workspace_root_rejects_invalid_session_id(self, client):
        resp = client.get("/api/team/not-a-uuid/workspace")
        assert resp.status_code == 400

    def test_update_workspace_syncs_cached_work_team(
        self, client, session_id, tmp_path, monkeypatch
    ):
        async def save_session() -> None:
            from app.core.db import async_session_factory

            async with async_session_factory() as db:
                db.add(
                    ChatSession(
                        id=uuid.UUID(session_id),
                        agent_name="lead",
                        mode="work",
                    )
                )
                await db.commit()

        asyncio.run(save_session())
        workspace = tmp_path / "selected-workspace"
        live_team = SimpleNamespace(workspace=None)

        from app.api.routes.team import files as team_routes
        from app.core import db as db_module

        monkeypatch.setattr(
            team_routes, "async_session_factory", db_module.async_session_factory
        )
        monkeypatch.setattr(
            team_routes.team_manager,
            "current_team_for_session",
            lambda sid: live_team if sid == session_id else None,
        )

        resp = client.put(
            f"/api/team/{session_id}/workspace",
            json={"path": str(workspace)},
        )

        expected = str(workspace.resolve())
        assert resp.status_code == 200
        assert resp.json()["workspace_root"] == expected
        assert live_team.workspace == expected

    def test_reset_workspace_clears_cached_work_team(
        self, client, session_id, tmp_path, monkeypatch
    ):
        selected = tmp_path / "selected-workspace"
        selected.mkdir()

        async def save_session() -> None:
            from app.core.db import async_session_factory

            async with async_session_factory() as db:
                db.add(
                    ChatSession(
                        id=uuid.UUID(session_id),
                        agent_name="lead",
                        mode="work",
                        workspace=str(selected),
                    )
                )
                await db.commit()

        asyncio.run(save_session())
        live_team = SimpleNamespace(workspace=str(selected))

        from app.api.routes.team import files as team_routes
        from app.core import db as db_module

        default_workspace = tmp_path / "default-session-workspace"
        monkeypatch.setattr(team_routes, "workspace_dir", lambda sid: default_workspace)
        monkeypatch.setattr(
            team_routes, "async_session_factory", db_module.async_session_factory
        )
        monkeypatch.setattr(
            team_routes.team_manager,
            "current_team_for_session",
            lambda sid: live_team if sid == session_id else None,
        )

        resp = client.put(
            f"/api/team/{session_id}/workspace",
            json={"path": None},
        )

        assert resp.status_code == 200
        assert resp.json()["workspace_root"] == str(default_workspace)
        assert live_team.workspace is None
