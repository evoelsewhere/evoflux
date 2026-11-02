"""``/api/team/workspace/{validate,files/*}``: a coding workspace named by absolute path."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import httpx
import pytest

from ws_helpers import Scrub, same_path, tree

FILES = "/api/team/workspace/files"


def listing(client: httpx.Client, root: Path) -> dict:
    response = client.get(f"{FILES}/list", params={"workspace": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def paths(body: dict) -> list[str]:
    return [item["path"] for item in body["files"]]


def test_validate_returns_the_resolved_folder_and_422_otherwise(
    client: httpx.Client, workspace: Path, tmp_path: Path, scrub: Scrub
) -> None:
    ok = client.get("/api/team/workspace/validate", params={"workspace": str(workspace)})
    assert ok.status_code == 200
    assert same_path(ok.json()["workspace"], workspace)
    assert list(ok.json()) == ["workspace"]

    missing = client.get(
        "/api/team/workspace/validate", params={"workspace": str(tmp_path / "nope")}
    )
    assert missing.status_code == 422
    assert scrub(missing.json()) == {
        "detail": "Workspace does not exist or is not a directory: <tmp>/nope"
    }

    a_file = client.get(
        "/api/team/workspace/validate", params={"workspace": str(workspace / "a.txt")}
    )
    assert a_file.status_code == 422
    assert scrub(a_file.json())["detail"].startswith(
        "Workspace does not exist or is not a directory: "
    )

    absent = client.get("/api/team/workspace/validate")
    assert absent.status_code == 422
    assert absent.json()["detail"][0]["loc"] == ["query", "workspace"]
    assert absent.json()["detail"][0]["type"] == "missing"


def test_validate_has_no_allowlist_any_folder_is_accepted(
    client: httpx.Client, tmp_path: Path
) -> None:
    """Suspected bug S1: the Rust chat workspace is an allowlist; this is not."""
    # tmp_path is outside EVOFLUX_WORKSPACE_DIR and EVOFLUX_WORKSPACE_ROOTS.
    response = client.get("/api/team/workspace/validate", params={"workspace": str(tmp_path)})
    assert response.status_code == 200
    # A relative path resolves against the process cwd, and ~ against HOME.
    relative = client.get("/api/team/workspace/validate", params={"workspace": "."})
    assert relative.status_code == 200
    assert Path(relative.json()["workspace"]).is_absolute()
    tilde = client.get("/api/team/workspace/validate", params={"workspace": "~"})
    assert tilde.status_code == 200
    assert same_path(tilde.json()["workspace"], tmp_path / "home")


def test_list_shape_ordering_and_ignore_rules(
    client: httpx.Client, workspace: Path
) -> None:
    (workspace / ".gitignore").write_text("ignored.txt\nbuildout/\n", encoding="utf-8")
    (workspace / "ignored.txt").write_text("i", encoding="utf-8")
    (workspace / "buildout").mkdir()
    (workspace / "buildout" / "x.txt").write_text("x", encoding="utf-8")
    for skipped in ("node_modules", "dist", "build", ".venv", "venv", "__pycache__"):
        (workspace / skipped).mkdir()
        (workspace / skipped / "f.txt").write_text("f", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (workspace / ".env.example").write_text("K=V\n", encoding="utf-8")
    (workspace / "sub" / "deep").mkdir()
    (workspace / "sub" / "deep" / "c.md").write_text("# c\n", encoding="utf-8")
    (workspace / "noext").write_text("n", encoding="utf-8")
    (workspace / "pic.webp").write_bytes(b"RIFF")

    body = listing(client, workspace)
    assert set(body) == {"workspace", "files", "truncated"}
    assert same_path(body["workspace"], workspace)
    assert body["truncated"] is False
    # Dot files are listed (the @-mention picker policy); .git and the skipped
    # folder names are not; .gitignore is honoured.
    assert paths(body) == [
        ".env.example",
        ".gitignore",
        "a.txt",
        "noext",
        "pic.webp",
        "sub/b.py",
        "sub/deep/c.md",
    ]
    by_path = {item["path"]: item for item in body["files"]}
    assert set(by_path["a.txt"]) == {"path", "name", "size", "mtime", "mime"}
    assert by_path["a.txt"]["size"] == 6
    assert by_path["a.txt"]["name"] == "a.txt"
    assert by_path["a.txt"]["mime"] == "text/plain"
    assert by_path["sub/b.py"]["name"] == "b.py"
    assert by_path["noext"]["mime"] == "application/octet-stream"
    # The listing guesses with mimetypes only (no webp fallback table).
    assert by_path["pic.webp"]["mime"] == (
        mimetypes.guess_type("pic.webp")[0] or "application/octet-stream"
    )
    assert isinstance(by_path["a.txt"]["mtime"], float)


def test_list_skips_a_linked_worktree_and_keeps_a_submodule(
    client: httpx.Client, workspace: Path
) -> None:
    linked = workspace / "wt"
    linked.mkdir()
    (linked / "f.txt").write_text("f", encoding="utf-8")
    (linked / ".git").write_text("gitdir: /repo/.git/worktrees/wt\n", encoding="utf-8")
    sub = workspace / "mod"
    sub.mkdir()
    (sub / "g.txt").write_text("g", encoding="utf-8")
    (sub / ".git").write_text("gitdir: ../.git/modules/mod\n", encoding="utf-8")
    assert paths(listing(client, workspace)) == ["a.txt", "mod/g.txt", "sub/b.py"]


def test_list_caps_at_ten_thousand_files(client: httpx.Client, tmp_path: Path) -> None:
    root = tmp_path / "many"
    root.mkdir()
    for index in range(10_001):
        (root / f"f{index:05d}.txt").write_bytes(b"")
    body = listing(client, root)
    assert body["truncated"] is True
    assert len(body["files"]) == 10_000
    assert body["files"][0]["path"] == "f00000.txt"
    assert body["files"][-1]["path"] == "f09999.txt"


def test_list_422_for_a_missing_folder_and_empty_for_an_empty_one(
    client: httpx.Client, tmp_path: Path
) -> None:
    missing = client.get(f"{FILES}/list", params={"workspace": str(tmp_path / "nope")})
    assert missing.status_code == 422
    empty = tmp_path / "empty"
    empty.mkdir()
    assert listing(client, empty)["files"] == []


def test_read_serves_raw_bytes_with_a_guessed_type(
    client: httpx.Client, workspace: Path
) -> None:
    (workspace / "bin.dat").write_bytes(bytes(range(256)))
    (workspace / "notes.unknownext").write_bytes(b"?")
    inline = client.get(f"{FILES}/read", params={"workspace": str(workspace), "path": "a.txt"})
    assert inline.status_code == 200
    assert inline.content == b"hello\n"
    assert inline.headers["content-type"].startswith("text/plain")
    assert "content-disposition" not in inline.headers
    assert inline.headers["content-length"] == "6"
    assert inline.headers["accept-ranges"] == "bytes"
    assert "etag" in inline.headers and "last-modified" in inline.headers

    download = client.get(
        f"{FILES}/read",
        params={"workspace": str(workspace), "path": "a.txt", "download": "true"},
    )
    assert download.headers["content-disposition"] == 'attachment; filename="a.txt"'

    binary = client.get(f"{FILES}/read", params={"workspace": str(workspace), "path": "bin.dat"})
    assert binary.content == bytes(range(256))
    assert binary.headers["content-type"] == "application/octet-stream"
    unknown = client.get(
        f"{FILES}/read", params={"workspace": str(workspace), "path": "notes.unknownext"}
    )
    assert unknown.headers["content-type"] == "application/octet-stream"

    nested = client.get(f"{FILES}/read", params={"workspace": str(workspace), "path": "sub/b.py"})
    assert nested.content == b"x = 1\n"
    assert nested.headers["content-type"].startswith(
        mimetypes.guess_type("b.py")[0] or "application/octet-stream"
    )


def test_read_errors(client: httpx.Client, workspace: Path, tmp_path: Path) -> None:
    root = str(workspace)
    cases = {
        "nope.txt": (404, "File not found."),
        "sub": (404, "File not found."),
        "": (404, "File not found."),
        ".": (404, "File not found."),
        "sub/../a.txt": (200, None),
    }
    for path, (status, detail) in cases.items():
        response = client.get(f"{FILES}/read", params={"workspace": root, "path": path})
        assert response.status_code == status, path
        if detail:
            assert response.json() == {"detail": detail}, path
    missing_ws = client.get(
        f"{FILES}/read", params={"workspace": str(tmp_path / "nope"), "path": "a.txt"}
    )
    assert missing_ws.status_code == 422
    no_path = client.get(f"{FILES}/read", params={"workspace": root})
    assert no_path.status_code == 422
    assert no_path.json()["detail"][0]["loc"] == ["query", "path"]


def test_write_replaces_content_and_creates_parents(
    client: httpx.Client, workspace: Path
) -> None:
    root = str(workspace)
    response = client.put(
        f"{FILES}/write",
        params={"workspace": root, "path": "new/dir/f.txt"},
        json={"content": "héllo\r\nline2"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    # write_text with encoding utf-8 and no newline argument: on Windows "\n"
    # would become "\r\n"; the content is stored as the platform writes it.
    expected = "héllo\r\nline2".replace("\n", os.linesep) if os.name == "nt" else "héllo\r\nline2"
    assert (workspace / "new" / "dir" / "f.txt").read_bytes() == expected.encode("utf-8")

    again = client.put(
        f"{FILES}/write", params={"workspace": root, "path": "a.txt"}, json={"content": ""}
    )
    assert again.json() == {"ok": True}
    assert (workspace / "a.txt").read_bytes() == b""


def test_write_body_validation(client: httpx.Client, workspace: Path) -> None:
    params = {"workspace": str(workspace), "path": "q.txt"}
    empty = client.put(f"{FILES}/write", params=params, json={})
    assert empty.status_code == 422
    assert empty.json() == {"detail": "Missing 'content' field."}
    non_string = client.put(f"{FILES}/write", params=params, json={"content": 5})
    assert non_string.status_code == 422
    assert non_string.json()["detail"][0]["type"] == "string_type"
    assert non_string.json()["detail"][0]["loc"] == ["body", "content"]
    extra_non_string = client.put(
        f"{FILES}/write", params=params, json={"content": "x", "other": 1}
    )
    assert extra_non_string.status_code == 422
    assert not (workspace / "q.txt").exists()


def test_write_to_the_root_or_a_folder_is_an_unhandled_500(
    client: httpx.Client, workspace: Path
) -> None:
    """Suspected bug B1: the OSError of writing over a folder is not caught."""
    for path in ("", ".", "sub"):
        response = client.put(
            f"{FILES}/write",
            params={"workspace": str(workspace), "path": path},
            json={"content": "x"},
        )
        assert response.status_code == 500, path
        assert response.text == "Internal Server Error"
    assert (workspace / "sub").is_dir()


def test_create_file_and_directory(client: httpx.Client, workspace: Path) -> None:
    root = str(workspace)
    created = client.post(f"{FILES}/create", params={"workspace": root, "path": "x/y/new.txt"})
    assert created.status_code == 200
    assert created.json() == {"path": "x/y/new.txt"}
    assert (workspace / "x" / "y" / "new.txt").read_bytes() == b""

    directory = client.post(
        f"{FILES}/create", params={"workspace": root, "path": "d1/d2", "kind": "directory"}
    )
    assert directory.json() == {"path": "d1/d2"}
    assert (workspace / "d1" / "d2").is_dir()

    exists = client.post(f"{FILES}/create", params={"workspace": root, "path": "a.txt"})
    assert exists.status_code == 409
    assert exists.json() == {"detail": "a.txt already exists."}
    assert (workspace / "a.txt").read_bytes() == b"hello\n"

    bad_kind = client.post(
        f"{FILES}/create", params={"workspace": root, "path": "k", "kind": "link"}
    )
    assert bad_kind.status_code == 422
    assert bad_kind.json() == {"detail": "kind must be file or directory."}

    # A path with backslashes is one nested path on Windows only.
    if os.name == "nt":
        nested = client.post(
            f"{FILES}/create", params={"workspace": root, "path": "w1\\w2.txt"}
        )
        assert nested.json() == {"path": "w1/w2.txt"}


def test_move_rename_and_errors(client: httpx.Client, workspace: Path) -> None:
    root = str(workspace)

    def move(src: str, dest: str) -> httpx.Response:
        return client.post(
            f"{FILES}/move", params={"workspace": root}, json={"from_path": src, "to_path": dest}
        )

    assert move("a.txt", "moved/deep/a2.txt").json() == {"ok": True}
    assert (workspace / "moved" / "deep" / "a2.txt").read_bytes() == b"hello\n"
    assert not (workspace / "a.txt").exists()

    same = move("moved/deep/a2.txt", "moved/deep/a2.txt")
    assert same.status_code == 200 and same.json() == {"ok": True}

    missing = move("zzz", "q")
    assert (missing.status_code, missing.json()) == (404, {"detail": "File not found."})

    (workspace / "taken.txt").write_text("t", encoding="utf-8")
    taken = move("moved/deep/a2.txt", "taken.txt")
    assert (taken.status_code, taken.json()) == (409, {"detail": "taken.txt already exists."})

    into_self = move("sub", "sub/inner/sub")
    assert (into_self.status_code, into_self.json()) == (
        400,
        {"detail": "Cannot move a folder into itself."},
    )
    folder = move("sub", "renamed")
    assert folder.json() == {"ok": True}
    assert (workspace / "renamed" / "b.py").is_file()


def test_move_and_copy_check_the_source_before_the_destination(
    client: httpx.Client, workspace: Path
) -> None:
    """Pins the validation order: both paths are resolved first, then existence."""
    root = str(workspace)
    both_bad = client.post(
        f"{FILES}/move",
        params={"workspace": root},
        json={"from_path": "../x", "to_path": "../y"},
    )
    assert both_bad.status_code == 400
    assert both_bad.json() == {"detail": "Path must not traverse upward."}
    missing_and_bad = client.post(
        f"{FILES}/move",
        params={"workspace": root},
        json={"from_path": "nope", "to_path": "../y"},
    )
    # coding routes resolve the destination before checking the source exists
    assert missing_and_bad.status_code == 400
    body_errors = client.post(f"{FILES}/move", params={"workspace": root}, json={"from_path": "a"})
    assert body_errors.status_code == 422
    assert body_errors.json()["detail"][0]["loc"] == ["body", "to_path"]


def test_copy_file_and_folder(client: httpx.Client, workspace: Path) -> None:
    root = str(workspace)

    def copy(src: str, dest: str) -> httpx.Response:
        return client.post(
            f"{FILES}/copy", params={"workspace": root}, json={"from_path": src, "to_path": dest}
        )

    assert copy("a.txt", "out/a-copy.txt").json() == {"ok": True}
    assert (workspace / "out" / "a-copy.txt").read_bytes() == b"hello\n"
    assert (workspace / "a.txt").exists()
    assert copy("sub", "sub-copy").json() == {"ok": True}
    assert (workspace / "sub-copy" / "b.py").read_bytes() == b"x = 1\n"

    taken = copy("a.txt", "sub/b.py")
    assert (taken.status_code, taken.json()) == (409, {"detail": "b.py already exists."})
    into_self = copy("sub", "sub/again")
    assert (into_self.status_code, into_self.json()) == (
        400,
        {"detail": "Cannot copy a folder into itself."},
    )
    missing = copy("nope", "q")
    assert (missing.status_code, missing.json()) == (404, {"detail": "File not found."})
    # Unlike move, a copy onto the source path is a conflict, not a no-op.
    onto_self = copy("a.txt", "a.txt")
    assert onto_self.status_code == 409


def test_delete_file_folder_and_errors(client: httpx.Client, workspace: Path) -> None:
    root = str(workspace)
    ok = client.delete(f"{FILES}/entry", params={"workspace": root, "path": "a.txt"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    assert not (workspace / "a.txt").exists()

    no_flag = client.delete(f"{FILES}/entry", params={"workspace": root, "path": "sub"})
    assert (no_flag.status_code, no_flag.json()) == (
        400,
        {"detail": "Directory delete requires recursive=true."},
    )
    assert (workspace / "sub" / "b.py").exists()
    recursive = client.delete(
        f"{FILES}/entry", params={"workspace": root, "path": "sub", "recursive": "true"}
    )
    assert recursive.json() == {"ok": True}
    assert not (workspace / "sub").exists()

    missing = client.delete(f"{FILES}/entry", params={"workspace": root, "path": "zzz"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "File not found."})
    the_root = client.delete(
        f"{FILES}/entry", params={"workspace": root, "path": ".", "recursive": "true"}
    )
    assert (the_root.status_code, the_root.json()) == (
        400,
        {"detail": "Path must name an entry."},
    )
    assert workspace.is_dir()


def test_mutations_leave_unrelated_files_alone(
    client: httpx.Client, workspace: Path
) -> None:
    before = tree(workspace)
    client.post(f"{FILES}/create", params={"workspace": str(workspace), "path": "n.txt"})
    after = tree(workspace)
    assert {k: v for k, v in after.items() if k != "n.txt"} == before
    assert after["n.txt"] == b""


def test_dot_env_is_readable_and_writable_with_no_deny_list(
    client: httpx.Client, workspace: Path
) -> None:
    """Suspected bug S4: the Rust tools deny ``**/.env`` and ``**/.env.*``; these routes do not."""
    root = str(workspace)
    (workspace / ".env").write_text("API_KEY=sk-test\n", encoding="utf-8", newline="")
    read = client.get(f"{FILES}/read", params={"workspace": root, "path": ".env"})
    assert read.status_code == 200
    assert read.content == b"API_KEY=sk-test\n"
    write = client.put(
        f"{FILES}/write", params={"workspace": root, "path": ".env.local"}, json={"content": "K=1"}
    )
    assert write.status_code == 200
    git_config = client.put(
        f"{FILES}/write", params={"workspace": root, "path": ".git/config"}, json={"content": ""}
    )
    assert git_config.status_code == 200
    assert (workspace / ".git" / "config").is_file()


def test_preview_checks_the_path_like_read(
    client: httpx.Client, workspace: Path, tmp_path: Path
) -> None:
    root = str(workspace)
    escape = client.get(f"{FILES}/preview", params={"workspace": root, "path": "../x"})
    assert (escape.status_code, escape.json()) == (400, {"detail": "Path escapes workspace root."})
    missing = client.get(f"{FILES}/preview", params={"workspace": root, "path": "zzz"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "File not found."})
    bad_ws = client.get(
        f"{FILES}/preview", params={"workspace": str(tmp_path / "nope"), "path": "a.txt"}
    )
    assert bad_ws.status_code == 422
    # A plain text file is not a document the viewer engine renders.
    unsupported = client.get(f"{FILES}/preview", params={"workspace": root, "path": "a.txt"})
    assert unsupported.status_code == 415
