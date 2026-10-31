"""``/api/commands`` contract: slash-command discovery and rendering."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    """The global discovery roots (the backend's config dir and home live in tmp_path)."""
    return {
        "global-EvoFlux": tmp_path / "config" / "commands",
        "global-opencode": tmp_path / "home" / ".config" / "opencode" / "commands",
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


def write(root: Path, name: str, text: str) -> Path:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def touch_ahead(path: Path, seconds: int) -> None:
    """Set mtimes in the future so the mtime-keyed discovery cache sees a change."""
    later = time.time() + seconds
    os.utime(path, (later, later))


def cmd(description: str, body: str) -> str:
    return f"---\ndescription: {description}\n---\n\n{body}\n"


def listing(client: httpx.Client, workspace: Path | None = None) -> list[dict]:
    params = {"workspace": str(workspace)} if workspace is not None else None
    response = client.get("/api/commands", params=params)
    assert response.status_code == 200
    return response.json()["commands"]


def render(
    client: httpx.Client,
    name: str,
    arguments: str | None = "",
    workspace: Path | None = None,
) -> httpx.Response:
    params = {"workspace": str(workspace)} if workspace is not None else None
    body = {} if arguments is None else {"arguments": arguments}
    return client.post(f"/api/commands/{name}/render", params=params, json=body)


# ── auth ────────────────────────────────────────────────────────────────────


def test_list_requires_auth(backend) -> None:
    response = httpx.get(f"{backend.base_url}/api/commands", timeout=30.0)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_render_requires_auth(backend) -> None:
    response = httpx.post(
        f"{backend.base_url}/api/commands/init/render", json={}, timeout=30.0
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_wrong_token_is_rejected(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/commands",
        headers={"Authorization": "Bearer not-the-token"},
        timeout=30.0,
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_token_query_param(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/commands",
        params={"_token": backend.token},
        timeout=30.0,
    )
    assert response.status_code == 200


# ── list ────────────────────────────────────────────────────────────────────


def test_list_empty_state(client: httpx.Client) -> None:
    response = client.get("/api/commands")
    assert response.status_code == 200
    assert response.json() == {"commands": []}


def test_list_global_sources_sorted_by_name(client, roots) -> None:
    write(roots["global-opencode"], "zeta", cmd("from opencode", "z"))
    write(roots["global-EvoFlux"], "alpha", cmd("from evoflux", "a"))
    write(roots["global-EvoFlux"], "Beta", cmd("capital sorts first", "b"))
    assert listing(client) == [
        {
            "name": "Beta",
            "description": "capital sorts first",
            "source": "global-EvoFlux",
        },
        {"name": "alpha", "description": "from evoflux", "source": "global-EvoFlux"},
        {"name": "zeta", "description": "from opencode", "source": "global-opencode"},
    ]


def test_list_sort_is_by_code_point(client, roots) -> None:
    for name in ("b", "_a", "é", "Z", "a.b", "a-c", "a"):
        write(roots["global-EvoFlux"], name, "body")
    assert [c["name"] for c in listing(client)] == [
        "Z",
        "_a",
        "a",
        "a-c",
        "a.b",
        "b",
        "é",
    ]


def test_list_project_roots_need_workspace(client, roots, workspace) -> None:
    write(workspace / ".evoflux" / "commands", "local", "x")
    write(workspace / ".opencode" / "commands", "oc-local", "x")
    write(roots["global-EvoFlux"], "shared", "x")
    assert [c["name"] for c in listing(client)] == ["shared"]
    assert listing(client, workspace) == [
        {"name": "local", "description": "", "source": "project-EvoFlux"},
        {"name": "oc-local", "description": "", "source": "project-opencode"},
        {"name": "shared", "description": "", "source": "global-EvoFlux"},
    ]


def test_precedence_follows_the_four_roots(client, roots, workspace) -> None:
    project = workspace / ".evoflux" / "commands"
    project_oc = workspace / ".opencode" / "commands"
    write(project, "a", cmd("p-evoflux", "1"))
    write(project_oc, "a", cmd("p-opencode", "2"))
    write(roots["global-EvoFlux"], "a", cmd("g-evoflux", "3"))
    write(roots["global-opencode"], "a", cmd("g-opencode", "4"))
    write(project_oc, "b", cmd("p-opencode", "2"))
    write(roots["global-EvoFlux"], "b", cmd("g-evoflux", "3"))
    write(roots["global-EvoFlux"], "c", cmd("g-evoflux", "3"))
    write(roots["global-opencode"], "c", cmd("g-opencode", "4"))
    rows = {c["name"]: c for c in listing(client, workspace)}
    assert rows["a"]["source"] == "project-EvoFlux"
    assert rows["b"]["source"] == "project-opencode"
    assert rows["c"]["source"] == "global-EvoFlux"
    assert render(client, "a", workspace=workspace).json()["content"] == "1"
    assert render(client, "b", workspace=workspace).json()["content"] == "2"
    assert render(client, "c", workspace=workspace).json()["content"] == "3"


def test_workspace_commands_do_not_leak_between_projects(client, tmp_path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    write(one / ".evoflux" / "commands", "only-one", "1")
    write(two / ".evoflux" / "commands", "only-two", "2")
    assert [c["name"] for c in listing(client, one)] == ["only-one"]
    assert [c["name"] for c in listing(client, two)] == ["only-two"]
    assert render(client, "only-one", workspace=two).status_code == 404


def test_workspace_tilde_expands_to_home(client, tmp_path) -> None:
    write(tmp_path / "home" / "proj" / ".evoflux" / "commands", "from-home", "x")
    response = client.get("/api/commands", params={"workspace": "~/proj"})
    assert response.status_code == 200
    assert [c["name"] for c in response.json()["commands"]] == ["from-home"]


def test_empty_workspace_param_resolves_to_the_backend_cwd(client, tmp_path) -> None:
    write(tmp_path / "cwd" / ".evoflux" / "commands", "from-cwd", "x")
    response = client.get("/api/commands", params={"workspace": ""})
    assert response.status_code == 200
    assert response.json() == {
        "commands": [
            {"name": "from-cwd", "description": "", "source": "project-EvoFlux"}
        ]
    }


def test_nested_folders_one_level_only(client, roots) -> None:
    root = roots["global-EvoFlux"]
    write(root, "git/commit", "x")
    write(root, "git/deeper/too-deep", "x")
    write(root, "a/b/c/three", "x")
    write(root, "top", "x")
    assert [c["name"] for c in listing(client)] == ["git/commit", "top"]


def test_only_markdown_files_are_commands(client, roots) -> None:
    root = roots["global-EvoFlux"]
    write(root, "real", "x")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / "script.md.bak").write_text("x", encoding="utf-8")
    (root / "folder.md").mkdir()
    assert [c["name"] for c in listing(client)] == ["real"]


def test_dotted_file_names_keep_inner_dots(client, roots) -> None:
    write(roots["global-EvoFlux"], "release.notes", "x")
    assert [c["name"] for c in listing(client)] == ["release.notes"]


def test_unicode_names_and_descriptions(client, roots) -> None:
    write(roots["global-EvoFlux"], "café/crème", cmd("Ünïcode — ✓", "corps"))
    assert listing(client) == [
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
        ("---\ndescription:\n---\nbody", ""),
        ("---\nother: value\n---\nbody", ""),
        ("---\n---\nbody", ""),
        ("---\n- just\n- a list\n---\nbody", ""),
        ("---\njust a scalar\n---\nbody", ""),
        ("no frontmatter at all", ""),
        ("---\r\ndescription: crlf\r\n---\r\nbody", "crlf"),
        ("--- \ndescription: spaced fence\n---   \nbody", "spaced fence"),
        ("---\ndescription: |\n  folded\n  text\n---\nbody", "folded\ntext"),
    ],
)
def test_description_parsing(client, roots, text, description) -> None:
    write(roots["global-EvoFlux"], "x", text)
    assert listing(client) == [
        {"name": "x", "description": description, "source": "global-EvoFlux"}
    ]


@pytest.mark.parametrize(
    ("text", "body"),
    [
        ("---\ndescription: d\n---\n\n  Body text  \n\n", "Body text"),
        ("plain\n\n", "plain"),
        ("---\ndescription: d\n---", "---\ndescription: d\n---"),
        ("---\ndescription: d\n---\n", ""),
        ("---\ndescription: d\n---\nline1\r\nline2\r\n", "line1\nline2"),
        ("---\nA: 1\n---\nfirst\n---\nsecond", "first\n---\nsecond"),
        ("\n---\ndescription: d\n---\nbody", "---\ndescription: d\n---\nbody"),
        ("", ""),
    ],
)
def test_body_parsing(client, roots, text, body) -> None:
    write(roots["global-EvoFlux"], "x", text)
    response = render(client, "x")
    assert response.status_code == 200
    assert response.json() == {"name": "x", "content": body}


def test_list_picks_up_edits_additions_and_removals(client, roots) -> None:
    root = roots["global-EvoFlux"]
    path = write(root, "live", cmd("first", "one"))
    assert listing(client)[0]["description"] == "first"
    path.write_text(cmd("second", "two"), encoding="utf-8")
    touch_ahead(path, 5)
    assert listing(client)[0]["description"] == "second"
    assert render(client, "live").json()["content"] == "two"
    touch_ahead(write(root, "extra/added", "x"), 10)
    touch_ahead(root / "extra", 10)
    touch_ahead(root, 10)
    assert [c["name"] for c in listing(client)] == ["extra/added", "live"]
    path.unlink()
    touch_ahead(root, 20)
    assert [c["name"] for c in listing(client)] == ["extra/added"]


# ── list: validation ────────────────────────────────────────────────────────


def test_list_rejects_missing_workspace(client, tmp_path) -> None:
    missing = (tmp_path / "does-not-exist").resolve()
    response = client.get("/api/commands", params={"workspace": str(missing)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {missing}"
    }


def test_list_rejects_workspace_that_is_a_file(client, tmp_path) -> None:
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    response = client.get("/api/commands", params={"workspace": str(target)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {target.resolve()}"
    }


# ── render ──────────────────────────────────────────────────────────────────


def test_render_substitutes_arguments(client, roots) -> None:
    write(roots["global-EvoFlux"], "greet", cmd("d", "Hello $ARGUMENTS, welcome."))
    response = render(client, "greet", "Ada")
    assert response.status_code == 200
    assert response.json() == {"name": "greet", "content": "Hello Ada, welcome."}


def test_render_substitutes_every_occurrence_and_strips_arguments(
    client, roots
) -> None:
    write(roots["global-EvoFlux"], "twice", "$ARGUMENTS and $ARGUMENTS")
    assert render(client, "twice", "  go  ").json()["content"] == "go and go"


def test_render_placeholder_with_empty_arguments(client, roots) -> None:
    write(roots["global-EvoFlux"], "empty", "[$ARGUMENTS]")
    assert render(client, "empty", "").json()["content"] == "[]"
    assert render(client, "empty", "   ").json()["content"] == "[]"


def test_render_appends_arguments_without_placeholder(client, roots) -> None:
    write(roots["global-EvoFlux"], "plain", "Do the thing.")
    assert render(client, "plain", " now ").json()["content"] == "Do the thing.\n\nnow"


def test_render_without_arguments_leaves_body(client, roots) -> None:
    write(roots["global-EvoFlux"], "plain", "Do the thing.")
    assert render(client, "plain", "").json()["content"] == "Do the thing."
    assert render(client, "plain", "  \n ").json()["content"] == "Do the thing."


def test_render_arguments_default_to_empty(client, roots) -> None:
    write(roots["global-EvoFlux"], "plain", "Do $ARGUMENTS.")
    response = render(client, "plain", None)
    assert response.status_code == 200
    assert response.json() == {"name": "plain", "content": "Do ."}


def test_render_does_not_expand_other_placeholders(client, roots) -> None:
    write(roots["global-EvoFlux"], "dollars", "$1 $ARGUMENT $arguments ${ARGUMENTS}")
    assert (
        render(client, "dollars", "x").json()["content"]
        == "$1 $ARGUMENT $arguments ${ARGUMENTS}\n\nx"
    )


def test_render_arguments_containing_placeholder_are_not_reexpanded(
    client, roots
) -> None:
    write(roots["global-EvoFlux"], "echo", "<$ARGUMENTS>")
    assert render(client, "echo", "$ARGUMENTS").json()["content"] == "<$ARGUMENTS>"


def test_render_nested_command_name_with_slash(client, roots) -> None:
    write(roots["global-EvoFlux"], "git/commit", cmd("d", "Commit: $ARGUMENTS"))
    response = render(client, "git/commit", "fix bug")
    assert response.status_code == 200
    assert response.json() == {"name": "git/commit", "content": "Commit: fix bug"}


def test_render_uses_workspace_local_command(client, roots, workspace) -> None:
    write(roots["global-EvoFlux"], "shared", "global body")
    write(workspace / ".evoflux" / "commands", "shared", "project body")
    assert render(client, "shared").json()["content"] == "global body"
    assert (
        render(client, "shared", workspace=workspace).json()["content"]
        == "project body"
    )


def test_render_unknown_command_is_404(client) -> None:
    response = render(client, "nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Command 'nope' not found."}


def test_render_unknown_nested_and_too_deep_names_are_404(client, roots) -> None:
    write(roots["global-EvoFlux"], "a/b/c", "x")
    for name in ("git/missing", "a/b/c", "a/b"):
        response = render(client, name)
        assert response.status_code == 404, name
        assert response.json() == {"detail": f"Command '{name}' not found."}


def test_render_name_is_case_sensitive_and_url_decoded(client, roots) -> None:
    write(roots["global-EvoFlux"], "Mixed", "x")
    assert render(client, "Mixed").status_code == 200
    assert render(client, "mixed").status_code == 404
    response = render(client, "has%20space")
    assert response.status_code == 404
    assert response.json() == {"detail": "Command 'has space' not found."}


def test_render_invalid_workspace_is_422_before_lookup(client, tmp_path) -> None:
    missing = (tmp_path / "gone").resolve()
    response = render(client, "init", workspace=missing)
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Workspace does not exist or is not a directory: {missing}"
    }


@pytest.mark.parametrize("payload", [{"arguments": 5}, {"arguments": None}, {"arguments": ["a"]}])
def test_render_validation_errors(client, payload) -> None:
    response = client.post("/api/commands/init/render", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [(d["type"], d["loc"]) for d in detail] == [
        ("string_type", ["body", "arguments"])
    ]


def test_render_requires_a_json_object_body(client) -> None:
    missing = client.post("/api/commands/init/render")
    assert missing.status_code == 422
    assert [(d["type"], d["loc"]) for d in missing.json()["detail"]] == [
        ("missing", ["body"])
    ]
    malformed = client.post(
        "/api/commands/init/render",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"][0]["type"] == "json_invalid"
    listy = client.post("/api/commands/init/render", json=[])
    assert listy.status_code == 422
    assert [(d["type"], d["loc"]) for d in listy.json()["detail"]] == [
        ("model_attributes_type", ["body"])
    ]


def test_render_ignores_unknown_body_fields(client, roots) -> None:
    write(roots["global-EvoFlux"], "plain", "body")
    response = client.post(
        "/api/commands/plain/render", json={"arguments": "", "extra": 1}
    )
    assert response.status_code == 200
    assert response.json() == {"name": "plain", "content": "body"}


def test_wrong_methods_are_405(client) -> None:
    assert client.get("/api/commands/init/render").status_code == 405
    assert client.post("/api/commands", json={}).status_code == 405


# ── built-in init ───────────────────────────────────────────────────────────


def test_builtin_init_is_not_listed(client) -> None:
    assert listing(client) == []


def test_builtin_init_render_is_exact(client, snapshot) -> None:
    response = render(client, "init")
    assert response.status_code == 200
    snapshot.check("init-render.json", response.json())


def test_builtin_init_appends_arguments(client) -> None:
    plain = render(client, "init").json()["content"]
    with_args = render(client, "init", "  focus on web/ ").json()
    assert with_args == {"name": "init", "content": f"{plain}\n\nfocus on web/"}


def test_builtin_init_needs_no_workspace_or_files(client, workspace) -> None:
    assert render(client, "init", workspace=workspace).status_code == 200


def test_disk_command_shadows_builtin_init(client, roots) -> None:
    write(roots["global-EvoFlux"], "init", cmd("mine", "custom init"))
    assert render(client, "init").json() == {"name": "init", "content": "custom init"}
    assert [c["name"] for c in listing(client)] == ["init"]


# ── concurrency ─────────────────────────────────────────────────────────────


def test_concurrent_reads_are_consistent(client, roots) -> None:
    write(roots["global-EvoFlux"], "busy", cmd("d", "Run $ARGUMENTS"))

    def one(i: int) -> tuple[list[dict], str]:
        rows = client.get("/api/commands").json()["commands"]
        content = render(client, "busy", f"job-{i}").json()["content"]
        return rows, content

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(24)))
    expected = [{"name": "busy", "description": "d", "source": "global-EvoFlux"}]
    for i, (rows, content) in enumerate(results):
        assert rows == expected
        assert content == f"Run job-{i}"
