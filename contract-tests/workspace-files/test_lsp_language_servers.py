"""``/workspace/lsp/*`` and ``/workspace/language-servers/*``.

No real language server is started and nothing is installed:

- the LSP routes are called only for a file whose extension has no server
  mapping (``unsupported``) or for requests refused before a server is chosen;
- a call that would launch ``pyright``, ``gopls`` or any other binary found on
  the machine's PATH is skipped (``test_lsp_with_a_server_is_skipped``): the
  result depends on what the developer has installed;
- the install routes are called only for an unknown id and for a server that
  has no managed installer, which both answer before any process starts.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from ws_helpers import Scrub, same_path

WS = "/api/team/workspace"
EXPECTED_LANGUAGES = {
    "bash", "c", "cpp", "csharp", "css", "dart", "go", "html", "java", "json",
    "kotlin", "lua", "markdown", "php", "python", "ruby", "rust", "svelte",
    "swift", "toml", "typescript", "vue", "yaml",
}  # fmt: skip
STATUS_KEYS = {
    "language_id", "display_name", "extensions", "detected", "file_count",
    "repositories", "state", "source", "command", "installed_version",
    "expected_version", "installable", "installer", "installer_available",
    "install_hint", "blocked_reason", "install_phase", "install_started_at",
    "install_error",
}  # fmt: skip


def diagnostics(client: httpx.Client, root: Path, body: dict) -> httpx.Response:
    return client.post(f"{WS}/lsp/diagnostics", params={"workspace": str(root)}, json=body)


def semantic(client: httpx.Client, root: Path, body: dict) -> httpx.Response:
    return client.post(f"{WS}/lsp/semantic", params={"workspace": str(root)}, json=body)


# ── diagnostics ───────────────────────────────────────────────────────────────


def test_diagnostics_for_an_unmapped_extension_is_unsupported(
    client: httpx.Client, workspace: Path
) -> None:
    response = diagnostics(client, workspace, {"path": "a.txt", "content": "text"})
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["workspace", "path", "language", "status", "diagnostics", "message"]
    assert same_path(body["workspace"], workspace)
    assert body["path"] == "a.txt" and body["language"] is None
    assert body["status"] == "unsupported" and body["diagnostics"] == []
    assert body["message"] == "No language server mapping for extension '.txt'."
    # the buffer is not written to disk
    assert (workspace / "a.txt").read_bytes() == b"hello\n"
    # an extension with no suffix at all
    (workspace / "Makefile").write_text("all:\n", encoding="utf-8")
    bare = diagnostics(client, workspace, {"path": "Makefile", "content": ""}).json()
    assert bare["message"] == "No language server mapping for extension ''."


def test_diagnostics_path_checks_come_before_the_server_lookup(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    # a mapped extension, so a mistake would start pyright; every case is refused first
    cases = {
        "../outside/x.py": (400, "Path escapes workspace root."),
        "sub/../../outside/x.py": (400, "Path escapes workspace root."),
        str(outside / "x.py"): (400, "Absolute paths rejected."),
        "nope.py": (404, "File not found."),
        "sub": (404, "File not found."),
    }
    for path, (status, detail) in cases.items():
        response = diagnostics(client, workspace, {"path": path, "content": "x"})
        assert (response.status_code, response.json()) == (status, {"detail": detail}), path
    # an absolute path is caught before the file is looked up, so it is refused
    # even for a file that exists
    existing = diagnostics(client, workspace, {"path": str(workspace / "sub" / "b.py"), "content": ""})
    assert (existing.status_code, existing.json()) == (400, {"detail": "Absolute paths rejected."})


@pytest.mark.skipif(os.name != "nt", reason="Windows path rules")
def test_diagnostics_drive_paths(client: httpx.Client, workspace: Path) -> None:
    for path in ("C:x.py", "C:\\x.py", "Z:rel.py", "\\\\nonexistent.invalid\\s\\x.py"):
        response = diagnostics(client, workspace, {"path": path, "content": "x"})
        assert response.status_code == 400, path
        assert response.json() == {"detail": "Absolute paths rejected."}


def test_diagnostics_body_validation(client: httpx.Client, workspace: Path) -> None:
    missing_content = diagnostics(client, workspace, {"path": "a.txt"})
    assert missing_content.status_code == 422
    assert missing_content.json()["detail"][0]["loc"] == ["body", "content"]
    empty_path = diagnostics(client, workspace, {"path": "", "content": ""})
    assert empty_path.status_code == 422
    assert empty_path.json()["detail"][0]["type"] == "string_too_short"
    too_long = diagnostics(client, workspace, {"path": "a" * 4097, "content": ""})
    assert too_long.json()["detail"][0]["type"] == "string_too_long"
    big = diagnostics(client, workspace, {"path": "a.txt", "content": "x" * 2_000_001})
    assert big.json()["detail"][0]["type"] == "string_too_long"
    bad_workspace = client.post(
        f"{WS}/lsp/diagnostics",
        params={"workspace": str(workspace / "nope")},
        json={"path": "a.txt", "content": ""},
    )
    assert bad_workspace.status_code == 422
    assert bad_workspace.json()["detail"].startswith("Workspace does not exist")


# ── semantic ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action",
    [
        "hover",
        "code_actions",
        "rename",
        "format",
        "organize_imports",
        "document_symbols",
        "workspace_symbols",
    ],
)
def test_semantic_for_an_unmapped_extension_is_unsupported(
    client: httpx.Client, workspace: Path, action: str
) -> None:
    # unsupported is answered before position and new_name are validated
    response = semantic(client, workspace, {"action": action, "path": "a.txt"})
    assert response.status_code == 200
    body = response.json()
    assert list(body) == [
        "workspace", "path", "action", "language", "status", "result", "capabilities", "message",
    ]  # fmt: skip
    assert body["action"] == action and body["status"] == "unsupported"
    assert body["language"] is None and body["result"] is None and body["capabilities"] == {}
    assert body["message"] == "No language server mapping for extension '.txt'."


def test_semantic_checks_the_path_first(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    cases = {
        "../outside/x.py": (400, "Path escapes workspace root."),
        str(outside / "x.py"): (400, "Absolute paths rejected."),
        "nope.py": (404, "File not found."),
    }
    for path, (status, detail) in cases.items():
        response = semantic(client, workspace, {"action": "format", "path": path})
        assert (response.status_code, response.json()) == (status, {"detail": detail}), path


def test_semantic_request_validation(client: httpx.Client, workspace: Path) -> None:
    def fields(body: dict) -> list[object]:
        response = semantic(client, workspace, body)
        assert response.status_code == 422, body
        return [item["loc"] for item in response.json()["detail"]]

    assert fields({"action": "zap", "path": "a.txt"}) == [["body", "action"]]
    assert fields({"action": "format", "path": ""}) == [["body", "path"]]
    assert fields({"action": "hover", "path": "a.txt", "line": 0}) == [["body", "line"]]
    assert fields({"action": "hover", "path": "a.txt", "column": 0}) == [["body", "column"]]
    assert fields({"action": "format", "path": "a.txt", "tab_size": 17}) == [["body", "tab_size"]]
    assert fields({"action": "format", "path": "a.txt", "tab_size": 0}) == [["body", "tab_size"]]
    assert fields({"action": "rename", "path": "a.txt", "new_name": ""}) == [["body", "new_name"]]
    assert fields({"action": "rename", "path": "a.txt", "new_name": "n" * 513}) == [
        ["body", "new_name"]
    ]
    assert fields({"action": "workspace_symbols", "path": "a.txt", "query": "q" * 513}) == [
        ["body", "query"]
    ]
    assert fields(
        {"action": "code_actions", "path": "a.txt", "diagnostics": [{}] * 201}
    ) == [["body", "diagnostics"]]
    assert fields({"action": "format", "path": "a.txt", "content": "x" * 2_000_001}) == [
        ["body", "content"]
    ]


def test_semantic_position_checks_run_after_the_mapping_lookup(
    client: httpx.Client, workspace: Path
) -> None:
    """A mapped extension reaches the position and ``new_name`` checks.

    Those are 422s raised before any server is looked up, so they are safe to
    pin even for a ``.py`` file.
    """
    (workspace / "m.py").write_text("x = 1\n", encoding="utf-8")
    for action in ("hover", "code_actions", "rename"):
        response = semantic(client, workspace, {"action": action, "path": "m.py"})
        assert (response.status_code, response.json()) == (
            422,
            {"detail": f"{action} requires line and column."},
        )
    no_name = semantic(
        client, workspace, {"action": "rename", "path": "m.py", "line": 1, "column": 1}
    )
    assert no_name.status_code == 422
    assert no_name.json() == {"detail": "rename requires new_name."}
    blank = semantic(
        client,
        workspace,
        {"action": "rename", "path": "m.py", "line": 1, "column": 1, "new_name": "   "},
    )
    assert blank.json() == {"detail": "rename requires new_name."}


@pytest.mark.skip(
    reason="a mapped extension starts whichever server is on the machine's PATH or "
    "in the managed cache; its answer (ready or unavailable) is not reproducible"
)
def test_lsp_with_a_server_is_skipped() -> None: ...


# ── language servers ──────────────────────────────────────────────────────────


def test_language_server_overview_shape_and_detection(
    client: httpx.Client, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "m.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / "n.PY").write_text("x = 1\n", encoding="utf-8")
    (workspace / "app.ts").write_text("let a = 1\n", encoding="utf-8")
    (workspace / ".gitignore").write_text("ignored.go\n", encoding="utf-8")
    (workspace / "ignored.go").write_text("package x\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "hooked.go").write_text("package x\n", encoding="utf-8")
    response = client.post(f"{WS}/language-servers/status", json={"workspaces": [str(workspace)]})
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["workspaces", "cache_dir", "servers", "scan_truncated", "scan_limit"]
    assert [Path(w).resolve() for w in body["workspaces"]] == [workspace.resolve()]
    assert same_path(body["cache_dir"], tmp_path / "cache" / "language-servers")
    assert body["scan_truncated"] is False and body["scan_limit"] == 50_000
    servers = {s["language_id"]: s for s in body["servers"]}
    assert set(servers) == EXPECTED_LANGUAGES
    assert all(set(s) == STATUS_KEYS for s in body["servers"])
    # detected languages sort first, then by display name without case
    detected = [s["language_id"] for s in body["servers"] if s["detected"]]
    assert detected == ["python", "typescript"]
    assert [s["language_id"] for s in body["servers"][:2]] == detected
    rest = [s["display_name"].casefold() for s in body["servers"][2:]]
    assert rest == sorted(rest)
    # m.py, n.PY (matches case-insensitively) and the fixture's sub/b.py
    assert servers["python"]["file_count"] == 3
    assert servers["python"]["repositories"] == [
        {"workspace": servers["python"]["repositories"][0]["workspace"], "name": "ws", "file_count": 3}
    ]
    assert servers["go"]["detected"] is False and servers["go"]["file_count"] == 0
    assert servers["python"]["extensions"] == [".py", ".pyi", ".pyw"]
    assert servers["python"]["install_phase"] == "idle"
    assert servers["python"]["install_started_at"] is None


def test_language_server_overview_counts_extensions_by_language(
    client: httpx.Client, tmp_path: Path
) -> None:
    root = tmp_path / "langs"
    root.mkdir()
    for name in ("a.c", "b.h", "c.cc", "d.hpp", "e.rs", "f.json", "g.yml", "h.sh", "i.md"):
        (root / name).write_text("x", encoding="utf-8")
    body = client.post(f"{WS}/language-servers/status", json={"workspaces": [str(root)]}).json()
    counts = {s["language_id"]: s["file_count"] for s in body["servers"] if s["detected"]}
    # ".h" and ".m" belong to C, ".hpp" and ".cc" to C++
    assert counts == {"c": 2, "cpp": 2, "rust": 1, "json": 1, "yaml": 1, "bash": 1, "markdown": 1}


def test_language_server_overview_workspaces(
    client: httpx.Client, workspace: Path, tmp_path: Path, scrub: Scrub
) -> None:
    empty = client.post(f"{WS}/language-servers/status", json={"workspaces": []}).json()
    assert empty["workspaces"] == []
    assert not any(s["detected"] for s in empty["servers"])
    assert client.post(f"{WS}/language-servers/status", json={}).json()["workspaces"] == []
    twice = client.post(
        f"{WS}/language-servers/status", json={"workspaces": [str(workspace), str(workspace)]}
    ).json()
    assert len(twice["workspaces"]) == 1
    missing = client.post(
        f"{WS}/language-servers/status", json={"workspaces": [str(workspace), str(tmp_path / "nope")]}
    )
    assert missing.status_code == 422
    assert scrub(missing.json()) == {
        "detail": "Workspace does not exist or is not a directory: <tmp>/nope"
    }
    too_many = client.post(
        f"{WS}/language-servers/status", json={"workspaces": [str(workspace)] * 33}
    )
    assert too_many.status_code == 422
    assert too_many.json()["detail"][0]["type"] == "too_long"
    wrong = client.post(f"{WS}/language-servers/status", json={"workspaces": "x"})
    assert wrong.status_code == 422


def test_language_server_overview_walks_a_workspace_scan_cap(
    client: httpx.Client, tmp_path: Path
) -> None:
    """Over 50,000 files stops the scan and says so; it does not fail."""
    root = tmp_path / "wide"
    root.mkdir()
    for index in range(50_001):
        (root / f"f{index:05d}.py").write_bytes(b"")
    body = client.post(f"{WS}/language-servers/status", json={"workspaces": [str(root)]}).json()
    assert body["scan_truncated"] is True
    python = next(s for s in body["servers"] if s["language_id"] == "python")
    assert python["file_count"] == 50_000


def test_language_server_install_routes_that_start_nothing(client: httpx.Client) -> None:
    unknown = client.post(f"{WS}/language-servers/nope/install")
    assert (unknown.status_code, unknown.json()) == (
        409,
        {"detail": "Unknown language server: nope"},
    )
    # a server with no managed installer answers with its manual hint
    manual = client.post(f"{WS}/language-servers/c/install")
    assert manual.status_code == 409
    assert manual.json()["detail"]
    # dismiss is idempotent and never fails, even for an unknown id
    for language in ("nope", "c", "python"):
        response = client.post(f"{WS}/language-servers/{language}/install/dismiss")
        assert response.status_code == 204 and response.content == b""
    assert client.post(f"{WS}/language-servers/..%2Fx/install").status_code == 404


@pytest.mark.skip(
    reason="a known id with its installer (npm, uv, go, ...) on PATH starts a real "
    "package install into the cache and from the network"
)
def test_language_server_install_that_runs_is_skipped() -> None: ...
