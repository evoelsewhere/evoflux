"""``/workspace/{status,git-diff/view,browse,tree}``: git state and folder pickers."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from ws_helpers import Scrub, git, init_repo, make_dir_link, remove_dir_link, same_path

WS = "/api/team/workspace"
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows path rules")
HAS_GIT = pytest.mark.skipif(
    os.system("git --version >nul 2>&1" if os.name == "nt" else "git --version >/dev/null 2>&1") != 0,
    reason="git is not installed",
)


def status(client: httpx.Client, root: Path) -> dict:
    response = client.get(f"{WS}/status", params={"workspace": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def diff(client: httpx.Client, root: Path, *paths: str) -> dict:
    response = client.get(
        f"{WS}/git-diff/view", params={"workspace": str(root), "paths": list(paths)}
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── status ────────────────────────────────────────────────────────────────────


def test_status_of_a_plain_folder(client: httpx.Client, workspace: Path) -> None:
    body = status(client, workspace)
    assert list(body) == ["workspace", "name", "is_git_repo"]
    assert same_path(body["workspace"], workspace)
    assert body["name"] == "ws" and body["is_git_repo"] is False


def test_status_validates_the_folder(client: httpx.Client, tmp_path: Path) -> None:
    response = client.get(f"{WS}/status", params={"workspace": str(tmp_path / "nope")})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Workspace does not exist or is not a directory: ")
    assert client.get(f"{WS}/status").status_code == 422


@HAS_GIT
def test_status_of_a_repository(client: httpx.Client, workspace: Path) -> None:
    init_repo(workspace, **{"tracked.txt": "one\n"})
    (workspace / "tracked.txt").write_text("two\n", encoding="utf-8", newline="")
    (workspace / "staged.txt").write_text("s\n", encoding="utf-8", newline="")
    git(workspace, "add", "staged.txt")
    (workspace / "untracked.txt").write_text("u\n", encoding="utf-8", newline="")
    body = status(client, workspace)
    assert list(body) == ["workspace", "name", "is_git_repo", "branch", "dirty", "head"]
    assert body["is_git_repo"] is True and body["branch"] == "main"
    assert body["dirty"] == {"staged": 1, "unstaged": 1, "untracked": 1}  # init_repo commits every file the fixture made
    head = body["head"]
    assert set(head) == {"sha", "subject", "timestamp"}
    assert head["subject"] == "first" and len(head["sha"]) >= 7
    assert head["sha"] == git(workspace, "rev-parse", "--short", "HEAD").strip()
    assert isinstance(head["timestamp"], int)


@HAS_GIT
def test_status_of_an_empty_repository_and_a_detached_head(
    client: httpx.Client, tmp_path: Path
) -> None:
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "trunk")
    body = status(client, empty)
    assert body["is_git_repo"] is True and body["branch"] == "trunk"
    assert body["head"] is None
    assert body["dirty"] == {"staged": 0, "unstaged": 0, "untracked": 0}

    repo = tmp_path / "detached"
    init_repo(repo, **{"f.txt": "1\n"})
    git(repo, "checkout", "-q", "--detach")
    assert status(client, repo)["branch"] is None


@HAS_GIT
def test_a_subfolder_of_a_repository_is_not_a_repository(
    client: httpx.Client, workspace: Path
) -> None:
    init_repo(workspace, **{"f.txt": "1\n"})
    assert status(client, workspace / "sub")["is_git_repo"] is False
    body = diff(client, workspace / "sub")
    assert body["is_git_repo"] is False and body["diff"] == ""


@HAS_GIT
def test_a_dot_git_file_counts_as_a_repository(
    client: httpx.Client, workspace: Path
) -> None:
    (workspace / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
    # git fails, so status degrades to a plain folder instead of a 500
    body = status(client, workspace)
    assert body["is_git_repo"] is False and "branch" not in body


# ── git diff ──────────────────────────────────────────────────────────────────


def test_diff_of_a_plain_folder(client: httpx.Client, workspace: Path) -> None:
    body = diff(client, workspace)
    assert list(body) == ["workspace", "is_git_repo", "diff"]
    assert body["is_git_repo"] is False and body["diff"] == ""
    response = client.get(f"{WS}/git-diff/view", params={"workspace": str(workspace / "nope")})
    assert response.status_code == 422


@HAS_GIT
def test_diff_against_head_includes_staged_unstaged_and_untracked(
    client: httpx.Client, workspace: Path
) -> None:
    init_repo(workspace, **{"in.txt": "in\n"})
    (workspace / "in.txt").write_text("changed\n", encoding="utf-8", newline="")
    (workspace / "added.txt").write_text("added\n", encoding="utf-8", newline="")
    git(workspace, "add", "added.txt")
    (workspace / "new.txt").write_text("brand new\n", encoding="utf-8", newline="")
    (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00")
    body = diff(client, workspace)
    assert list(body) == ["workspace", "is_git_repo", "diff", "untracked", "truncated"]
    assert body["is_git_repo"] is True and body["truncated"] is False
    assert sorted(body["untracked"]) == ["bin.dat", "new.txt"]
    text = body["diff"]
    assert "diff --git a/in.txt b/in.txt" in text and "+changed" in text
    assert "diff --git a/added.txt b/added.txt" in text and "+added" in text
    # untracked files are synthesised, with a hand-written header
    assert "\ndiff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+brand new\n" in text
    assert "\ndiff --git a/bin.dat b/bin.dat\nnew file mode 100644\nBinary or unreadable file not shown: bin.dat\n" in text


@HAS_GIT
def test_diff_of_a_repository_without_a_commit_uses_the_empty_tree(
    client: httpx.Client, tmp_path: Path
) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "s.txt").write_text("staged\n", encoding="utf-8", newline="")
    git(repo, "add", "s.txt")
    (repo / "u.txt").write_text("untracked\n", encoding="utf-8", newline="")
    body = diff(client, repo)
    assert body["untracked"] == ["u.txt"]
    assert "diff --git a/s.txt b/s.txt" in body["diff"] and "+staged" in body["diff"]
    assert "+untracked" in body["diff"]


@HAS_GIT
def test_diff_caps_large_untracked_files_and_the_whole_diff(
    client: httpx.Client, workspace: Path
) -> None:
    init_repo(workspace, **{"big.txt": "x\n"})
    (workspace / "huge-new.txt").write_text("y" * (256 * 1024 + 1), encoding="utf-8", newline="")
    body = diff(client, workspace)
    assert (
        "\ndiff --git a/huge-new.txt b/huge-new.txt\nnew file mode 100644\n"
        "Binary or large file not shown: huge-new.txt\n"
    ) in body["diff"]
    # a tracked change over 512 KiB characters is cut and flagged
    (workspace / "big.txt").write_text(("line of text\n" * 60_000), encoding="utf-8", newline="")
    body = diff(client, workspace)
    assert body["truncated"] is True
    assert len(body["diff"]) == 512 * 1024


@HAS_GIT
def test_scoped_diff(client: httpx.Client, workspace: Path) -> None:
    init_repo(workspace, **{"in.txt": "in\n", "other.txt": "o\n"})
    (workspace / "in.txt").write_text("changed\n", encoding="utf-8", newline="")
    (workspace / "other.txt").write_text("changed too\n", encoding="utf-8", newline="")
    (workspace / "new.txt").write_text("brand new\n", encoding="utf-8", newline="")
    (workspace / "new2.txt").write_text("brand new 2\n", encoding="utf-8", newline="")
    body = diff(client, workspace, "new.txt")
    assert body["untracked"] == ["new.txt"]
    assert "in.txt" not in body["diff"] and "new2.txt" not in body["diff"]
    assert "+brand new\n" in body["diff"]
    both = diff(client, workspace, "in.txt", "", "new2.txt")  # empty entries are dropped
    assert both["untracked"] == ["new2.txt"]
    assert "+changed\n" in both["diff"] and "other.txt" not in both["diff"]
    # a missing path just gives an empty diff
    none = diff(client, workspace, "does-not-exist.txt")
    assert none["diff"] == "" and none["untracked"] == []


@HAS_GIT
def test_scoped_diff_refusals(client: httpx.Client, workspace: Path, outside: Path) -> None:
    init_repo(workspace, **{"in.txt": "in\n"})
    for bad in ("../x", "sub/../../x", str(outside), ".."):
        response = client.get(
            f"{WS}/git-diff/view", params={"workspace": str(workspace), "paths": [bad]}
        )
        assert response.status_code == 422, bad
        assert response.json() == {"detail": f"invalid path in scoped diff: {bad}"}
    # Suspected bug B4: the check is a string prefix, so a file whose name
    # starts with two dots is refused too.
    dots = client.get(
        f"{WS}/git-diff/view", params={"workspace": str(workspace), "paths": ["..hidden"]}
    )
    assert dots.status_code == 422
    # sub/../x normalises to x, which stays inside, so it is accepted
    ok = client.get(
        f"{WS}/git-diff/view", params={"workspace": str(workspace), "paths": ["sub/../in.txt"]}
    )
    assert ok.status_code == 200


@HAS_GIT
def test_scoped_diff_passes_the_path_after_a_double_dash(
    client: httpx.Client, workspace: Path
) -> None:
    """An option-looking path is a pathspec, not an option; ``:(top)`` magic is accepted."""
    init_repo(workspace, **{"in.txt": "in\n"})
    (workspace / "in.txt").write_text("changed\n", encoding="utf-8", newline="")
    body = diff(client, workspace, "--output=pwn.txt")
    assert body["diff"] == ""
    assert not (workspace / "pwn.txt").exists()
    magic = diff(client, workspace, ":(top)in.txt")
    assert "+changed" in magic["diff"]
    # the pathspec may name a folder; untracked files under it are then dropped
    (workspace / "sub" / "n.txt").write_text("n\n", encoding="utf-8", newline="")
    folder = diff(client, workspace, "sub")
    assert folder["untracked"] == []  # suspected bug B5: only exact file names match


@HAS_GIT
@WINDOWS
def test_scoped_diff_of_an_untracked_file_in_a_folder_is_empty_on_windows(
    client: httpx.Client, workspace: Path
) -> None:
    """Suspected bug B6: ``normpath`` turns ``sub/n.txt`` into ``sub\\n.txt``,
    which never equals the ``sub/n.txt`` git prints, so the SSE splice path
    never sees an untracked file in a sub-folder."""
    init_repo(workspace, **{"in.txt": "in\n"})
    (workspace / "sub" / "n.txt").write_text("n\n", encoding="utf-8", newline="")
    body = diff(client, workspace, "sub/n.txt")
    assert body["untracked"] == []
    assert "n.txt" not in body["diff"]
    whole = diff(client, workspace)
    assert "sub/n.txt" in whole["untracked"]


@HAS_GIT
def test_diff_reads_untracked_files_through_a_directory_link(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    """Suspected bug S2: the untracked scan follows a link out of the workspace
    and returns the content of a file that is outside it."""
    init_repo(workspace, **{"in.txt": "in\n"})
    link = workspace / "jn"
    if not make_dir_link(link, outside):
        pytest.skip("cannot create a directory link on this machine")
    try:
        # while the files routes refuse the same path ...
        refused = client.get(
            "/api/team/workspace/files/read",
            params={"workspace": str(workspace), "path": "jn/secret.txt"},
        )
        assert refused.status_code == 400
        # ... the diff route copies the outside file into its answer.
        body = diff(client, workspace)
        assert "jn/secret.txt" in body["untracked"]
        assert "+SECRET" in body["diff"]
    finally:
        remove_dir_link(link)


@HAS_GIT
def test_git_runs_the_repository_s_own_fsmonitor_hook(
    client: httpx.Client, workspace: Path, tmp_path: Path
) -> None:
    """Suspected bug S3: ``status`` and ``git-diff`` run ``git`` without
    ``-c core.fsmonitor=false`` (the snapshot service passes it), so a
    repository's ``core.fsmonitor`` command runs when the folder is opened."""
    init_repo(workspace, **{"in.txt": "in\n"})
    marker = tmp_path / "fsmonitor-ran.txt"
    hook = tmp_path / "hook.sh"
    hook.write_text(f'#!/bin/sh\necho ran > "{marker.as_posix()}"\nexit 1\n', encoding="utf-8", newline="")
    git(workspace, "config", "core.fsmonitor", f"sh {hook.as_posix()}")
    (workspace / "in.txt").write_text("changed\n", encoding="utf-8", newline="")
    status(client, workspace)
    diff(client, workspace)
    assert marker.exists(), "git did not run the configured fsmonitor command"


# ── browse ────────────────────────────────────────────────────────────────────


def test_browse_lists_visible_folders_sorted_without_case(
    client: httpx.Client, tmp_path: Path
) -> None:
    root = tmp_path / "browse"
    for name in ("beta", "Alpha", "gamma", ".hidden"):
        (root / name).mkdir(parents=True)
    (root / "file.txt").write_text("f", encoding="utf-8")
    body = client.get(f"{WS}/browse", params={"path": str(root)}).json()
    assert list(body) == ["path", "parent", "directories"]
    assert same_path(body["path"], root) and same_path(body["parent"], tmp_path)
    assert [d["name"] for d in body["directories"]] == ["Alpha", "beta", "gamma"]
    assert all(set(d) == {"name", "path"} for d in body["directories"])
    assert same_path(body["directories"][0]["path"], root / "Alpha")


def test_browse_defaults_resolves_and_refuses(
    client: httpx.Client, tmp_path: Path, scrub: Scrub
) -> None:
    home = tmp_path / "home"
    (home / "projects").mkdir(exist_ok=True)
    default = client.get(f"{WS}/browse").json()
    assert same_path(default["path"], home)
    assert "projects" in [d["name"] for d in default["directories"]]
    assert same_path(client.get(f"{WS}/browse", params={"path": ""}).json()["path"], home)
    assert same_path(client.get(f"{WS}/browse", params={"path": "~"}).json()["path"], home)
    # a relative path is resolved against the sidecar's working directory
    relative = client.get(f"{WS}/browse", params={"path": "."}).json()
    assert same_path(relative["path"], tmp_path / "cwd")

    a_file = tmp_path / "plain.txt"
    a_file.write_text("x", encoding="utf-8")
    for bad in (a_file, tmp_path / "nope"):
        response = client.get(f"{WS}/browse", params={"path": str(bad)})
        assert response.status_code == 422
        assert scrub(response.json())["detail"].startswith("Not a directory: <tmp>/")

    # the root of the drive has no parent
    anchor = client.get(f"{WS}/browse", params={"path": tmp_path.anchor}).json()
    assert anchor["parent"] is None


def test_browse_has_no_allowlist(client: httpx.Client, tmp_path: Path) -> None:
    """Suspected bug S1: any folder on the machine can be listed (names only)."""
    response = client.get(f"{WS}/browse", params={"path": tmp_path.anchor})
    assert response.status_code == 200
    assert response.json()["directories"], "a drive root has sub-folders"


def test_browse_folds_links_to_one_entry_and_keeps_the_first_name(
    client: httpx.Client, tmp_path: Path
) -> None:
    root = tmp_path / "dups"
    (root / "real").mkdir(parents=True)
    if not make_dir_link(root / "alias", root / "real"):
        pytest.skip("cannot create a directory link on this machine")
    try:
        body = client.get(f"{WS}/browse", params={"path": str(root)}).json()
        # "alias" sorts first and wins; both resolve to <root>/real
        assert [d["name"] for d in body["directories"]] == ["alias"]
        assert same_path(body["directories"][0]["path"], root / "real")
    finally:
        remove_dir_link(root / "alias")


# ── tree ──────────────────────────────────────────────────────────────────────


def test_tree_is_empty_without_projects(client: httpx.Client) -> None:
    assert client.get(f"{WS}/tree").json() == {"repositories": [], "projects": []}


def test_tree_lists_the_repositories_of_a_project(
    client: httpx.Client, workspace: Path, scrub: Scrub
) -> None:
    created = client.post(
        "/api/team/projects", json={"name": "demo", "workspace_paths": [str(workspace)]}
    )
    assert created.status_code == 201, created.text
    project = created.json()
    body = client.get(f"{WS}/tree").json()
    assert set(body) == {"repositories", "projects"}
    [repo] = body["repositories"]
    assert set(repo) == {"workspace_id", "path", "name", "worktrees", "project_id"}
    assert same_path(repo["path"], workspace)
    assert repo["name"] == "ws" and repo["worktrees"] == []
    assert repo["project_id"] == project["id"]
    assert [p["id"] for p in body["projects"]] == [project["id"]]
    assert body["projects"][0]["name"] == "demo"
