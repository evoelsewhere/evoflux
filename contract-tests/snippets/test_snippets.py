"""``/api/snippets`` contract: prompt-snippet discovery and rendering."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}
WORKSPACE_REQUIRED = {"detail": "Snippet workspace is required."}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


@pytest.fixture
def global_root(tmp_path: Path) -> Path:
    return tmp_path / "config" / "snippets"


def project_root(workspace: Path) -> Path:
    return workspace / ".evoflux" / "snippets"


def write(root: Path, name: str, text: str) -> Path:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def touch_ahead(path: Path, seconds: int) -> None:
    """Set mtimes in the future so the mtime-keyed discovery cache sees a change."""
    later = time.time() + seconds
    os.utime(path, (later, later))


def snippet(description: str, body: str) -> str:
    return f"---\ndescription: {description}\n---\n\n{body}\n"


def listing(client: httpx.Client, workspace: Path) -> list[dict]:
    response = client.get("/api/snippets", params={"workspace": str(workspace)})
    assert response.status_code == 200
    return response.json()["snippets"]


def render(client: httpx.Client, name: str, workspace: Path) -> httpx.Response:
    return client.post(
        f"/api/snippets/{name}/render", params={"workspace": str(workspace)}
    )


# ── auth ────────────────────────────────────────────────────────────────────


def test_list_requires_auth(backend, workspace) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/snippets",
        params={"workspace": str(workspace)},
        timeout=30.0,
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_render_requires_auth(backend, workspace) -> None:
    response = httpx.post(
        f"{backend.base_url}/api/snippets/x/render",
        params={"workspace": str(workspace)},
        timeout=30.0,
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_wrong_token_is_rejected(backend, workspace) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/snippets",
        params={"workspace": str(workspace)},
        headers={"Authorization": "Bearer not-the-token"},
        timeout=30.0,
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_token_query_param(backend, workspace) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/snippets",
        params={"_token": backend.token, "workspace": str(workspace)},
        timeout=30.0,
    )
    assert response.status_code == 200


# ── workspace validation ────────────────────────────────────────────────────


def test_list_requires_workspace(client) -> None:
    response = client.get("/api/snippets")
    assert response.status_code == 422
    assert response.json() == WORKSPACE_REQUIRED


def test_render_requires_workspace(client) -> None:
    response = client.post("/api/snippets/x/render")
    assert response.status_code == 422
    assert response.json() == WORKSPACE_REQUIRED


def test_empty_workspace_param_resolves_to_the_backend_cwd(client, tmp_path) -> None:
    write(tmp_path / "cwd" / ".evoflux" / "snippets", "from-cwd", "x")
    response = client.get("/api/snippets", params={"workspace": ""})
    assert response.status_code == 200
    assert response.json() == {
        "snippets": [
            {"name": "from-cwd", "description": "", "source": "project-EvoFlux"}
        ]
    }


def test_list_rejects_missing_workspace(client, tmp_path) -> None:
    missing = (tmp_path / "does-not-exist").resolve()
    response = client.get("/api/snippets", params={"workspace": str(missing)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {missing}"
    }


def test_render_rejects_missing_workspace_before_lookup(client, tmp_path) -> None:
    missing = (tmp_path / "gone").resolve()
    response = client.post("/api/snippets/x/render", params={"workspace": str(missing)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {missing}"
    }


def test_workspace_that_is_a_file_is_rejected(client, tmp_path) -> None:
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    response = client.get("/api/snippets", params={"workspace": str(target)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {target.resolve()}"
    }


def test_render_rejects_workspace_that_is_a_file(client, tmp_path) -> None:
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    response = client.post("/api/snippets/x/render", params={"workspace": str(target)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {target.resolve()}"
    }


def test_workspace_tilde_expands_to_home(client, tmp_path) -> None:
    write(tmp_path / "home" / "proj" / ".evoflux" / "snippets", "from-home", "x")
    response = client.get("/api/snippets", params={"workspace": "~/proj"})
    assert response.status_code == 200
    assert [s["name"] for s in response.json()["snippets"]] == ["from-home"]


# ── list ────────────────────────────────────────────────────────────────────


def test_list_empty_state(client, workspace) -> None:
    response = client.get("/api/snippets", params={"workspace": str(workspace)})
    assert response.status_code == 200
    assert response.json() == {"snippets": []}


def test_list_project_and_global_sorted_by_name(client, workspace, global_root) -> None:
    write(project_root(workspace), "review", snippet("Review a diff", "Review it."))
    write(global_root, "Alpha", snippet("global", "A"))
    write(global_root, "git/commit", "Write a commit message.")
    assert listing(client, workspace) == [
        {"name": "Alpha", "description": "global", "source": "global-EvoFlux"},
        {"name": "git/commit", "description": "", "source": "global-EvoFlux"},
        {"name": "review", "description": "Review a diff", "source": "project-EvoFlux"},
    ]


def test_list_sort_is_by_code_point(client, workspace, global_root) -> None:
    for name in ("b", "_a", "é", "Z", "a.b", "a-c", "a"):
        write(global_root, name, "body")
    assert [s["name"] for s in listing(client, workspace)] == [
        "Z",
        "_a",
        "a",
        "a-c",
        "a.b",
        "b",
        "é",
    ]


def test_project_snippet_wins_over_global(client, workspace, global_root) -> None:
    write(project_root(workspace), "shared", snippet("project", "project body"))
    write(global_root, "shared", snippet("global", "global body"))
    write(global_root, "only-global", "g")
    rows = {s["name"]: s for s in listing(client, workspace)}
    assert rows["shared"] == {
        "name": "shared",
        "description": "project",
        "source": "project-EvoFlux",
    }
    assert rows["only-global"]["source"] == "global-EvoFlux"
    assert render(client, "shared", workspace).json()["content"] == "project body"


def test_snippets_do_not_leak_between_workspaces(client, tmp_path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    write(project_root(one), "only-one", "1")
    write(project_root(two), "only-two", "2")
    assert [s["name"] for s in listing(client, one)] == ["only-one"]
    assert [s["name"] for s in listing(client, two)] == ["only-two"]
    assert render(client, "only-one", two).status_code == 404


def test_global_snippets_available_to_every_workspace(client, tmp_path, global_root) -> None:
    write(global_root, "everywhere", "x")
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    assert [s["name"] for s in listing(client, one)] == ["everywhere"]
    assert [s["name"] for s in listing(client, two)] == ["everywhere"]


def test_other_roots_are_not_snippet_roots(client, workspace, tmp_path) -> None:
    write(workspace / ".opencode" / "snippets", "oc", "x")
    write(workspace / ".evoflux" / "commands", "cmd", "x")
    write(tmp_path / "config" / "commands", "global-cmd", "x")
    write(tmp_path / "home" / ".config" / "opencode" / "snippets", "oc-global", "x")
    write(workspace / "snippets", "bare", "x")
    assert listing(client, workspace) == []


def test_nested_folders_one_level_only(client, workspace, global_root) -> None:
    write(global_root, "git/commit", "x")
    write(global_root, "git/deeper/too-deep", "x")
    write(global_root, "a/b/c/three", "x")
    write(global_root, "top", "x")
    assert [s["name"] for s in listing(client, workspace)] == ["git/commit", "top"]


def test_only_markdown_files_are_snippets(client, workspace, global_root) -> None:
    write(global_root, "real", "x")
    (global_root / "notes.txt").write_text("x", encoding="utf-8")
    (global_root / "folder.md").mkdir()
    assert [s["name"] for s in listing(client, workspace)] == ["real"]


def test_unicode_names_and_descriptions(client, workspace, global_root) -> None:
    write(global_root, "café/crème", snippet("Ünïcode — ✓", "corps"))
    assert listing(client, workspace) == [
        {
            "name": "café/crème",
            "description": "Ünïcode — ✓",
            "source": "global-EvoFlux",
        }
    ]


@pytest.mark.parametrize(
    ("text", "description"),
    [
        ("---\ndescription:   padded  \n---\nbody", "padded"),
        ("---\ndescription: 42\n---\nbody", ""),
        ("---\ndescription: [a, b]\n---\nbody", ""),
        ("---\nother: value\n---\nbody", ""),
        ("---\n- just\n- a list\n---\nbody", ""),
        ("no frontmatter at all", ""),
        ("---\r\ndescription: crlf\r\n---\r\nbody", "crlf"),
    ],
)
def test_description_parsing(client, workspace, global_root, text, description) -> None:
    write(global_root, "x", text)
    assert listing(client, workspace) == [
        {"name": "x", "description": description, "source": "global-EvoFlux"}
    ]


def test_list_picks_up_edits_additions_and_removals(client, workspace, global_root) -> None:
    path = write(global_root, "live", snippet("first", "one"))
    assert listing(client, workspace)[0]["description"] == "first"
    path.write_text(snippet("second", "two"), encoding="utf-8")
    touch_ahead(path, 5)
    assert listing(client, workspace)[0]["description"] == "second"
    assert render(client, "live", workspace).json()["content"] == "two"
    touch_ahead(write(project_root(workspace), "added", "x"), 10)
    touch_ahead(project_root(workspace), 10)
    assert [s["name"] for s in listing(client, workspace)] == ["added", "live"]
    path.unlink()
    touch_ahead(project_root(workspace), 20)
    touch_ahead(global_root, 20)
    assert [s["name"] for s in listing(client, workspace)] == ["added"]


# ── render ──────────────────────────────────────────────────────────────────


def test_render_returns_body_without_frontmatter(client, workspace, global_root) -> None:
    write(global_root, "greet", snippet("d", "Hello there."))
    response = render(client, "greet", workspace)
    assert response.status_code == 200
    assert response.json() == {"name": "greet", "content": "Hello there."}


def test_render_does_not_substitute_arguments(client, workspace, global_root) -> None:
    write(global_root, "literal", "Keep $ARGUMENTS as is.")
    response = client.post(
        "/api/snippets/literal/render",
        params={"workspace": str(workspace)},
        json={"arguments": "ignored"},
    )
    assert response.status_code == 200
    assert response.json() == {"name": "literal", "content": "Keep $ARGUMENTS as is."}


@pytest.mark.parametrize(
    ("text", "body"),
    [
        ("---\ndescription: d\n---\n\n  Body text  \n\n", "Body text"),
        ("plain\n\n", "plain"),
        ("---\ndescription: d\n---", "---\ndescription: d\n---"),
        ("---\ndescription: d\n---\n", ""),
        ("---\ndescription: d\n---\nline1\r\nline2\r\n", "line1\nline2"),
        ("---\nA: 1\n---\nfirst\n---\nsecond", "first\n---\nsecond"),
        ("", ""),
    ],
)
def test_body_parsing(client, workspace, global_root, text, body) -> None:
    write(global_root, "x", text)
    response = render(client, "x", workspace)
    assert response.status_code == 200
    assert response.json() == {"name": "x", "content": body}


def test_render_nested_name_with_slash(client, workspace, global_root) -> None:
    write(global_root, "git/commit", snippet("d", "Commit body"))
    response = render(client, "git/commit", workspace)
    assert response.status_code == 200
    assert response.json() == {"name": "git/commit", "content": "Commit body"}


def test_render_unknown_snippet_is_404(client, workspace) -> None:
    response = render(client, "nope", workspace)
    assert response.status_code == 404
    assert response.json() == {"detail": "Snippet 'nope' not found."}


def test_render_unknown_nested_and_too_deep_names_are_404(
    client, workspace, global_root
) -> None:
    write(global_root, "a/b/c", "x")
    for name in ("git/missing", "a/b/c", "a/b"):
        response = render(client, name, workspace)
        assert response.status_code == 404, name
        assert response.json() == {"detail": f"Snippet '{name}' not found."}


def test_render_name_is_case_sensitive_and_url_decoded(client, workspace, global_root) -> None:
    write(global_root, "Mixed", "x")
    assert render(client, "Mixed", workspace).status_code == 200
    assert render(client, "mixed", workspace).status_code == 404
    response = render(client, "has%20space", workspace)
    assert response.status_code == 404
    assert response.json() == {"detail": "Snippet 'has space' not found."}


def test_builtin_init_is_not_a_snippet(client, workspace) -> None:
    response = render(client, "init", workspace)
    assert response.status_code == 404
    assert response.json() == {"detail": "Snippet 'init' not found."}


def test_commands_are_not_snippets(client, workspace, tmp_path) -> None:
    write(tmp_path / "config" / "commands", "only-command", "x")
    assert render(client, "only-command", workspace).status_code == 404


def test_wrong_methods_are_405(client, workspace) -> None:
    params = {"workspace": str(workspace)}
    assert client.get("/api/snippets/x/render", params=params).status_code == 405
    assert client.post("/api/snippets", params=params).status_code == 405


# ── concurrency ─────────────────────────────────────────────────────────────


def test_concurrent_reads_are_consistent(client, workspace, global_root) -> None:
    write(global_root, "busy", snippet("d", "Busy body"))

    def one(_: int) -> tuple[list[dict], dict]:
        return listing(client, workspace), render(client, "busy", workspace).json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(24)))
    expected = [{"name": "busy", "description": "d", "source": "global-EvoFlux"}]
    for rows, rendered in results:
        assert rows == expected
        assert rendered == {"name": "busy", "content": "Busy body"}
