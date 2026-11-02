"""``/api/team/workspace/git``: branches, tags, log, stash, merge, rebase, conflicts."""

from __future__ import annotations

from pathlib import Path

import httpx

from gc_helpers import commit_file, git, sha

G = "/api/team/workspace/git"


def post(client: httpx.Client, path: str, **body) -> httpx.Response:
    return client.post(f"{G}/{path}", json=body)


def request(client: httpx.Client, method: str, path: str, **body) -> httpx.Response:
    return client.request(method, f"{G}/{path}", json=body)


def branches(client: httpx.Client, root: Path) -> list[dict]:
    response = client.get(f"{G}/branches", params={"workspace": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def head_branch(root: Path) -> str:
    return git(root, "symbolic-ref", "--short", "HEAD").strip()


def conflicted_repo(repo: Path) -> None:
    """``main`` and ``other`` both change a.txt: merging one into the other conflicts."""
    git(repo, "checkout", "-qb", "other")
    commit_file(repo, "a.txt", "from other\n", "other change")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "a.txt", "from main\n", "main change")


# ── branches ──────────────────────────────────────────────────────────────────


def test_branch_listing_marks_the_current_branch(client: httpx.Client, repo: Path) -> None:
    git(repo, "branch", "feature")
    rows = branches(client, repo)
    assert rows == [
        {"name": "feature", "current": False, "remote": None, "ahead": 0, "behind": 0},
        {"name": "main", "current": True, "remote": None, "ahead": 0, "behind": 0},
    ]


def test_create_branch_checks_it_out_by_default(client: httpx.Client, repo: Path) -> None:
    assert post(client, "branches", workspace=str(repo), name="feat/x").json() == {"ok": True}
    assert head_branch(repo) == "feat/x"
    assert post(
        client, "branches", workspace=str(repo), name="keep", checkout=False, start_point="HEAD~1"
    ).json() == {"ok": True}
    assert head_branch(repo) == "feat/x"
    assert sha(repo, "keep") == sha(repo, "HEAD~1")


def test_create_branch_errors(client: httpx.Client, repo: Path) -> None:
    for name in ["", "-x", "a b", "a..b", "@", "HEAD", "x.lock", "a/", "a~1", "a:b"]:
        response = post(client, "branches", workspace=str(repo), name=name)
        assert response.status_code == 422, name
        assert response.json() == {"detail": f"Invalid branch name: {name}"}
    duplicate = post(client, "branches", workspace=str(repo), name="main")
    assert duplicate.status_code == 502
    assert "already exists" in duplicate.json()["detail"]
    bad_start = post(client, "branches", workspace=str(repo), name="n", start_point="nope")
    assert bad_start.status_code == 502


def test_checkout_switches_branches_and_refuses_unknown_and_invalid_names(
    client: httpx.Client, repo: Path
) -> None:
    git(repo, "branch", "other")
    assert post(client, "branches/checkout", workspace=str(repo), name="other").json() == {"ok": True}
    assert head_branch(repo) == "other"
    missing = post(client, "branches/checkout", workspace=str(repo), name="nope")
    assert missing.status_code == 502
    invalid = post(client, "branches/checkout", workspace=str(repo), name="--detach")
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "Invalid ref name: --detach"}


def test_checkout_with_a_conflicting_local_change_is_a_502_and_keeps_the_branch(
    client: httpx.Client, repo: Path
) -> None:
    conflicted_repo(repo)
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8", newline="")
    response = post(client, "branches/checkout", workspace=str(repo), name="other")
    assert response.status_code == 502
    assert head_branch(repo) == "main"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "dirty\n"


def test_delete_branch_needs_force_for_unmerged_work(client: httpx.Client, repo: Path) -> None:
    git(repo, "checkout", "-qb", "work")
    commit_file(repo, "w.txt", "w\n", "work")
    git(repo, "checkout", "-q", "main")
    refused = request(client, "DELETE", "branches", workspace=str(repo), name="work")
    assert refused.status_code == 502
    assert "not fully merged" in refused.json()["detail"]
    forced = request(client, "DELETE", "branches", workspace=str(repo), name="work", force=True)
    assert forced.json() == {"ok": True}
    assert [b["name"] for b in branches(client, repo)] == ["main"]
    current = request(client, "DELETE", "branches", workspace=str(repo), name="main", force=True)
    assert current.status_code == 502
    invalid = request(client, "DELETE", "branches", workspace=str(repo), name="-D")
    assert invalid.status_code == 422


# ── tags ──────────────────────────────────────────────────────────────────────


def test_tags_create_list_and_delete(client: httpx.Client, repo: Path) -> None:
    assert post(client, "tags", workspace=str(repo), name="v1").json() == {"ok": True}
    assert post(
        client, "tags", workspace=str(repo), name="v2", target="HEAD~1", message="release two"
    ).json() == {"ok": True}
    rows = client.get(f"{G}/tags", params={"workspace": str(repo)}).json()
    assert {r["name"] for r in rows} == {"v1", "v2"}
    by_name = {r["name"]: r for r in rows}
    assert list(by_name["v1"]) == ["name", "sha", "subject", "date"]
    assert by_name["v1"]["subject"] == "second"
    # an annotated tag lists the tag object's id (12 characters), not the commit's
    assert len(by_name["v1"]["sha"]) == 12 and len(by_name["v2"]["sha"]) == 12
    assert by_name["v1"]["sha"] == sha(repo)[:12]
    assert by_name["v2"]["subject"] == "release two"
    assert request(client, "DELETE", "tags", workspace=str(repo), name="v1").json() == {"ok": True}
    assert [r["name"] for r in client.get(f"{G}/tags", params={"workspace": str(repo)}).json()] == ["v2"]


def test_tag_errors_and_limit_clamping(client: httpx.Client, repo: Path) -> None:
    for name in ["", "a b", "a..b", "x.lock"]:
        response = post(client, "tags", workspace=str(repo), name=name)
        assert response.status_code == 422, name
        assert response.json() == {"detail": f"Invalid tag name: {name}"}
    # B7: ``-x`` passes ``check-ref-format`` and then reaches ``git tag`` as an option (argument injection)
    assert post(client, "tags", workspace=str(repo), name="-x").status_code == 502
    post(client, "tags", workspace=str(repo), name="v1")
    assert post(client, "tags", workspace=str(repo), name="v1").status_code == 502
    assert post(client, "tags", workspace=str(repo), name="v3", target="nope").status_code == 502
    assert request(client, "DELETE", "tags", workspace=str(repo), name="nope").status_code == 502
    one = client.get(f"{G}/tags", params={"workspace": str(repo), "limit": 0}).json()
    assert len(one) == 1
    negative = client.get(f"{G}/tags", params={"workspace": str(repo), "limit": -5}).json()
    assert len(negative) == 1


# ── remotes ───────────────────────────────────────────────────────────────────


def test_remote_add_list_update_delete(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    assert post(client, "remotes", workspace=ws, name="origin", url="https://example.test/a.git").json() == {
        "ok": True
    }
    rows = client.get(f"{G}/remotes", params={"workspace": ws}).json()
    assert rows == [
        {
            "name": "origin",
            "fetch_url": "https://example.test/a.git",
            "push_url": "https://example.test/a.git",
        }
    ]
    assert request(
        client, "PUT", "remotes", workspace=ws, name="origin", url="ssh://example.test/b.git"
    ).json() == {"ok": True}
    assert client.get(f"{G}/remotes", params={"workspace": ws}).json()[0]["fetch_url"] == (
        "ssh://example.test/b.git"
    )
    assert request(client, "DELETE", "remotes", workspace=ws, name="origin").json() == {"ok": True}
    assert client.get(f"{G}/remotes", params={"workspace": ws}).json() == []


def test_remote_name_and_url_validation(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    for name in ["", "-x", "a b", "HEAD", "a..b", "x.lock"]:
        response = post(client, "remotes", workspace=ws, name=name, url="https://example.test/a.git")
        assert response.status_code == 422, name
        assert response.json() == {"detail": f"Invalid remote name: {name}"}
    cases = {
        " ": "Invalid remote URL",
        "-oProxyCommand=x": "Invalid remote URL",
        "https://example.test/a\n.git": "Invalid remote URL",
        "ext::sh -c id": "Git remote helpers are not allowed.",
        "https://user:pw@example.test/a.git": "Store remote credentials in a Git server connection, not the URL.",
        "ftp://example.test/a.git": "Unsupported Git remote protocol: ftp",
        "ext://x/y": "Unsupported Git remote protocol: ext",
    }
    for url, detail in cases.items():
        response = post(client, "remotes", workspace=ws, name="origin", url=url)
        if url == " ":
            # the schema's min_length counts the blank, the route then strips it
            assert response.status_code == 422
            assert response.json() == {"detail": detail}
            continue
        assert response.status_code == 422, url
        assert response.json() == {"detail": detail}, url
    assert client.get(f"{G}/remotes", params={"workspace": ws}).json() == []
    # accepted forms: scp-like, file, git, a Windows drive path
    for url in ["git@example.test:o/r.git", "file:///tmp/x", "git://example.test/x", "C:/some/where"]:
        assert post(client, "remotes", workspace=ws, name="o", url=url).status_code == 200, url
        request(client, "DELETE", "remotes", workspace=ws, name="o")


def test_remote_errors_from_git(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    post(client, "remotes", workspace=ws, name="origin", url="https://example.test/a.git")
    duplicate = post(client, "remotes", workspace=ws, name="origin", url="https://example.test/b.git")
    assert duplicate.status_code == 502
    missing = request(client, "PUT", "remotes", workspace=ws, name="nope", url="https://example.test/x")
    assert missing.status_code == 502
    gone = request(client, "DELETE", "remotes", workspace=ws, name="nope")
    assert gone.status_code == 502


# ── log ───────────────────────────────────────────────────────────────────────


def test_log_entries_and_paging(client: httpx.Client, repo: Path) -> None:
    for index in range(3):
        commit_file(repo, f"f{index}.txt", "x\n", f"commit {index}")
    body = client.get(f"{G}/log", params={"workspace": str(repo), "limit": 2}).json()
    assert list(body) == ["entries", "has_more", "next_skip"]
    assert body["has_more"] is True and body["next_skip"] == 2
    assert [e["message"] for e in body["entries"]] == ["commit 2", "commit 1"]
    entry = body["entries"][0]
    assert list(entry) == ["sha", "short_sha", "parent_shas", "refs", "author", "date", "message"]
    assert entry["sha"] == sha(repo) and entry["short_sha"] == sha(repo)[:8]
    assert entry["parent_shas"] == [sha(repo, "HEAD~1")]
    assert entry["refs"] == ["HEAD -> main"]
    assert entry["author"] == "t"
    nxt = client.get(f"{G}/log", params={"workspace": str(repo), "limit": 10, "skip": 2}).json()
    assert [e["message"] for e in nxt["entries"]] == ["commit 0", "second", "first"]
    assert nxt["has_more"] is False and nxt["next_skip"] is None


def test_log_parameters_branch_path_all_and_clamping(client: httpx.Client, repo: Path) -> None:
    git(repo, "checkout", "-qb", "other")
    commit_file(repo, "o.txt", "o\n", "on other")
    git(repo, "checkout", "-q", "main")
    ws = str(repo)
    main = client.get(f"{G}/log", params={"workspace": ws}).json()
    assert [e["message"] for e in main["entries"]] == ["second", "first"]
    other = client.get(f"{G}/log", params={"workspace": ws, "branch": "other"}).json()
    assert other["entries"][0]["message"] == "on other"
    every = client.get(f"{G}/log", params={"workspace": ws, "all_branches": True}).json()
    assert {e["message"] for e in every["entries"]} == {"on other", "second", "first"}
    scoped = client.get(f"{G}/log", params={"workspace": ws, "path": "a.txt"}).json()
    assert [e["message"] for e in scoped["entries"]] == ["first"]
    one = client.get(f"{G}/log", params={"workspace": ws, "limit": 0}).json()
    assert len(one["entries"]) == 1 and one["has_more"] is True
    skipped = client.get(f"{G}/log", params={"workspace": ws, "skip": -4}).json()
    assert len(skipped["entries"]) == 2
    bad = client.get(f"{G}/log", params={"workspace": ws, "branch": "-x"})
    assert bad.status_code == 422 and bad.json() == {"detail": "Invalid ref name: -x"}
    unknown = client.get(f"{G}/log", params={"workspace": ws, "branch": "nope"}).json()
    assert unknown == {"entries": [], "has_more": False, "next_skip": None}


def test_log_of_an_empty_repository_is_empty(client: httpx.Client, folder: Path) -> None:
    git(folder, "init", "-q", "-b", "main")
    body = client.get(f"{G}/log", params={"workspace": str(folder)}).json()
    assert body == {"entries": [], "has_more": False, "next_skip": None}


def test_log_files_of_a_commit(client: httpx.Client, repo: Path) -> None:
    git(repo, "mv", "a.txt", "c.txt")
    (repo / "sub" / "b.txt").write_text("changed\n", encoding="utf-8", newline="")
    (repo / "added.txt").write_text("n\n", encoding="utf-8", newline="")
    git(repo, "rm", "-q", "--cached", "--", "sub/b.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "mixed")
    rows = client.get(f"{G}/log/{sha(repo)}/files", params={"workspace": str(repo)}).json()
    assert all(list(r) == ["path", "status"] for r in rows)
    statuses = {r["path"]: r["status"] for r in rows}
    assert statuses["added.txt"] == "A"
    assert any(s.startswith("R") for s in statuses.values())
    short = client.get(f"{G}/log/{sha(repo)[:7]}/files", params={"workspace": str(repo)})
    assert short.status_code == 200 and short.json() == rows


def test_log_files_validation(client: httpx.Client, repo: Path) -> None:
    for bad in ["xyz", "abc", "ABCDEF12", "HEAD", "a" * 65]:
        response = client.get(f"{G}/log/{bad}/files", params={"workspace": str(repo)})
        assert response.status_code == 422, bad
        assert response.json() == {"detail": f"Invalid SHA: {bad}"}
    unknown = client.get(f"{G}/log/{'0' * 12}/files", params={"workspace": str(repo)})
    assert unknown.status_code == 200 and unknown.json() == []


# ── stash ─────────────────────────────────────────────────────────────────────


def test_stash_create_list_apply_pop_and_drop(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    (repo / "a.txt").write_text("stashed\n", encoding="utf-8", newline="")
    assert post(client, "stash", workspace=ws, message="wip a").json() == {"ok": True}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    rows = client.get(f"{G}/stash", params={"workspace": ws}).json()
    assert len(rows) == 1 and list(rows[0]) == ["index", "message", "sha"]
    assert rows[0]["index"] == 0 and rows[0]["message"].endswith("wip a") and len(rows[0]["sha"]) == 8
    applied = post(client, "stash/apply", workspace=ws, index=0).json()
    assert applied["success"] is True and applied["conflicts"] == []
    assert (repo / "a.txt").read_text(encoding="utf-8") == "stashed\n"
    assert len(client.get(f"{G}/stash", params={"workspace": ws}).json()) == 1
    git(repo, "checkout", "--", "a.txt")
    popped = post(client, "stash/pop", workspace=ws, index=0).json()
    assert popped["success"] is True
    assert client.get(f"{G}/stash", params={"workspace": ws}).json() == []
    (repo / "a.txt").write_text("again\n", encoding="utf-8", newline="")
    post(client, "stash", workspace=ws)
    assert request(client, "DELETE", "stash", workspace=ws, index=0).json() == {"ok": True}
    assert client.get(f"{G}/stash", params={"workspace": ws}).json() == []


def test_stash_with_nothing_to_stash_and_include_untracked(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    # ``git stash push`` with no local change succeeds without creating an entry
    assert post(client, "stash", workspace=ws).json() == {"ok": True}
    assert client.get(f"{G}/stash", params={"workspace": ws}).json() == []
    (repo / "u.txt").write_text("u\n", encoding="utf-8", newline="")
    post(client, "stash", workspace=ws)
    assert (repo / "u.txt").exists() and client.get(f"{G}/stash", params={"workspace": ws}).json() == []
    post(client, "stash", workspace=ws, include_untracked=True)
    assert not (repo / "u.txt").exists()
    assert len(client.get(f"{G}/stash", params={"workspace": ws}).json()) == 1


def test_stash_errors_for_an_unknown_index(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    for method, path in [("POST", "stash/apply"), ("POST", "stash/pop"), ("DELETE", "stash")]:
        response = request(client, method, path, workspace=ws, index=5)
        if path == "stash":
            assert response.status_code == 502
        else:
            # apply and pop report the failure in the body, not as a status
            assert response.status_code == 200, path
            body = response.json()
            assert body["success"] is False and body["conflicts"] == [] and body["message"]


def test_stash_apply_that_conflicts_reports_the_files(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    (repo / "a.txt").write_text("stashed\n", encoding="utf-8", newline="")
    post(client, "stash", workspace=ws)
    commit_file(repo, "a.txt", "committed\n", "diverge")
    body = post(client, "stash/apply", workspace=ws, index=0).json()
    assert body["success"] is False
    assert body["conflicts"] == ["a.txt"]
    assert len(client.get(f"{G}/stash", params={"workspace": ws}).json()) == 1


# ── merge, rebase, cherry-pick, revert ────────────────────────────────────────


def test_merge_fast_forward_and_validation(client: httpx.Client, repo: Path) -> None:
    git(repo, "checkout", "-qb", "feat")
    commit_file(repo, "f.txt", "f\n", "feat commit")
    git(repo, "checkout", "-q", "main")
    body = post(client, "merge", workspace=str(repo), branch="feat").json()
    assert body["success"] is True and body["conflicts"] == []
    assert "Fast-forward" in body["message"]
    assert (repo / "f.txt").exists()
    invalid = post(client, "merge", workspace=str(repo), branch="-x")
    assert invalid.status_code == 422 and invalid.json() == {"detail": "Invalid ref name: -x"}
    unknown = post(client, "merge", workspace=str(repo), branch="nope").json()
    assert unknown["success"] is False and unknown["conflicts"] == [] and unknown["message"]


def test_merge_conflict_continue_and_abort(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    conflicted_repo(repo)
    body = post(client, "merge", workspace=ws, branch="other").json()
    assert body["success"] is False and body["conflicts"] == ["a.txt"]
    state = client.get(f"{G}/conflicts", params={"workspace": ws}).json()
    assert state == {
        "conflicted": True,
        "operation": "merge",
        "files": [{"path": "a.txt", "status": "both modified"}],
    }
    files = {f["path"]: f for f in client.get(f"{G}/changes", params={"workspace": ws}).json()["files"]}
    assert files["a.txt"]["status"] == "both modified"
    # continue with an unresolved conflict is git's error
    refused = post(client, "continue", workspace=ws)
    assert refused.status_code == 502
    assert post(client, "abort", workspace=ws).json() == {"ok": True}
    assert client.get(f"{G}/conflicts", params={"workspace": ws}).json() == {
        "conflicted": False,
        "operation": None,
        "files": [],
    }
    assert (repo / "a.txt").read_text(encoding="utf-8") == "from main\n"
    # ``continue`` after resolving runs ``git merge --continue`` with no editor configured and
    # can wait for one until the 60 s timeout, so it is not exercised here (NOTES B9)


def test_continue_and_abort_without_an_operation(client: httpx.Client, repo: Path) -> None:
    for path in ("continue", "abort"):
        response = post(client, path, workspace=str(repo))
        assert response.status_code == 422
        assert response.json() == {"detail": "No in-progress operation found"}
    assert client.get(f"{G}/conflicts", params={"workspace": str(repo)}).json()["conflicted"] is False


def test_rebase_onto_a_branch_and_with_a_conflict(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    git(repo, "checkout", "-qb", "topic")
    commit_file(repo, "t.txt", "t\n", "topic commit")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "main commit")
    git(repo, "checkout", "-q", "topic")
    ok = post(client, "rebase", workspace=ws, onto="main").json()
    assert ok["success"] is True and ok["conflicts"] == []
    assert git(repo, "log", "--format=%s", "-3").split("\n")[:2] == ["topic commit", "main commit"]
    assert post(client, "rebase", workspace=ws, onto="-x").status_code == 422
    # a conflicting rebase stops in the middle
    git(repo, "checkout", "-qb", "clash", "main")
    commit_file(repo, "m.txt", "clash\n", "clash commit")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "m.txt", "main again\n", "main second")
    git(repo, "checkout", "-q", "clash")
    body = post(client, "rebase", workspace=ws, onto="main").json()
    assert body["success"] is False and body["conflicts"] == ["m.txt"]
    assert client.get(f"{G}/conflicts", params={"workspace": ws}).json()["operation"] == "rebase"
    assert post(client, "abort", workspace=ws).json() == {"ok": True}
    assert head_branch(repo) == "clash"


def test_cherry_pick_and_revert(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    git(repo, "checkout", "-qb", "side")
    picked = commit_file(repo, "p.txt", "p\n", "side commit")
    git(repo, "checkout", "-q", "main")
    body = post(client, "cherry-pick", workspace=ws, shas=[picked]).json()
    assert body["success"] is True and body["conflicts"] == []
    assert (repo / "p.txt").exists()
    reverted = post(client, "revert", workspace=ws, sha=sha(repo)).json()
    assert reverted["success"] is True
    assert not (repo / "p.txt").exists()
    assert git(repo, "log", "-1", "--format=%s").strip().startswith('Revert "side commit"')


def test_cherry_pick_and_revert_validation_and_conflicts(client: httpx.Client, repo: Path) -> None:
    ws = str(repo)
    for bad in ["xyz", "abc", "HEAD", "-n"]:
        a = post(client, "cherry-pick", workspace=ws, shas=[bad])
        assert a.status_code == 422 and a.json() == {"detail": f"Invalid SHA: {bad}"}, bad
        b = post(client, "revert", workspace=ws, sha=bad)
        assert b.status_code == 422 and b.json() == {"detail": f"Invalid SHA: {bad}"}, bad
    nothing = post(client, "cherry-pick", workspace=ws, shas=[])
    assert nothing.status_code == 200 and nothing.json()["success"] is False  # git refuses an empty cherry-pick
    git(repo, "checkout", "-qb", "side")
    side = commit_file(repo, "a.txt", "side\n", "side a")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "a.txt", "main\n", "main a")
    clash = post(client, "cherry-pick", workspace=ws, shas=[side]).json()
    assert clash["success"] is False and clash["conflicts"] == ["a.txt"]
    state = client.get(f"{G}/conflicts", params={"workspace": ws}).json()
    assert state["operation"] == "cherry-pick"
    assert post(client, "abort", workspace=ws).json() == {"ok": True}
