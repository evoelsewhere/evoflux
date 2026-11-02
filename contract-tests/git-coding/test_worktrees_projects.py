"""``/api/team/workspace/worktrees`` and ``/api/team/projects`` (and the tree they feed)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from gc_helpers import commit_file, git, same_path, sha

T = "/api/team"
WT = f"{T}/workspace/worktrees"


def create_worktree(client: httpx.Client, repo: Path, **body) -> httpx.Response:
    return client.post(WT, json={"source_workspace": str(repo), **body})


def listed(client: httpx.Client, repo: Path) -> list[dict]:
    response = client.get(WT, params={"source_workspace": str(repo)})
    assert response.status_code == 200, response.text
    return response.json()


# ── worktrees ─────────────────────────────────────────────────────────────────


def test_create_a_worktree_with_a_generated_name_and_branch(client: httpx.Client, repo: Path) -> None:
    response = create_worktree(client, repo)
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["name", "directory", "branch", "managed", "source_workspace"]
    assert body["name"] == "session" and body["branch"] == "EvoFlux/session" and body["managed"] is True
    assert same_path(body["source_workspace"], repo)
    directory = Path(body["directory"])
    assert directory.is_dir() and (directory / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert sha(directory) == sha(repo)
    assert git(directory, "symbolic-ref", "--short", "HEAD").strip() == "EvoFlux/session"
    # the default root is inside the repository and locally ignored
    assert same_path(directory.parent, repo / ".evoflux" / "worktrees")
    status = git(repo, "status", "--porcelain")
    assert ".evoflux" not in status


def test_worktree_names_are_slugged_and_made_unique(client: httpx.Client, repo: Path) -> None:
    first = create_worktree(client, repo, name="My Feature!").json()
    assert first["name"] == "my-feature" and first["branch"] == "EvoFlux/my-feature"
    second = create_worktree(client, repo, name="my feature").json()
    assert second["name"] == "my-feature-1" and second["branch"] == "EvoFlux/my-feature-1"
    third = create_worktree(client, repo, name="my-feature", branch="custom").json()
    assert third["name"] == "my-feature-2" and third["branch"] == "custom-2"
    blank = create_worktree(client, repo, name="   ").json()
    assert blank["name"] == "session"


def test_a_detached_worktree_has_no_branch(client: httpx.Client, repo: Path) -> None:
    body = create_worktree(client, repo, name="det", detached=True, branch="ignored").json()
    assert body["branch"] is None
    assert git(Path(body["directory"]), "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"
    rows = listed(client, repo)
    assert [r["branch"] for r in rows] == [None]


def test_worktree_listing_excludes_the_source_and_marks_managed(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    created = create_worktree(client, repo, name="one").json()
    outside = tmp_path / "elsewhere"
    git(repo, "worktree", "add", "-q", "-b", "outside", str(outside))
    rows = {r["name"]: r for r in listed(client, repo)}
    assert set(rows) == {"one", "elsewhere"}
    assert list(rows["one"]) == ["name", "directory", "branch", "managed"]
    assert rows["one"]["managed"] is True and rows["one"]["branch"] == "EvoFlux/one"
    assert same_path(rows["one"]["directory"], created["directory"])
    assert rows["elsewhere"]["managed"] is False and rows["elsewhere"]["branch"] == "outside"


def test_worktree_create_validation(client: httpx.Client, repo: Path, folder: Path) -> None:
    for branch in ["-x", "a b", "a..b", "x.lock"]:
        response = create_worktree(client, repo, name="v", branch=branch)
        assert response.status_code == 422, branch
        assert response.json() == {"detail": "Invalid branch name."}
    not_git = create_worktree(client, folder)
    assert not_git.status_code == 422
    assert not_git.json() == {"detail": "Worktrees are only supported for git projects."}
    missing = client.post(WT, json={"source_workspace": str(folder / "nope")})
    assert missing.status_code == 422
    assert missing.json()["detail"].startswith("Workspace does not exist or is not a directory: ")
    long_name = create_worktree(client, repo, name="x" * 81)
    assert long_name.status_code == 422 and long_name.json()["detail"][0]["type"] == "string_too_long"
    assert client.post(WT, json={}).status_code == 422


def test_listing_a_folder_that_is_not_a_repository_is_a_422(client: httpx.Client, folder: Path) -> None:
    response = client.get(WT, params={"source_workspace": str(folder)})
    assert response.status_code == 422
    assert response.json() == {"detail": "Worktrees are only supported for git projects."}


def test_remove_a_managed_worktree_deletes_its_directory_and_branch(client: httpx.Client, repo: Path) -> None:
    created = create_worktree(client, repo, name="gone").json()
    (Path(created["directory"]) / "dirty.txt").write_text("d\n", encoding="utf-8", newline="")
    response = client.request(
        "DELETE", WT, json={"source_workspace": str(repo), "directory": created["directory"]}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"removed": True}
    assert not Path(created["directory"]).exists()
    assert listed(client, repo) == []
    assert git(repo, "branch", "--list", "EvoFlux/gone").strip() == ""


def test_remove_keeps_a_branch_the_caller_named(client: httpx.Client, repo: Path) -> None:
    created = create_worktree(client, repo, name="keepme", branch="feature/keep").json()
    client.request("DELETE", WT, json={"source_workspace": str(repo), "directory": created["directory"]})
    assert git(repo, "branch", "--list", "feature/keep").strip() != ""


def test_remove_refuses_directories_that_are_not_managed(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    git(repo, "worktree", "add", "-q", "-b", "outside", str(outside))
    for directory in [str(outside), str(repo), str(tmp_path), str(repo / ".evoflux")]:
        response = client.request(
            "DELETE", WT, json={"source_workspace": str(repo), "directory": directory}
        )
        assert response.status_code == 403, directory
        assert response.json() == {"detail": "Only EvoFlux-managed worktrees can be removed."}
    assert outside.is_dir()
    assert (repo / "a.txt").exists()


def test_remove_of_an_unknown_directory_below_the_managed_root_is_a_no_op(client: httpx.Client, repo: Path) -> None:
    created = create_worktree(client, repo, name="probe").json()
    ghost = Path(created["directory"]).parent / "ghost"
    response = client.request("DELETE", WT, json={"source_workspace": str(repo), "directory": str(ghost)})
    assert response.status_code == 200 and response.json() == {"removed": True}
    assert not ghost.exists()
    # a path that climbs out of the managed root is resolved first, so it is refused
    sneaky = Path(created["directory"]).parent / ".." / ".." / "a.txt"
    refused = client.request("DELETE", WT, json={"source_workspace": str(repo), "directory": str(sneaky)})
    assert refused.status_code == 403
    assert (repo / "a.txt").exists()


def test_worktrees_show_up_under_their_repository_in_the_tree(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    created = create_worktree(client, repo, name="treewt").json()
    project = client.post(
        f"{T}/projects", json={"name": "P", "workspace_paths": [str(repo)]}
    )
    assert project.status_code == 201, project.text
    tree = client.get(f"{T}/workspace/tree").json()
    assert list(tree) == ["repositories", "projects"]
    repos = tree["repositories"]
    assert len(repos) == 1
    entry = repos[0]
    assert same_path(entry["path"], repo) and entry["name"] == "repo"
    assert entry["project_id"] == project.json()["id"]
    assert [w["name"] for w in entry["worktrees"]] == ["treewt"]
    assert entry["worktrees"][0]["managed"] is True
    assert same_path(entry["worktrees"][0]["path"], created["directory"])


# ── projects ──────────────────────────────────────────────────────────────────


def make_project(client: httpx.Client, *paths: Path, **extra) -> dict:
    response = client.post(
        f"{T}/projects",
        json={"name": "Proj", "workspace_paths": [str(p) for p in paths], **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_get_list_and_shape(client: httpx.Client, repo: Path, folder: Path) -> None:
    body = make_project(client, repo, folder, description="d", settings={"k": 1})
    assert list(body) == ["id", "name", "description", "settings", "kind", "workspaces", "created_at", "updated_at"]
    assert body["name"] == "Proj" and body["description"] == "d" and body["settings"] == {"k": 1}
    assert body["kind"] == "coding"
    assert [w["name"] for w in body["workspaces"]] == ["repo", "plain"]
    item = body["workspaces"][0]
    assert list(item) == ["workspace_id", "path", "name", "display_name", "sort_order", "kind"]
    assert item["kind"] == "repo" and item["display_name"] is None and item["sort_order"] == 0
    assert [w["sort_order"] for w in body["workspaces"]] == [0, 1]
    uuid.UUID(body["id"])
    assert client.get(f"{T}/projects/{body['id']}").json() == body
    listed_projects = client.get(f"{T}/projects").json()
    assert [p["id"] for p in listed_projects] == [body["id"]]
    assert client.get(f"{T}/projects", params={"kind": "coding"}).json() == listed_projects
    assert client.get(f"{T}/projects", params={"kind": "work"}).json() == []


def test_create_validation(client: httpx.Client, repo: Path, tmp_path: Path) -> None:
    gone = tmp_path / "nope"
    bad_path = client.post(f"{T}/projects", json={"name": "P", "workspace_paths": [str(repo), str(gone)]})
    assert bad_path.status_code == 422
    assert bad_path.json()["detail"].startswith("Workspace does not exist or is not a directory: ")
    for body in [
        {"name": "", "workspace_paths": [str(repo)]},
        {"name": "x" * 256, "workspace_paths": [str(repo)]},
        {"name": "P", "workspace_paths": []},
        {"name": "P"},
        {"workspace_paths": [str(repo)]},
    ]:
        response = client.post(f"{T}/projects", json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)
    assert client.get(f"{T}/projects").json() == []


def test_unknown_and_malformed_project_ids(client: httpx.Client) -> None:
    ghost = uuid.uuid4()
    for method, path, body in [
        ("GET", f"{T}/projects/{ghost}", None),
        ("PUT", f"{T}/projects/{ghost}", {"name": "n"}),
        ("DELETE", f"{T}/projects/{ghost}", None),
    ]:
        response = client.request(method, path, json=body)
        assert response.status_code == 404, (method, response.text)
        assert response.json() == {"detail": "Project not found"}
    add = client.post(f"{T}/projects/{ghost}/workspaces", json={"workspace_path": "."})
    assert add.status_code in (404, 422)
    bad = client.get(f"{T}/projects/not-a-uuid")
    assert bad.status_code == 422 and bad.json()["detail"][0]["loc"] == ["path", "project_id"]


def test_update_changes_only_the_named_fields(client: httpx.Client, repo: Path) -> None:
    project = make_project(client, repo, description="keep", settings={"a": 1})
    pid = project["id"]
    renamed = client.put(f"{T}/projects/{pid}", json={"name": "New"}).json()
    assert renamed["name"] == "New" and renamed["description"] == "keep" and renamed["settings"] == {"a": 1}
    cleared = client.put(f"{T}/projects/{pid}", json={"description": None}).json()
    assert cleared["description"] is None and cleared["name"] == "New"
    settings = client.put(f"{T}/projects/{pid}", json={"settings": {"b": 2}}).json()
    assert settings["settings"] == {"a": 1, "b": 2}  # settings are merged, not replaced
    assert settings["updated_at"] >= project["updated_at"]
    for body in [{"name": ""}, {"name": "x" * 256}]:
        assert client.put(f"{T}/projects/{pid}", json=body).status_code == 422


def test_add_update_and_remove_a_workspace(client: httpx.Client, repo: Path, folder: Path) -> None:
    project = make_project(client, repo)
    pid = project["id"]
    added = client.post(
        f"{T}/projects/{pid}/workspaces", json={"workspace_path": str(folder), "display_name": "Scratch"}
    )
    assert added.status_code == 201, added.text
    item = added.json()
    assert list(item) == ["workspace_id", "path", "name", "display_name", "sort_order", "kind"]
    assert item["display_name"] == "Scratch" and item["sort_order"] == 1
    again = client.post(f"{T}/projects/{pid}/workspaces", json={"workspace_path": str(folder)})
    assert again.status_code in (201, 409), again.text
    updated = client.put(
        f"{T}/projects/{pid}/workspaces/{item['workspace_id']}", json={"display_name": "Renamed", "sort_order": 5}
    )
    assert updated.status_code == 200, updated.text
    assert (updated.json()["display_name"], updated.json()["sort_order"]) == ("Renamed", 5)
    removed = client.delete(f"{T}/projects/{pid}/workspaces/{item['workspace_id']}")
    assert removed.status_code == 204 and removed.content == b""
    again_gone = client.delete(f"{T}/projects/{pid}/workspaces/{item['workspace_id']}")
    assert again_gone.status_code == 404 and again_gone.json() == {"detail": "Workspace not in project"}
    assert folder.is_dir()
    unknown = client.put(f"{T}/projects/{pid}/workspaces/{uuid.uuid4()}", json={"display_name": "x"})
    assert unknown.status_code == 404
    bad_path = client.post(f"{T}/projects/{pid}/workspaces", json={"workspace_path": str(folder / "nope")})
    assert bad_path.status_code == 422


def test_deleting_a_project_never_touches_the_repositories(client: httpx.Client, repo: Path) -> None:
    project = make_project(client, repo)
    head = commit_file(repo, "keep.txt", "k\n", "keep")
    response = client.delete(f"{T}/projects/{project['id']}")
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"{T}/projects/{project['id']}").status_code == 404
    assert (repo / "keep.txt").exists() and (repo / ".git").is_dir()
    assert sha(repo) == head
    assert client.get(f"{T}/projects").json() == []
    assert client.get(f"{T}/workspace/tree").json()["repositories"] == []


def test_tree_lists_only_repositories_owned_by_a_live_project(client: httpx.Client, repo: Path, folder: Path) -> None:
    make_project(client, repo)
    tree = client.get(f"{T}/workspace/tree").json()
    assert [Path(r["path"]).name for r in tree["repositories"]] == ["repo"]
    assert [p["name"] for p in tree["projects"]] == ["Proj"]
    assert list(tree["repositories"][0]) == ["workspace_id", "path", "name", "worktrees", "project_id"]
