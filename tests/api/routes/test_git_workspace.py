from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_without_team():
    from app.api.app import create_app
    from app.services.team_manager import set_team

    app = create_app()
    set_team(None)
    yield app
    set_team(None)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_init_and_repository_overview(app_without_team, tmp_path: Path):
    workspace = tmp_path / "new-repository"
    workspace.mkdir()
    client = TestClient(app_without_team)

    initialized = client.post(
        "/api/team/workspace/git/repository/init",
        json={"workspace": str(workspace), "default_branch": "trunk"},
    )
    overview = client.get(
        "/api/team/workspace/git/repository",
        params={"workspace": str(workspace)},
    )

    assert initialized.status_code == 200
    assert initialized.json()["is_git_repo"] is True
    assert overview.status_code == 200
    assert overview.json()["branch"] == "trunk"
    assert overview.json()["head_sha"] is None


def test_clone_repository_into_selected_parent(app_without_team, tmp_path: Path):
    source = _repo(tmp_path)
    bare = tmp_path / "source.git"
    _git(source, "clone", "--bare", str(source), str(bare))
    parent = tmp_path / "clones"
    parent.mkdir()

    response = TestClient(app_without_team).post(
        "/api/team/workspace/git/repository/clone",
        json={
            "parent": str(parent),
            "url": str(bare),
            "directory": "working-copy",
            "branch": "main",
        },
    )

    destination = parent / "working-copy"
    assert response.status_code == 200
    assert response.json() == {
        "workspace": str(destination),
        "name": "working-copy",
        "remote_url": str(bare),
    }
    assert (destination / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert _git(destination, "remote", "get-url", "origin") == str(bare)


def test_clone_rejects_existing_destination(app_without_team, tmp_path: Path):
    source = _repo(tmp_path)
    parent = tmp_path / "clones"
    destination = parent / "existing"
    destination.mkdir(parents=True)

    response = TestClient(app_without_team).post(
        "/api/team/workspace/git/repository/clone",
        json={
            "parent": str(parent),
            "url": str(source),
            "directory": destination.name,
        },
    )

    assert response.status_code == 409


def test_remote_crud_and_tag_crud(app_without_team, tmp_path: Path):
    repo = _repo(tmp_path)
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare")
    client = TestClient(app_without_team)
    base = "/api/team/workspace/git"

    created_remote = client.post(
        f"{base}/remotes",
        json={"workspace": str(repo), "name": "origin", "url": str(bare)},
    )
    remotes = client.get(f"{base}/remotes", params={"workspace": str(repo)})
    created_tag = client.post(
        f"{base}/tags",
        json={
            "workspace": str(repo),
            "name": "v1.0.0",
            "target": "HEAD",
            "message": "First release",
        },
    )
    tags = client.get(f"{base}/tags", params={"workspace": str(repo)})

    assert created_remote.status_code == 200
    assert remotes.json() == [
        {
            "name": "origin",
            "fetch_url": str(bare),
            "push_url": str(bare),
        }
    ]
    assert created_tag.status_code == 200
    assert tags.status_code == 200
    assert tags.json()[0]["name"] == "v1.0.0"
    assert tags.json()[0]["subject"] == "First release"

    assert (
        client.request(
            "DELETE",
            f"{base}/tags",
            json={"workspace": str(repo), "name": "v1.0.0"},
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE",
            f"{base}/remotes",
            json={"workspace": str(repo), "name": "origin"},
        ).status_code
        == 200
    )
    assert client.get(f"{base}/tags", params={"workspace": str(repo)}).json() == []
    assert client.get(f"{base}/remotes", params={"workspace": str(repo)}).json() == []


def test_delete_branch_and_stash_accept_client_json_contract(
    app_without_team,
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    client = TestClient(app_without_team)
    base = "/api/team/workspace/git"
    _git(repo, "branch", "temporary")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "temporary stash")

    deleted_branch = client.request(
        "DELETE",
        f"{base}/branches",
        json={"workspace": str(repo), "name": "temporary", "force": False},
    )
    deleted_stash = client.request(
        "DELETE",
        f"{base}/stash",
        json={"workspace": str(repo), "index": 0},
    )

    assert deleted_branch.status_code == 200
    assert deleted_stash.status_code == 200
    assert "temporary" not in _git(repo, "branch", "--list")
    assert _git(repo, "stash", "list") == ""


def test_discard_restores_tracked_and_removes_nested_untracked_files(
    app_without_team,
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    tracked = repo / "README.md"
    tracked.write_text("changed\n", encoding="utf-8")
    generated = repo / "generated" / "nested.txt"
    generated.parent.mkdir()
    generated.write_text("temporary\n", encoding="utf-8")

    changes = TestClient(app_without_team).get(
        "/api/team/workspace/git/changes",
        params={"workspace": str(repo)},
    )

    response = TestClient(app_without_team).post(
        "/api/team/workspace/git/discard",
        json={
            "workspace": str(repo),
            "paths": ["README.md", "generated/nested.txt"],
        },
    )

    assert any(
        item["path"] == "generated/nested.txt" and item["status"] == "untracked"
        for item in changes.json()["files"]
    )
    assert response.status_code == 200
    assert tracked.read_text(encoding="utf-8") == "hello\n"
    assert not generated.exists()


def test_discard_untracked_file_does_not_fail_restore(
    app_without_team,
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    untracked = repo / "scratch.txt"
    untracked.write_text("temporary\n", encoding="utf-8")

    response = TestClient(app_without_team).post(
        "/api/team/workspace/git/discard",
        json={"workspace": str(repo), "paths": ["scratch.txt"]},
    )

    assert response.status_code == 200
    assert not untracked.exists()


def test_diff_view_handles_c_quoted_untracked_path(
    app_without_team,
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    path = "café notes.txt"
    (repo / path).write_text("first\nsecond\n", encoding="utf-8")

    response = TestClient(app_without_team).get(
        "/api/team/workspace/git/diff-view",
        params={"workspace": str(repo), "path": path},
    )

    assert response.status_code == 200
    assert f"+++ b/{path}" in response.json()["diff"]
    assert "+first" in response.json()["diff"]


def test_repository_identity_and_revert_commit(app_without_team, tmp_path: Path):
    repo = _repo(tmp_path)
    client = TestClient(app_without_team)
    base = "/api/team/workspace/git"
    (repo / "README.md").write_text("release\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "release change")
    sha = _git(repo, "rev-parse", "HEAD")

    identity = client.post(
        f"{base}/repository/identity",
        json={
            "workspace": str(repo),
            "name": "Repository User",
            "email": "repository@example.com",
        },
    )
    reverted = client.post(
        f"{base}/revert",
        json={"workspace": str(repo), "sha": sha},
    )

    assert identity.status_code == 200
    assert identity.json()["user_name"] == "Repository User"
    assert identity.json()["user_email"] == "repository@example.com"
    assert reverted.status_code == 200
    assert reverted.json()["success"] is True
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_log_paginates_and_returns_graph_metadata(app_without_team, tmp_path: Path):
    repo = _repo(tmp_path)
    client = TestClient(app_without_team)
    base = "/api/team/workspace/git"
    for index in range(3):
        (repo / "README.md").write_text(f"change {index}\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", f"change {index}")
    _git(repo, "branch", "release", "HEAD~1")

    first = client.get(
        f"{base}/log",
        params={
            "workspace": str(repo),
            "all_branches": True,
            "skip": 0,
            "limit": 2,
        },
    )
    second = client.get(
        f"{base}/log",
        params={
            "workspace": str(repo),
            "all_branches": True,
            "skip": 2,
            "limit": 2,
        },
    )

    assert first.status_code == 200
    assert first.json()["has_more"] is True
    assert first.json()["next_skip"] == 2
    assert len(first.json()["entries"]) == 2
    assert first.json()["entries"][0]["parent_shas"]
    assert any("main" in ref for ref in first.json()["entries"][0]["refs"])
    assert second.status_code == 200
    assert {entry["sha"] for entry in first.json()["entries"]}.isdisjoint(
        {entry["sha"] for entry in second.json()["entries"]}
    )


def test_log_files_returns_files_for_selected_commit(app_without_team, tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    _git(repo, "commit", "-m", "add file")
    sha = _git(repo, "rev-parse", "HEAD")

    response = TestClient(app_without_team).get(
        f"/api/team/workspace/git/log/{sha}/files",
        params={"workspace": str(repo)},
    )

    assert response.status_code == 200
    assert response.json() == [{"path": "added.txt", "status": "A"}]
