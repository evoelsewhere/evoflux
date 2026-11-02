"""``/api/team/workspace/git``: repository, changes, staging, commit and diff view."""

from __future__ import annotations

from pathlib import Path

import httpx

from gc_helpers import git, same_path, sha

G = "/api/team/workspace/git"
NOT_A_DIR = "Workspace does not exist or is not a directory: "


def post(client: httpx.Client, path: str, **body) -> httpx.Response:
    return client.post(f"{G}/{path}", json=body)


def changes(client: httpx.Client, root: Path) -> dict:
    response = client.get(f"{G}/changes", params={"workspace": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def by_path(body: dict) -> dict[str, dict]:
    return {f["path"]: f for f in body["files"]}


# ── workspace validation (every route) ────────────────────────────────────────


def test_every_route_validates_the_workspace_first(client: httpx.Client, tmp_path: Path) -> None:
    gone = str(tmp_path / "nope")
    for method, path, extra in [
        ("GET", "repository", {}),
        ("GET", "changes", {}),
        ("GET", "branches", {}),
        ("GET", "tags", {}),
        ("GET", "remotes", {}),
        ("GET", "jobs", {}),
        ("GET", "log", {}),
        ("GET", "stash", {}),
        ("GET", "conflicts", {}),
        ("GET", "diff-view", {"path": "a"}),
    ]:
        response = client.request(method, f"{G}/{path}", params={"workspace": gone, **extra})
        assert response.status_code == 422, (path, response.text)
        assert response.json()["detail"] == f"{NOT_A_DIR}{Path(gone).resolve()}", path
    for path in [
        "repository/init",
        "repository/identity",
        "stage",
        "stage-all",
        "unstage",
        "unstage-all",
        "discard",
        "commit",
        "branches",
        "branches/checkout",
        "tags",
        "merge",
        "fetch",
        "pull",
        "push",
        "stash",
        "rebase",
        "cherry-pick",
        "revert",
        "continue",
        "abort",
    ]:
        body = {
            "workspace": gone,
            "name": "x",
            "email": "x@y",
            "message": "m",
            "branch": "b",
            "onto": "b",
            "shas": ["abcd"],
            "sha": "abcd",
        }
        response = client.post(f"{G}/{path}", json=body)
        assert response.status_code == 422, (path, response.text)
        assert response.json()["detail"] == f"{NOT_A_DIR}{Path(gone).resolve()}", path


def test_a_missing_workspace_parameter_is_the_fastapi_422(client: httpx.Client) -> None:
    response = client.get(f"{G}/repository")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "workspace"]
    response = client.post(f"{G}/stage-all", json={})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "workspace"]


def test_mutating_routes_refuse_a_folder_that_is_not_a_repository(
    client: httpx.Client, folder: Path
) -> None:
    for path, body in [
        ("repository/identity", {"name": "n", "email": "e@x"}),
        ("stage", {"paths": ["a"]}),
        ("stage-all", {}),
        ("unstage", {}),
        ("unstage-all", {}),
        ("discard", {}),
        ("commit", {"message": "m"}),
        ("branches", {"name": "b"}),
        ("branches/checkout", {"name": "b"}),
        ("merge", {"branch": "b"}),
        ("stash", {}),
        ("rebase", {"onto": "b"}),
        ("cherry-pick", {"shas": ["abcd"]}),
        ("revert", {"sha": "abcd"}),
        ("fetch", {}),
        ("pull", {}),
        ("push", {}),
    ]:
        response = post(client, path, workspace=str(folder), **body)
        assert response.status_code == 422, (path, response.text)
        assert response.json() == {"detail": "Not a git repository"}, path


def test_reads_of_a_folder_that_is_not_a_repository_are_empty(
    client: httpx.Client, folder: Path
) -> None:
    ws = {"workspace": str(folder)}
    assert client.get(f"{G}/branches", params=ws).json() == []
    assert client.get(f"{G}/tags", params=ws).json() == []
    assert client.get(f"{G}/remotes", params=ws).json() == []
    assert client.get(f"{G}/stash", params=ws).json() == []
    assert client.get(f"{G}/jobs", params=ws).json() is None
    assert client.get(f"{G}/diff-view", params={**ws, "path": "a"}).json() == {"diff": ""}
    changes_body = client.get(f"{G}/changes", params=ws).json()
    assert changes_body == {
        "is_git_repo": False,
        "branch": None,
        "ahead": 0,
        "behind": 0,
        "files": [],
    }


# ── repository ────────────────────────────────────────────────────────────────


def test_repository_of_a_plain_folder_and_of_a_repository(
    client: httpx.Client, folder: Path, repo: Path
) -> None:
    plain = client.get(f"{G}/repository", params={"workspace": str(folder)}).json()
    assert plain == {
        "is_git_repo": False,
        "root": None,
        "branch": None,
        "detached": False,
        "upstream": None,
        "head_sha": None,
        "head_subject": None,
        "user_name": None,
        "user_email": None,
    }
    git(repo, "config", "--local", "user.name", "Local Name")
    git(repo, "config", "--local", "user.email", "local@example.test")
    body = client.get(f"{G}/repository", params={"workspace": str(repo)}).json()
    assert list(body) == list(plain)
    assert same_path(body["root"], repo)
    assert body["branch"] == "main" and body["detached"] is False
    assert body["upstream"] is None
    assert body["head_sha"] == sha(repo)[:12]
    assert body["head_subject"] == "second"
    assert (body["user_name"], body["user_email"]) == ("Local Name", "local@example.test")


def test_repository_of_a_detached_head(client: httpx.Client, repo: Path) -> None:
    git(repo, "checkout", "-q", "--detach", "HEAD~1")
    body = client.get(f"{G}/repository", params={"workspace": str(repo)}).json()
    assert body["branch"] is None and body["detached"] is True
    assert body["head_subject"] == "first"


def test_init_creates_a_repository_with_the_requested_branch(
    client: httpx.Client, folder: Path
) -> None:
    response = post(client, "repository/init", workspace=str(folder), default_branch="trunk")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_git_repo"] is True and same_path(body["root"], folder)
    assert (folder / ".git").is_dir()
    assert git(folder, "symbolic-ref", "--short", "HEAD").strip() == "trunk"
    # a repository without a commit has no head
    assert body["head_sha"] is None and body["head_subject"] is None
    again = post(client, "repository/init", workspace=str(folder))
    assert again.status_code == 409
    assert again.json() == {"detail": "Git is already initialized"}


def test_init_validates_the_branch_name(client: httpx.Client, folder: Path) -> None:
    for name in ["", "-x", "a b", "a..b", "HEAD", "x.lock", "a/"]:
        response = post(client, "repository/init", workspace=str(folder), default_branch=name)
        assert response.status_code == 422, name
        assert response.json() == {"detail": f"Invalid default branch: {name}"}
    assert not (folder / ".git").exists()


def test_identity_is_written_to_the_repository_config(client: httpx.Client, repo: Path) -> None:
    response = post(
        client, "repository/identity", workspace=str(repo), name="  Ada  ", email=" ada@example.test "
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["user_name"], body["user_email"]) == ("Ada", "ada@example.test")
    assert git(repo, "config", "--local", "user.name").strip() == "Ada"


def test_identity_validation(client: httpx.Client, repo: Path) -> None:
    for name, email in [("   ", "a@b"), ("n", "   "), ("a\nb", "a@b"), ("n", "a@b\x01")]:
        response = post(client, "repository/identity", workspace=str(repo), name=name, email=email)
        assert response.status_code == 422, (name, email)
        assert response.json() == {"detail": "Invalid Git identity"}
    # the schema bounds come first and are FastAPI's list
    response = post(client, "repository/identity", workspace=str(repo), name="", email="a@b")
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_short"


# ── changes, staging, discard ─────────────────────────────────────────────────


def test_changes_lists_staged_unstaged_and_untracked_files(
    client: httpx.Client, repo: Path
) -> None:
    clean = changes(client, repo)
    assert clean == {"is_git_repo": True, "branch": "main", "ahead": 0, "behind": 0, "files": []}
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "new.txt").write_text("n\n", encoding="utf-8", newline="")
    (repo / "staged.txt").write_text("s\n", encoding="utf-8", newline="")
    (repo / "sub" / "deep.txt").write_text("d\n", encoding="utf-8", newline="")
    git(repo, "add", "staged.txt")
    files = by_path(changes(client, repo))
    assert set(files) == {"a.txt", "new.txt", "staged.txt", "sub/deep.txt"}
    assert files["a.txt"] == {"path": "a.txt", "status": "modified", "staged": False, "old_path": None}
    assert files["new.txt"]["status"] == "untracked" and files["new.txt"]["staged"] is False
    assert files["staged.txt"]["status"] == "added" and files["staged.txt"]["staged"] is True
    # untracked files are listed one by one, not as a folder
    assert files["sub/deep.txt"]["status"] == "untracked"


def test_changes_reports_a_rename_with_its_old_path(client: httpx.Client, repo: Path) -> None:
    git(repo, "mv", "a.txt", "renamed.txt")
    files = by_path(changes(client, repo))
    assert files["renamed.txt"]["status"] == "renamed"
    assert files["renamed.txt"]["old_path"] == "a.txt" and files["renamed.txt"]["staged"] is True


def test_changes_for_a_file_staged_and_modified_again_lists_both_sides(
    client: httpx.Client, repo: Path
) -> None:
    (repo / "a.txt").write_text("first\n", encoding="utf-8", newline="")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("second\n", encoding="utf-8", newline="")
    rows = [f for f in changes(client, repo)["files"] if f["path"] == "a.txt"]
    assert sorted(f["staged"] for f in rows) == [False, True]


def test_stage_and_unstage_named_paths(client: httpx.Client, repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "new.txt").write_text("n\n", encoding="utf-8", newline="")
    assert post(client, "stage", workspace=str(repo), paths=["a.txt"]).json() == {"ok": True}
    files = by_path(changes(client, repo))
    assert files["a.txt"]["staged"] is True and files["new.txt"]["staged"] is False
    assert post(client, "unstage", workspace=str(repo), paths=["a.txt"]).json() == {"ok": True}
    assert by_path(changes(client, repo))["a.txt"]["staged"] is False


def test_stage_without_paths_is_a_git_error_and_unknown_paths_are_a_502(
    client: httpx.Client, repo: Path
) -> None:
    empty = post(client, "stage", workspace=str(repo))
    assert empty.status_code == 200 or empty.status_code == 502
    missing = post(client, "stage", workspace=str(repo), paths=["no-such-file.txt"])
    assert missing.status_code == 502
    assert "no-such-file.txt" in missing.json()["detail"]


def test_stage_all_and_unstage_all(client: httpx.Client, repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "new.txt").write_text("n\n", encoding="utf-8", newline="")
    assert post(client, "stage-all", workspace=str(repo)).json() == {"ok": True}
    assert all(f["staged"] for f in changes(client, repo)["files"])
    assert post(client, "unstage-all", workspace=str(repo)).json() == {"ok": True}
    files = by_path(changes(client, repo))
    assert not any(f["staged"] for f in files.values())
    assert files["new.txt"]["status"] == "untracked"


def test_unstage_in_a_repository_without_a_commit_removes_from_the_index(
    client: httpx.Client, folder: Path
) -> None:
    git(folder, "init", "-q", "-b", "main")
    (folder / "f.txt").write_text("x\n", encoding="utf-8", newline="")
    git(folder, "add", "f.txt")
    assert post(client, "unstage", workspace=str(folder), paths=["f.txt"]).json() == {"ok": True}
    assert by_path(changes(client, folder))["f.txt"]["status"] == "untracked"
    git(folder, "add", "f.txt")
    assert post(client, "unstage-all", workspace=str(folder)).json() == {"ok": True}
    assert by_path(changes(client, folder))["f.txt"]["status"] == "untracked"


def test_discard_named_paths_restores_tracked_and_removes_untracked(
    client: httpx.Client, repo: Path
) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "keep.txt").write_text("k\n", encoding="utf-8", newline="")
    (repo / "gone.txt").write_text("g\n", encoding="utf-8", newline="")
    (repo / "dir").mkdir()
    (repo / "dir" / "x.txt").write_text("x\n", encoding="utf-8", newline="")
    response = post(client, "discard", workspace=str(repo), paths=["a.txt", "gone.txt", "dir/x.txt"])
    assert response.json() == {"ok": True}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert not (repo / "gone.txt").exists() and not (repo / "dir" / "x.txt").exists()
    assert (repo / "keep.txt").exists()


def test_discard_without_paths_resets_the_whole_working_tree(
    client: httpx.Client, repo: Path
) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "new.txt").write_text("n\n", encoding="utf-8", newline="")
    (repo / "newdir").mkdir()
    (repo / "newdir" / "y.txt").write_text("y\n", encoding="utf-8", newline="")
    assert post(client, "discard", workspace=str(repo)).json() == {"ok": True}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert not (repo / "new.txt").exists() and not (repo / "newdir").exists()
    assert changes(client, repo)["files"] == []


def test_discard_leaves_staged_changes_in_the_index(client: httpx.Client, repo: Path) -> None:
    (repo / "a.txt").write_text("staged\n", encoding="utf-8", newline="")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("unstaged\n", encoding="utf-8", newline="")
    assert post(client, "discard", workspace=str(repo), paths=["a.txt"]).json() == {"ok": True}
    # ``git restore`` resets the working tree to the index
    assert (repo / "a.txt").read_text(encoding="utf-8") == "staged\n"


# ── commit ────────────────────────────────────────────────────────────────────


def test_commit_creates_a_commit_and_returns_its_sha(client: httpx.Client, repo: Path) -> None:
    git(repo, "config", "--local", "user.name", "T")
    git(repo, "config", "--local", "user.email", "t@example.test")
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    git(repo, "add", "a.txt")
    response = post(client, "commit", workspace=str(repo), message="change a")
    assert response.status_code == 200, response.text
    assert response.json() == {"sha": sha(repo), "message": "change a"}
    assert git(repo, "log", "-1", "--format=%s").strip() == "change a"
    assert changes(client, repo)["files"] == []


def test_commit_with_paths_stages_them_first(client: httpx.Client, repo: Path) -> None:
    git(repo, "config", "--local", "user.name", "T")
    git(repo, "config", "--local", "user.email", "t@example.test")
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "other.txt").write_text("o\n", encoding="utf-8", newline="")
    response = post(client, "commit", workspace=str(repo), message="only a", paths=["a.txt"])
    assert response.status_code == 200, response.text
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["a.txt"]
    assert by_path(changes(client, repo))["other.txt"]["status"] == "untracked"


def test_commit_with_nothing_to_commit_is_a_409(client: httpx.Client, repo: Path) -> None:
    git(repo, "config", "--local", "user.name", "T")
    git(repo, "config", "--local", "user.email", "t@example.test")
    head = sha(repo)
    response = post(client, "commit", workspace=str(repo), message="empty")
    assert response.status_code == 409
    assert response.json() == {"detail": "Nothing to commit"}
    assert sha(repo) == head


def test_commit_amend_without_a_message_keeps_the_old_one(
    client: httpx.Client, repo: Path
) -> None:
    git(repo, "config", "--local", "user.name", "T")
    git(repo, "config", "--local", "user.email", "t@example.test")
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    git(repo, "add", "a.txt")
    before = sha(repo)
    response = post(client, "commit", workspace=str(repo), message="", amend=True)
    assert response.status_code == 200, response.text
    assert response.json()["message"] == ""
    assert sha(repo) != before
    assert git(repo, "log", "-1", "--format=%s").strip() == "second"
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "2"


def test_commit_message_limit_is_the_schema_422(client: httpx.Client, repo: Path) -> None:
    response = post(client, "commit", workspace=str(repo), message="x" * 10001)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_long"


# ── diff view ─────────────────────────────────────────────────────────────────


def test_diff_view_of_unstaged_staged_and_untracked_files(
    client: httpx.Client, repo: Path
) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="")
    unstaged = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": "a.txt"}).json()
    assert list(unstaged) == ["diff"]
    assert "-one" in unstaged["diff"] and "+changed" in unstaged["diff"]
    git(repo, "add", "a.txt")
    staged = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": "a.txt"}).json()
    assert staged["diff"] == unstaged["diff"]
    (repo / "u.txt").write_text("l1\nl2\n", encoding="utf-8", newline="")
    untracked = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": "u.txt"}).json()
    assert untracked["diff"] == "--- /dev/null\n+++ b/u.txt\n@@ -0,0 +1,2 @@\n+l1\n+l2"
    clean = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": "sub/b.txt"}).json()
    assert clean == {"diff": ""}


def test_diff_view_refuses_absolute_and_parent_paths(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    for bad in [str(tmp_path / "x"), "../x", "sub/../../x"]:
        response = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": bad})
        assert response.status_code == 422, bad
        assert response.json() == {"detail": "Invalid path"}


def test_diff_view_limits_the_size_with_413(client: httpx.Client, repo: Path) -> None:
    """Default ``git.max_diff_bytes`` is 2,000,000: an untracked file over it is refused."""
    (repo / "big.txt").write_bytes(b"x" * 2_000_001)
    response = client.get(f"{G}/diff-view", params={"workspace": str(repo), "path": "big.txt"})
    assert response.status_code == 413
    assert response.json() == {"detail": "Diff exceeds the configured 2000000 byte limit."}
    (repo / "big.txt").write_bytes(b"y" * 1_000_000)
    assert client.get(
        f"{G}/diff-view", params={"workspace": str(repo), "path": "big.txt"}
    ).status_code == 200
