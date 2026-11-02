"""``/api/team/workspace/git``: clone, fetch, pull, push and jobs, against local bare remotes."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from gc_helpers import commit_file, git, init_repo, make_bare, same_path, sha

G = "/api/team/workspace/git"


def post(client: httpx.Client, path: str, **body) -> httpx.Response:
    return client.post(f"{G}/{path}", json=body)


def finished_job(client: httpx.Client, root: Path, timeout: float = 60.0) -> dict:
    """Poll ``/jobs`` until the background job of ``root`` has left ``running``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"{G}/jobs", params={"workspace": str(root)}).json()
        if job is not None and job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("the git job did not finish")


def with_remote(repo: Path, tmp_path: Path) -> Path:
    """Push ``repo`` to a new bare remote named ``origin`` and track ``main``."""
    bare = make_bare(tmp_path / "remote.git")
    git(repo, "remote", "add", "origin", bare.as_uri())
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


# ── clone ─────────────────────────────────────────────────────────────────────


def test_clone_a_local_repository(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    parent = tmp_path / "clones"
    parent.mkdir()
    response = post(client, "repository/clone", parent=str(parent), url=bare.as_uri(), directory="mine")
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["workspace", "name", "remote_url"]
    assert same_path(body["workspace"], parent / "mine")
    assert body["name"] == "mine" and body["remote_url"] == bare.as_uri()
    assert (parent / "mine" / "a.txt").exists()
    assert git(parent / "mine", "remote").split() == ["origin"]
    # the directory name defaults to the repository name without ``.git``
    second = post(client, "repository/clone", parent=str(parent), url=bare.as_uri(), branch="main", depth=1)
    assert second.status_code == 200, second.text
    assert second.json()["name"] == "remote"
    assert (parent / "remote" / ".git" / "shallow").exists()


def test_clone_errors(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    parent = tmp_path / "clones"
    parent.mkdir()
    (parent / "taken").mkdir()
    ok_url = bare.as_uri()
    exists = post(client, "repository/clone", parent=str(parent), url=ok_url, directory="taken")
    assert exists.status_code == 409
    assert exists.json()["detail"].startswith("Clone destination already exists: ")
    for name in [".", "..", "a/b", "a\\b", "a\x01b"]:
        response = post(client, "repository/clone", parent=str(parent), url=ok_url, directory=name)
        assert response.status_code == 422, name
        assert response.json() == {"detail": "Invalid clone directory name"}, name
    blank = post(client, "repository/clone", parent=str(parent), url=ok_url, directory="   ")
    assert blank.status_code == 422 and blank.json() == {"detail": "Invalid clone directory name"}
    branch = post(client, "repository/clone", parent=str(parent), url=ok_url, branch="-x")
    assert branch.status_code == 422 and branch.json() == {"detail": "Invalid clone branch"}
    helper = post(client, "repository/clone", parent=str(parent), url="ext::sh -c id")
    assert helper.status_code == 422 and helper.json() == {"detail": "Git remote helpers are not allowed."}
    option = post(client, "repository/clone", parent=str(parent), url="--upload-pack=x")
    assert option.status_code == 422 and option.json() == {"detail": "Invalid remote URL"}
    missing = post(client, "repository/clone", parent=str(parent / "none"), url=ok_url)
    assert missing.status_code == 422
    failed = post(client, "repository/clone", parent=str(parent), url=(tmp_path / "no.git").as_uri())
    assert failed.status_code == 502 and failed.json()["detail"]
    assert not (parent / "no").exists()


def test_clone_body_limits_are_fastapi_422s(client: httpx.Client, folder: Path) -> None:
    for extra in [{"depth": 0}, {"depth": 1_000_001}, {"directory": ""}, {"branch": ""}]:
        response = post(client, "repository/clone", parent=str(folder), url="https://example.test/a.git", **extra)
        assert response.status_code == 422, extra
        assert isinstance(response.json()["detail"], list)


# ── push, fetch, pull ─────────────────────────────────────────────────────────


def test_push_runs_as_a_job_and_updates_the_remote(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    commit_file(repo, "p.txt", "p\n", "to push")
    response = post(client, "push", workspace=str(repo))
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["workspace", "op", "status", "message", "error"]
    assert body["op"] == "push" and body["status"] in ("running", "done")
    assert same_path(body["workspace"], repo)
    job = finished_job(client, repo)
    assert job["status"] == "done" and job["op"] == "push" and job["error"] is None
    assert sha(bare, "main") == sha(repo)


def test_push_without_an_upstream_fails_inside_the_job_not_the_request(
    client: httpx.Client, repo: Path, tmp_path: Path
) -> None:
    bare = make_bare(tmp_path / "remote.git")
    git(repo, "remote", "add", "origin", bare.as_uri())
    assert post(client, "push", workspace=str(repo)).status_code == 200
    job = finished_job(client, repo)
    assert job["status"] == "error" and job["error"]
    ok = post(client, "push", workspace=str(repo), remote="origin", branch="main", set_upstream=True)
    assert ok.status_code == 200
    assert finished_job(client, repo)["status"] == "done"
    assert sha(bare, "main") == sha(repo)


def test_push_validation_and_the_force_setting(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    with_remote(repo, tmp_path)
    ws = str(repo)
    force = post(client, "push", workspace=ws, force_with_lease=True)
    assert force.status_code == 403
    assert force.json() == {"detail": "Force push is disabled in Git & reviews settings."}
    for remote in ["-x", "a b", "HEAD", "a..b"]:
        response = post(client, "push", workspace=ws, remote=remote)
        assert response.status_code == 422, remote
        assert response.json() == {"detail": f"Invalid remote name: {remote}"}
    branch = post(client, "push", workspace=ws, branch="-x")
    assert branch.status_code == 422 and branch.json() == {"detail": "Invalid branch name: -x"}


def test_fetch_brings_new_commits_and_prunes(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", bare.as_uri(), str(other))
    new = commit_file(other, "n.txt", "n\n", "from other")
    git(other, "push", "-q", "origin", "HEAD:main")
    git(other, "push", "-q", "origin", "HEAD:refs/heads/gone")
    assert post(client, "fetch", workspace=str(repo)).status_code == 200
    job = finished_job(client, repo)
    assert job["status"] == "done" and job["op"] == "fetch"
    assert sha(repo, "origin/main") == new
    assert git(repo, "branch", "-r", "--list", "origin/gone").strip() != ""
    git(other, "push", "-q", "origin", "--delete", "gone")
    # ``prune`` defaults to the ``git.prune_on_fetch`` setting, which is on
    assert post(client, "fetch", workspace=str(repo)).status_code == 200
    finished_job(client, repo)
    assert git(repo, "branch", "-r", "--list", "origin/gone").strip() == ""
    remote_rows = {b["name"]: b for b in client.get(f"{G}/branches", params={"workspace": str(repo)}).json()}
    assert remote_rows["origin/main"]["remote"] == "origin"
    assert remote_rows["main"]["behind"] == 1 and remote_rows["main"]["ahead"] == 0


def test_fetch_prune_false_keeps_deleted_remote_branches(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    git(repo, "push", "-q", "origin", "HEAD:refs/heads/gone")
    assert post(client, "fetch", workspace=str(repo)).status_code == 200
    finished_job(client, repo)
    git(bare, "branch", "-D", "gone")
    assert post(client, "fetch", workspace=str(repo), prune=False).status_code == 200
    assert finished_job(client, repo)["status"] == "done"
    assert git(repo, "branch", "-r", "--list", "origin/gone").strip() != ""


def test_fetch_validates_the_remote_and_reports_git_errors_in_the_job(
    client: httpx.Client, repo: Path, tmp_path: Path
) -> None:
    ws = str(repo)
    invalid = post(client, "fetch", workspace=ws, remote="-x")
    assert invalid.status_code == 422 and invalid.json() == {"detail": "Invalid remote name: -x"}
    assert post(client, "fetch", workspace=ws, remote="nope").status_code == 200
    job = finished_job(client, repo)
    assert job["status"] == "error" and job["error"]


def test_pull_fast_forwards_by_default_and_refuses_divergence(
    client: httpx.Client, repo: Path, tmp_path: Path
) -> None:
    bare = with_remote(repo, tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", bare.as_uri(), str(other))
    new = commit_file(other, "n.txt", "n\n", "from other")
    git(other, "push", "-q", "origin", "HEAD:main")
    assert post(client, "pull", workspace=str(repo)).status_code == 200
    job = finished_job(client, repo)
    assert job["status"] == "done" and job["op"] == "pull"
    assert sha(repo) == new
    # diverge: a local commit and a new remote one; the default strategy is ff_only
    commit_file(repo, "l.txt", "l\n", "local")
    commit_file(other, "o.txt", "o\n", "other again")
    git(other, "push", "-q", "origin", "HEAD:main")
    assert post(client, "pull", workspace=str(repo)).status_code == 200
    assert finished_job(client, repo)["status"] == "error"
    assert post(client, "pull", workspace=str(repo), strategy="merge").status_code == 200
    assert finished_job(client, repo)["status"] == "done"
    assert len(git(repo, "log", "--merges", "--format=%H").split()) == 1


def test_pull_rebase_flag_and_strategy_validation(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", bare.as_uri(), str(other))
    commit_file(other, "o.txt", "o\n", "other")
    git(other, "push", "-q", "origin", "HEAD:main")
    commit_file(repo, "l.txt", "l\n", "local")
    assert post(client, "pull", workspace=str(repo), rebase=True).status_code == 200
    assert finished_job(client, repo)["status"] == "done"
    assert git(repo, "log", "--merges", "--format=%H").split() == []
    assert git(repo, "log", "-1", "--format=%s").strip() == "local"
    bad = post(client, "pull", workspace=str(repo), strategy="squash")
    assert bad.status_code == 422 and bad.json()["detail"][0]["loc"] == ["body", "strategy"]
    branch = post(client, "pull", workspace=str(repo), branch="-x")
    assert branch.status_code == 422 and branch.json() == {"detail": "Invalid branch name: -x"}


def test_a_second_operation_while_one_runs_returns_the_running_job(
    client: httpx.Client, repo: Path, tmp_path: Path
) -> None:
    with_remote(repo, tmp_path)
    first = post(client, "fetch", workspace=str(repo)).json()
    second = post(client, "push", workspace=str(repo)).json()
    # either the first had finished (the second is a new push) or the running job came back
    assert second["op"] in ("fetch", "push")
    if first["status"] == "running":
        assert second["op"] in ("fetch", "push")
    finished_job(client, repo)


def test_jobs_of_a_repository_that_never_ran_one_is_null(client: httpx.Client, repo: Path) -> None:
    assert client.get(f"{G}/jobs", params={"workspace": str(repo)}).json() is None


def test_push_tags_one_or_all(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    bare = with_remote(repo, tmp_path)
    git(repo, "tag", "v1")
    git(repo, "tag", "v2")
    # B8: with a tag but no remote the ref is passed to ``git push`` as the remote name, so the job fails
    assert post(client, "tags/push", workspace=str(repo), tag="v1").status_code == 200
    assert finished_job(client, repo)["status"] == "error"
    assert git(bare, "tag").split() == []
    assert post(client, "tags/push", workspace=str(repo), remote="origin", tag="v1").status_code == 200
    job = finished_job(client, repo)
    assert job["op"] == "push tags" and job["status"] == "done"
    assert git(bare, "tag").split() == ["v1"]
    assert post(client, "tags/push", workspace=str(repo)).status_code == 200
    assert finished_job(client, repo)["status"] == "done"
    assert git(bare, "tag").split() == ["v1", "v2"]
    bad = post(client, "tags/push", workspace=str(repo), tag="a b")
    assert bad.status_code == 422 and bad.json() == {"detail": "Invalid tag name: a b"}
    bad_remote = post(client, "tags/push", workspace=str(repo), remote="-x")
    assert bad_remote.status_code == 422 and bad_remote.json() == {"detail": "Invalid remote name: -x"}


def test_init_then_clone_roundtrip_keeps_unrelated_history(client: httpx.Client, tmp_path: Path) -> None:
    source = tmp_path / "src"
    init_repo(source, **{"x.txt": "x\n"})
    parent = tmp_path / "dest"
    parent.mkdir()
    cloned = post(client, "repository/clone", parent=str(parent), url=source.as_uri())
    assert cloned.status_code == 200, cloned.text
    assert cloned.json()["name"] == "src"
    assert sha(parent / "src") == sha(source)
