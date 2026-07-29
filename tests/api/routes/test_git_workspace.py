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
