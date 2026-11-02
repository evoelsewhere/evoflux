"""``/api/team/workspace/{change-sets,problems,editor}`` and ``/workspace/git/ai`` (checks that need no model)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import httpx

T = "/api/team/workspace"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create(client: httpx.Client, root: Path, files: list[dict], **extra) -> httpx.Response:
    body = {"origin": "ai", "title": "T", "files": files, **extra}
    return client.post(f"{T}/change-sets", params={"workspace": str(root)}, json=body)


def proposal(path: str, content: str, base: str | None = None) -> dict:
    item = {"path": path, "proposed_content": content}
    if base is not None:
        item["base_hash"] = base
    return item


# ── change sets ───────────────────────────────────────────────────────────────


def test_create_get_and_read_a_proposed_file(client: httpx.Client, repo: Path) -> None:
    response = create(client, repo, [proposal("a.txt", "new\n", sha256("one\n")), proposal("sub/new.txt", "n\n")])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending" and body["origin"] == "ai" and body["title"] == "T"
    assert [f["path"] for f in body["files"]] == ["a.txt", "sub/new.txt"]
    first = body["files"][0]
    assert first["status"] == "pending" and first["base_hash"] == sha256("one\n")
    assert first["proposed_hash"] == sha256("new\n")
    assert (first["additions"], first["deletions"]) == (1, 1)
    assert "-one" in first["diff"] and "+new" in first["diff"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"  # nothing is written yet
    got = client.get(f"{T}/change-sets/{body['id']}", params={"workspace": str(repo)})
    assert got.status_code == 200 and got.json() == body
    content = client.get(f"{T}/change-sets/{body['id']}/files/a.txt", params={"workspace": str(repo)})
    assert content.status_code == 200, content.text
    detail = content.json()
    assert (detail["original_content"], detail["proposed_content"]) == ("one\n", "new\n")


def test_apply_writes_the_selected_files_and_marks_the_status(client: httpx.Client, repo: Path) -> None:
    body = create(client, repo, [proposal("a.txt", "new\n", sha256("one\n")), proposal("extra.txt", "x\n")]).json()
    applied = client.post(
        f"{T}/change-sets/{body['id']}/apply",
        params={"workspace": str(repo)},
        json={"paths": ["a.txt"], "verify": False},
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["status"] == "partial"
    assert {f["path"]: f["status"] for f in result["files"]} == {"a.txt": "applied", "extra.txt": "pending"}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "new\n"
    assert not (repo / "extra.txt").exists()
    rest = client.post(
        f"{T}/change-sets/{body['id']}/apply", params={"workspace": str(repo)}, json={"verify": False}
    ).json()
    assert rest["status"] == "applied"
    assert (repo / "extra.txt").read_text(encoding="utf-8") == "x\n"
    again = client.post(
        f"{T}/change-sets/{body['id']}/apply", params={"workspace": str(repo)}, json={"verify": False}
    )
    assert again.status_code == 422
    assert again.json() == {"detail": "No pending files selected for apply."}


def test_a_file_changed_since_the_proposal_is_stale(client: httpx.Client, repo: Path) -> None:
    stale = create(client, repo, [proposal("a.txt", "new\n", sha256("other content\n"))])
    assert stale.status_code == 409
    assert stale.json() == {"detail": {"code": "stale_change_set", "paths": ["a.txt"]}}
    body = create(client, repo, [proposal("a.txt", "new\n", sha256("one\n"))]).json()
    (repo / "a.txt").write_text("edited meanwhile\n", encoding="utf-8", newline="")
    applied = client.post(
        f"{T}/change-sets/{body['id']}/apply", params={"workspace": str(repo)}, json={"verify": False}
    )
    assert applied.status_code == 409
    assert applied.json() == {"detail": {"code": "stale_change_set", "paths": ["a.txt"]}}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "edited meanwhile\n"


def test_reject_leaves_the_files_alone(client: httpx.Client, repo: Path) -> None:
    body = create(client, repo, [proposal("a.txt", "new\n")]).json()
    rejected = client.post(
        f"{T}/change-sets/{body['id']}/reject", params={"workspace": str(repo)}, json={}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    again = client.post(f"{T}/change-sets/{body['id']}/reject", params={"workspace": str(repo)}, json={})
    assert again.status_code == 422
    assert again.json() == {"detail": "No pending files selected for rejection."}


def test_change_set_paths_cannot_leave_the_repository(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    for bad, detail in [
        ("../outside.txt", "ChangeSet path escapes the repository."),
        (str(outside), "ChangeSet paths must be repository-relative."),
        ("sub/../../outside.txt", "ChangeSet path escapes the repository."),
        (".", "ChangeSet path cannot be the repository root."),
    ]:
        response = create(client, repo, [proposal(bad, "x\n")])
        assert response.status_code == 422, bad
        assert response.json() == {"detail": detail}, bad
    assert not outside.exists()


def test_change_set_create_validation(client: httpx.Client, repo: Path) -> None:
    empty = create(client, repo, [])
    assert empty.status_code == 422
    assert empty.json() == {"detail": "A ChangeSet requires at least one file proposal."}
    duplicate = create(client, repo, [proposal("a.txt", "1\n"), proposal("./a.txt", "2\n")])
    assert duplicate.status_code == 422
    assert duplicate.json() == {"detail": "Duplicate file proposal: a.txt"}
    for body in [
        {"origin": "nope", "title": "T", "files": []},
        {"origin": "ai", "title": "", "files": []},
        {"origin": "ai", "title": "T", "files": [{"path": "", "proposed_content": ""}]},
        {"origin": "ai", "title": "T", "files": [{"path": "a", "proposed_content": "", "base_hash": "short"}]},
    ]:
        response = client.post(f"{T}/change-sets", params={"workspace": str(repo)}, json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)


def test_unknown_change_sets_and_other_workspaces(client: httpx.Client, repo: Path, folder: Path) -> None:
    missing = client.get(f"{T}/change-sets/{uuid.uuid4().hex}", params={"workspace": str(repo)})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "ChangeSet not found or expired."}
    body = create(client, repo, [proposal("a.txt", "new\n")]).json()
    other = client.get(f"{T}/change-sets/{body['id']}", params={"workspace": str(folder)})
    assert other.status_code == 404
    gone = client.get(f"{T}/change-sets/{body['id']}/files/nope.txt", params={"workspace": str(repo)})
    assert gone.status_code == 404
    assert gone.json() == {"detail": "ChangeSet file not found."}
    bad_workspace = client.get(f"{T}/change-sets/{body['id']}", params={"workspace": str(folder / "nope")})
    assert bad_workspace.status_code == 422
    assert bad_workspace.json()["detail"].startswith("Workspace does not exist or is not a directory: ")


# ── problems ──────────────────────────────────────────────────────────────────


def test_problems_of_a_clean_workspace(client: httpx.Client, folder: Path) -> None:
    response = client.get(f"{T}/problems", params={"workspace": str(folder), "refresh_plugins": False})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "problems": [],
        "counts": {"error": 0, "warning": 0, "info": 0, "hint": 0, "total": 0},
    }


def test_problems_need_at_least_one_valid_workspace(client: httpx.Client, folder: Path, tmp_path: Path) -> None:
    missing = client.get(f"{T}/problems")
    assert missing.status_code == 422 and missing.json()["detail"][0]["loc"] == ["query", "workspace"]
    gone = client.get(f"{T}/problems", params={"workspace": str(tmp_path / "nope")})
    assert gone.status_code == 422
    assert gone.json()["detail"].startswith("Workspace does not exist or is not a directory: ")
    two = client.get(
        f"{T}/problems",
        params={"workspace": [str(folder), str(folder)], "refresh_plugins": False},
    )
    assert two.status_code == 200 and two.json()["counts"]["total"] == 0


def test_problem_actions_on_an_unknown_problem_are_404(client: httpx.Client, folder: Path) -> None:
    for action in ["dismiss", "suppress", "restore"]:
        response = client.post(f"{T}/problems/nope/{action}", params={"workspace": str(folder)})
        assert response.status_code == 404, action
        assert response.json()["detail"]
    gone = client.post(f"{T}/problems/nope/dismiss", params={"workspace": str(folder / "nope")})
    assert gone.status_code == 422


# ── editor and git AI: the refusals that come before any model call ───────────


def test_editor_context_refuses_files_outside_the_workspace(client: httpx.Client, folder: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    for active in ["../secret.txt", str(tmp_path / "secret.txt")]:
        response = client.post(
            f"{T}/editor/context",
            params={"workspace": str(folder)},
            json={"active_file": active},
        )
        assert response.status_code == 422, active
        assert "SECRET" not in response.text


def test_editor_action_checks_the_session_before_anything_else(client: httpx.Client, folder: Path) -> None:
    ws = {"workspace": str(folder)}
    no_session = client.post(f"{T}/editor/action", params=ws, json={"action": "fix_diagnostic"})
    assert no_session.status_code in (422,)
    bad = client.post(
        f"{T}/editor/action", params=ws, json={"action": "fix_diagnostic", "session_id": "nope"}
    )
    assert bad.status_code == 422
    unknown = client.post(
        f"{T}/editor/action",
        params=ws,
        json={"action": "fix_diagnostic", "session_id": str(uuid.uuid4())},
    )
    assert unknown.status_code in (404, 422)


def test_git_ai_checks_the_session_before_any_model_call(client: httpx.Client, repo: Path) -> None:
    ws = {"workspace": str(repo)}
    bad_id = client.post(f"{T}/git/ai", params=ws, json={"session_id": "nope", "action": "self_review"})
    assert bad_id.status_code == 422
    unknown = client.post(
        f"{T}/git/ai", params=ws, json={"session_id": str(uuid.uuid4()), "action": "self_review"}
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Coding session not found."}
    action = client.post(f"{T}/git/ai", params=ws, json={"session_id": str(uuid.uuid4()), "action": "nope"})
    assert action.status_code == 422 and isinstance(action.json()["detail"], list)
