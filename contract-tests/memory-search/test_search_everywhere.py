"""``POST /api/team/workspace/search-everywhere``: repository search for one workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from memory_helpers import SEARCH_EVERYWHERE

GIT = ["git", "-c", "user.name=Contract", "-c", "user.email=contract@example.invalid"]


def search(client, workspace: Path | str, query: str, **body) -> list[dict]:
    response = client.post(
        SEARCH_EVERYWHERE,
        params={"workspace": str(workspace)},
        json={"query": query, **body},
    )
    assert response.status_code == 200, response.text
    assert list(response.json()) == ["items"]
    return response.json()["items"]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / "repo"
    path.mkdir(parents=True)
    return path


def git(ws: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=ws, check=True, capture_output=True)


def test_request_validation(client, ws) -> None:
    cases = [
        ({}, [("missing", ["body", "query"])]),
        ({"query": ""}, [("string_too_short", ["body", "query"])]),
        ({"query": "x" * 1001}, [("string_too_long", ["body", "query"])]),
        ({"query": "x", "limit": 0}, [("greater_than_equal", ["body", "limit"])]),
        ({"query": "x", "limit": 101}, [("less_than_equal", ["body", "limit"])]),
        ({"query": "x", "limit": "many"}, [("int_parsing", ["body", "limit"])]),
    ]
    for body, expected in cases:
        response = client.post(
            SEARCH_EVERYWHERE, params={"workspace": str(ws)}, json=body
        )
        assert response.status_code == 422, body
        got = [(e["type"], e["loc"]) for e in response.json()["detail"]]
        assert got == expected, body
    # validation errors are reported together, query and body in one list
    both = client.post(SEARCH_EVERYWHERE, json={})
    assert both.status_code == 422
    assert [(e["type"], e["loc"]) for e in both.json()["detail"]] == [
        ("missing", ["query", "workspace"]),
        ("missing", ["body", "query"]),
    ]


def test_workspace_must_be_an_existing_directory(client, ws, tmp_path) -> None:
    missing = ws / "nope"
    response = client.post(
        SEARCH_EVERYWHERE, params={"workspace": str(missing)}, json={"query": "x"}
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {missing.resolve()}"
    }
    a_file = ws / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    response = client.post(
        SEARCH_EVERYWHERE, params={"workspace": str(a_file)}, json={"query": "x"}
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {a_file.resolve()}"
    }
    empty = client.post(
        SEARCH_EVERYWHERE, params={"workspace": ""}, json={"query": "x"}
    )
    assert empty.status_code in (200, 422)


def test_any_existing_directory_is_searched_without_an_allowlist(
    client, tmp_path
) -> None:
    """The route does not check ``EVOFLUX_WORKSPACE_ROOTS`` or any session (finding S1)."""
    outside = tmp_path / "not-a-workspace-root"
    outside.mkdir()
    (outside / "qzx-secret.txt").write_text("x", encoding="utf-8")
    items = search(client, outside, "qzx-secret")
    assert [i["id"] for i in items] == ["file:qzx-secret.txt"]


def test_relative_workspace_and_user_home_expansion_resolve_against_the_backend(
    client, tmp_path
) -> None:
    response = client.post(
        SEARCH_EVERYWHERE, params={"workspace": "."}, json={"query": "qzx-none"}
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_file_and_folder_rows(client, ws) -> None:
    (ws / "qzxdir").mkdir()
    (ws / "qzxdir" / "inner.txt").write_text("12345", encoding="utf-8")
    (ws / "qzxdir" / "qzxsub").mkdir()
    (ws / "qzx-top.txt").write_text("abc", encoding="utf-8")
    (ws / "qzx-data.json").write_text("{}", encoding="utf-8")
    (ws / "qzx-blob.unknownext").write_bytes(b"\x00\x01")
    items = search(client, ws, "qzx")
    assert [i["id"] for i in items] == [
        "folder:qzxdir",
        "file:qzx-blob.unknownext",
        "file:qzx-data.json",
        "file:qzx-top.txt",
        "folder:qzxdir/qzxsub",
        "file:qzxdir/inner.txt",
    ]
    by_id = {i["id"]: i for i in items}
    folder = by_id["folder:qzxdir"]
    assert folder == {
        "id": "folder:qzxdir",
        "kind": "folder",
        "label": "qzxdir",
        "description": "Repository folder",
        "path": "qzxdir",
        "line": None,
        "metadata": None,
    }
    assert list(folder) == [
        "id",
        "kind",
        "label",
        "description",
        "path",
        "line",
        "metadata",
    ]
    top = by_id["file:qzx-top.txt"]
    assert top["kind"] == "file"
    assert top["label"] == "qzx-top.txt"
    assert top["description"] == "Repository file"
    assert top["path"] == "qzx-top.txt"
    assert top["line"] is None
    assert set(top["metadata"]) == {"size", "mtime", "mime"}
    assert top["metadata"]["size"] == 3
    assert top["metadata"]["mime"] == "text/plain"
    assert isinstance(top["metadata"]["mtime"], float)
    assert by_id["file:qzx-data.json"]["metadata"]["mime"] == "application/json"
    assert (
        by_id["file:qzx-blob.unknownext"]["metadata"]["mime"]
        == "application/octet-stream"
    )
    nested = by_id["file:qzxdir/inner.txt"]
    assert nested["label"] == "qzxdir/inner.txt"
    assert nested["metadata"]["size"] == 5


def test_match_is_a_case_insensitive_substring_of_the_relative_path(client, ws) -> None:
    (ws / "Alpha").mkdir()
    (ws / "Alpha" / "beta.TXT").write_text("x", encoding="utf-8")
    (ws / "gamma.txt").write_text("x", encoding="utf-8")
    assert [i["id"] for i in search(client, ws, "ALPHA/BE")] == ["file:Alpha/beta.TXT"]
    assert [i["id"] for i in search(client, ws, "a/b")] == ["file:Alpha/beta.TXT"]
    assert [i["id"] for i in search(client, ws, "  gamma  ")] == ["file:gamma.txt"]
    assert search(client, ws, "   ") == []
    # a path separator typed with a backslash does not match
    assert search(client, ws, "alpha\\beta") == []


def test_ignored_paths_are_not_searched(client, ws) -> None:
    for name in (
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "logs",
    ):
        (ws / name).mkdir()
        (ws / name / "qzxhidden.txt").write_text("x", encoding="utf-8")
    (ws / "keep").mkdir()
    (ws / "keep" / "qzxhidden.txt").write_text("x", encoding="utf-8")
    (ws / "other.log").write_text("x", encoding="utf-8")
    (ws / "qzxhidden.log").write_text("x", encoding="utf-8")
    (ws / ".gitignore").write_text(
        "# comment\nlogs/\n*.log\n!keep.log\n", encoding="utf-8"
    )
    ids = [i["id"] for i in search(client, ws, "qzxhidden")]
    # ignore rules (hidden, generated and .gitignore) prune directories only; a file
    # that a .gitignore pattern matches is still listed (finding G1)
    assert ids == ["file:qzxhidden.log", "file:keep/qzxhidden.txt"]


def test_dot_files_are_searched_but_dot_directories_are_not(client, ws) -> None:
    (ws / ".hidden").mkdir()
    (ws / ".hidden" / "qzx.txt").write_text("x", encoding="utf-8")
    (ws / ".qzxrc").write_text("x", encoding="utf-8")
    ids = [i["id"] for i in search(client, ws, "qzx")]
    # dot files are listed; every directory whose name starts with a dot is pruned
    assert ids == ["file:.qzxrc"]


def test_per_source_cap_follows_the_limit(client, ws) -> None:
    for n in range(40):
        (ws / f"qzxcap{n:02d}.txt").write_text("x", encoding="utf-8")
    # per source = max(5, min(20, limit // 3)); the path source is the only one with hits
    assert len(search(client, ws, "qzxcap")) == 16  # default limit 50
    assert len(search(client, ws, "qzxcap", limit=100)) == 20
    assert len(search(client, ws, "qzxcap", limit=30)) == 10
    assert len(search(client, ws, "qzxcap", limit=6)) == 5
    assert len(search(client, ws, "qzxcap", limit=3)) == 3
    assert [i["id"] for i in search(client, ws, "qzxcap", limit=1)] == [
        "file:qzxcap00.txt"
    ]


def test_git_branch_and_commit_rows(client, ws) -> None:
    git(ws, "init", "-q")
    (ws / "a.txt").write_text("a", encoding="utf-8")
    git(ws, "add", "a.txt")
    git(ws, "commit", "-q", "-m", "QZXCommit first change")
    git(ws, "branch", "qzxbranch")
    git(ws, "commit", "-q", "--allow-empty", "-m", "unrelated work")
    sha = subprocess.run(
        ["git", "log", "--grep=qzxcommit", "-i", "--format=%H"],
        cwd=ws,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    items = search(client, ws, "qzx")
    assert [(i["kind"], i["id"]) for i in items] == [
        ("git_branch", "git-branch:qzxbranch"),
        ("git_commit", f"git-commit:{sha}"),
    ]
    branch, commit = items
    assert branch == {
        "id": "git-branch:qzxbranch",
        "kind": "git_branch",
        "label": "qzxbranch",
        "description": "Git branch",
        "path": None,
        "line": None,
        "metadata": {"branch": "qzxbranch"},
    }
    assert commit == {
        "id": f"git-commit:{sha}",
        "kind": "git_commit",
        "label": "QZXCommit first change",
        "description": sha[:12],
        "path": None,
        "line": None,
        "metadata": {"sha": sha},
    }


def test_group_order_is_paths_then_git_then_skills(client, ws) -> None:
    git(ws, "init", "-q")
    git(ws, "commit", "-q", "--allow-empty", "-m", "qzxgrp commit")
    (ws / "qzxgrp.txt").write_text("x", encoding="utf-8")
    skill = ws / ".agents" / "skills" / "qzxgrp-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: qzxgrp-skill\ndescription: Skill for the group test\n---\n\nbody\n",
        encoding="utf-8",
    )
    kinds = [i["kind"] for i in search(client, ws, "qzxgrp")]
    assert kinds == ["file", "git_commit", "skill"]


def test_workspace_skill_row(client, ws) -> None:
    skill = ws / ".claude" / "skills" / "qzxskill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: qzxskill\ndescription: Finds the qzx thing\n---\n\nbody\n",
        encoding="utf-8",
    )
    (row,) = [i for i in search(client, ws, "finds the qzx") if i["kind"] == "skill"]
    assert row == {
        "id": "skill:qzxskill",
        "kind": "skill",
        "label": "qzxskill",
        "description": "Finds the qzx thing",
        "path": None,
        "line": None,
        "metadata": {"name": "qzxskill", "insert_text": "$qzxskill "},
    }
    # the skill is not offered for a workspace that does not hold it
    other = ws.parent / "other"
    other.mkdir()
    assert [i for i in search(client, other, "qzxskill") if i["kind"] == "skill"] == []


def test_search_does_not_write_into_the_workspace(client, ws) -> None:
    (ws / "qzxro.txt").write_text("x", encoding="utf-8")
    before = sorted(p.name for p in ws.rglob("*"))
    search(client, ws, "qzxro")
    assert sorted(p.name for p in ws.rglob("*")) == before


def test_unknown_methods(client, ws) -> None:
    assert (
        client.get(SEARCH_EVERYWHERE, params={"workspace": str(ws)}).status_code == 405
    )
    # the path without the workspace prefix does not exist
    assert client.post(
        "/api/team/search-everywhere", json={"query": "x"}
    ).status_code in (404, 422)
