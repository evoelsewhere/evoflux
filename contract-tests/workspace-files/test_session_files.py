"""``/api/team/{session_id}/{files,workspace,uploads}``: a folder named by session.

A Work session's folder is ``<EVOFLUX_WORKSPACE_DIR>/<session id>``; a session
whose ``workspace`` is set uses that folder instead. A session id only has to be
a UUID: no row is required for the file routes.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest

from ws_helpers import Scrub, make_dir_link, make_file_symlink, remove_dir_link, same_path, tree

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows path rules")


def upload(
    client: httpx.Client,
    sid: str,
    name: str,
    data: bytes = b"data",
    subfolder: str | None = None,
) -> httpx.Response:
    return client.post(
        f"/api/team/{sid}/files/upload",
        params={"subfolder": subfolder} if subfolder is not None else None,
        files=[("files", (name, data, "application/octet-stream"))],
    )


def listed(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["path"] for item in response.json()["files"]]


def test_files_listing_of_an_unused_session_is_empty_with_a_root(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    response = client.get(f"/api/team/{session_id}/files")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"session_id", "files", "truncated", "workspace_root"}
    assert body["session_id"] == session_id
    assert body["files"] == [] and body["truncated"] is False
    assert same_path(body["workspace_root"], session_dir)
    # listing does not create the folder
    assert not session_dir.exists()


def test_workspace_root_route_and_invalid_ids(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    body = client.get(f"/api/team/{session_id}/workspace").json()
    assert set(body) == {"session_id", "workspace_root"}
    assert same_path(body["workspace_root"], session_dir)
    for method, path in (
        ("GET", "/api/team/not-a-uuid/files"),
        ("GET", "/api/team/not-a-uuid/workspace"),
        ("GET", "/api/team/not-a-uuid/uploads/a.png"),
        ("POST", "/api/team/not-a-uuid/files/create?path=a"),
        ("DELETE", "/api/team/not-a-uuid/files/a"),
    ):
        response = client.request(method, path)
        assert response.status_code == 400, path
        assert response.json() == {"detail": "Invalid session id."}
    bad_put = client.put("/api/team/not-a-uuid/workspace", json={"path": None})
    assert bad_put.status_code == 400
    assert bad_put.json() == {"detail": "Invalid session id."}


def test_a_session_without_a_row_still_gets_a_folder(
    client: httpx.Client, workspace_root: Path
) -> None:
    ghost = str(uuid.uuid4())
    assert client.get(f"/api/team/{ghost}/files").json()["files"] == []
    assert listed(upload(client, ghost, "g.txt")) == ["g.txt"]
    assert (workspace_root / ghost / "g.txt").read_bytes() == b"data"
    put = client.put(f"/api/team/{ghost}/workspace", json={"path": None})
    assert (put.status_code, put.json()) == (404, {"detail": "Session not found."})


def test_put_workspace_sets_resets_and_creates_the_folder(
    client: httpx.Client, session_id: str, session_dir: Path, tmp_path: Path
) -> None:
    custom = tmp_path / "custom" / "deep"
    (tmp_path / "custom").mkdir()
    response = client.put(f"/api/team/{session_id}/workspace", json={"path": str(custom)})
    assert response.status_code == 200
    assert custom.is_dir()  # created, with parents
    body = response.json()
    assert body["files"] == [] and same_path(body["workspace_root"], custom)
    assert same_path(client.get(f"/api/team/{session_id}/workspace").json()["workspace_root"], custom)

    (custom / "f.txt").write_text("f", encoding="utf-8")
    assert listed(client.get(f"/api/team/{session_id}/files")) == ["f.txt"]

    reset = client.put(f"/api/team/{session_id}/workspace", json={"path": None})
    assert same_path(reset.json()["workspace_root"], session_dir)
    # an omitted path is the same as null
    client.put(f"/api/team/{session_id}/workspace", json={"path": str(custom)})
    omitted = client.put(f"/api/team/{session_id}/workspace", json={})
    assert same_path(omitted.json()["workspace_root"], session_dir)


def test_put_workspace_errors(
    client: httpx.Client, session_id: str, tmp_path: Path, scrub: Scrub
) -> None:
    for bad in ("relative", "", "."):
        response = client.put(f"/api/team/{session_id}/workspace", json={"path": bad})
        assert response.status_code == 400, bad
        assert response.json() == {"detail": "Workspace path must be absolute."}
    a_file = tmp_path / "plain.txt"
    a_file.write_text("x", encoding="utf-8")
    response = client.put(f"/api/team/{session_id}/workspace", json={"path": str(a_file)})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Cannot create directory: ")
    wrong_type = client.put(f"/api/team/{session_id}/workspace", json={"path": 5})
    assert wrong_type.status_code == 422
    # the failed calls changed nothing
    assert client.get(f"/api/team/{session_id}/workspace").status_code == 200


@WINDOWS
def test_put_workspace_unc_that_cannot_be_created_is_a_400(
    client: httpx.Client, session_id: str
) -> None:
    response = client.put(
        f"/api/team/{session_id}/workspace",
        json={"path": "\\\\nonexistent.invalid\\share\\x"},
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Cannot create directory: ")


def test_put_workspace_has_no_allowlist_and_creates_any_folder(
    client: httpx.Client, session_id: str, tmp_path: Path
) -> None:
    """Suspected bug S1: any absolute folder is created and adopted.

    The Rust chat workspace only accepts ``EVOFLUX_WORKSPACE_DIR`` and
    ``EVOFLUX_WORKSPACE_ROOTS`` folders; this route (and ``~`` expansion)
    accepts everything and ``mkdir -p``s it first.
    """
    elsewhere = tmp_path / "elsewhere" / "a" / "b"
    response = client.put(f"/api/team/{session_id}/workspace", json={"path": str(elsewhere)})
    assert response.status_code == 200
    assert elsewhere.is_dir()
    tilde = client.put(f"/api/team/{session_id}/workspace", json={"path": "~/from-tilde"})
    assert tilde.status_code == 200
    assert (tmp_path / "home" / "from-tilde").is_dir()
    # a path with .. is resolved, not refused
    dotted = tmp_path / "elsewhere" / "a" / ".." / "c"
    response = client.put(f"/api/team/{session_id}/workspace", json={"path": str(dotted)})
    assert response.status_code == 200
    assert (tmp_path / "elsewhere" / "c").is_dir()
    assert same_path(response.json()["workspace_root"], tmp_path / "elsewhere" / "c")


def test_session_file_mutations(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    base = f"/api/team/{session_id}/files"
    created = client.post(f"{base}/create", params={"path": "x/y.txt"})
    assert created.status_code == 200
    assert [i["path"] for i in created.json()["files"]] == ["x/y.txt"]
    assert created.json()["files"][0]["size"] == 0
    d = client.post(f"{base}/create", params={"path": "kd", "kind": "directory"})
    assert (session_dir / "kd").is_dir()
    assert [i["path"] for i in d.json()["files"]] == ["x/y.txt"]  # empty folders are not listed
    assert client.post(f"{base}/create", params={"path": "x/y.txt"}).json() == {
        "detail": "y.txt already exists."
    }
    assert client.post(f"{base}/create", params={"path": "k", "kind": "zz"}).json() == {
        "detail": "kind must be file or directory."
    }
    # kind is checked after the session id and before the path
    assert client.post(f"{base}/create", params={"path": "../k", "kind": "zz"}).status_code == 422

    moved = client.post(f"{base}/move", json={"from_path": "x/y.txt", "to_path": "z.txt"})
    assert [i["path"] for i in moved.json()["files"]] == ["z.txt"]
    same = client.post(f"{base}/move", json={"from_path": "z.txt", "to_path": "z.txt"})
    assert same.status_code == 200
    # the source is checked before the destination here
    missing = client.post(f"{base}/move", json={"from_path": "nope", "to_path": "../q"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "File not found."})
    bad_dest = client.post(f"{base}/move", json={"from_path": "z.txt", "to_path": "../q"})
    assert bad_dest.json() == {"detail": "Path must not traverse upward."}
    taken = client.post(f"{base}/copy", json={"from_path": "z.txt", "to_path": "z.txt"})
    assert (taken.status_code, taken.json()) == (409, {"detail": "z.txt already exists."})
    copied = client.post(f"{base}/copy", json={"from_path": "z.txt", "to_path": "c/z2.txt"})
    assert [i["path"] for i in copied.json()["files"]] == ["z.txt", "c/z2.txt"]  # a folder's files come before its sub-folders
    into = client.post(f"{base}/copy", json={"from_path": "c", "to_path": "c/c2"})
    assert into.json() == {"detail": "Cannot copy a folder into itself."}

    no_flag = client.delete(f"{base}/c")
    assert no_flag.json() == {"detail": "Directory delete requires recursive=true."}
    gone = client.delete(f"{base}/c", params={"recursive": "true"})
    assert [i["path"] for i in gone.json()["files"]] == ["z.txt"]
    assert client.delete(f"{base}/z.txt").status_code == 200
    assert client.delete(f"{base}/z.txt").json() == {"detail": "File not found."}
    for path in ("..%2Fesc.txt", "a%2F..%2F..%2Fx"):
        refused = client.delete(f"{base}/{path}")
        assert (refused.status_code, refused.json()) == (
            400,
            {"detail": "Path must not traverse upward."},
        )


def test_session_routes_with_a_custom_workspace_use_that_folder(
    client: httpx.Client, session_id: str, session_dir: Path, tmp_path: Path
) -> None:
    custom = tmp_path / "proj"
    custom.mkdir()
    (custom / "readme.md").write_text("# hi\n", encoding="utf-8")
    client.put(f"/api/team/{session_id}/workspace", json={"path": str(custom)})
    assert listed(client.get(f"/api/team/{session_id}/files")) == ["readme.md"]
    assert listed(upload(client, session_id, "up.txt")) == ["readme.md", "up.txt"]
    assert (custom / "up.txt").is_file() and not session_dir.exists()
    client.post(f"/api/team/{session_id}/files/create", params={"path": "n.txt"})
    assert (custom / "n.txt").is_file()
    # uploads/ is NOT redirected: it stays under EVOFLUX_WORKSPACE_DIR/<id>
    (custom / "uploads").mkdir()
    (custom / "uploads" / "in-repo.png").write_bytes(b"png")
    assert client.get(f"/api/team/{session_id}/uploads/in-repo.png").status_code == 404


# ── uploads: POST /files/upload ───────────────────────────────────────────────


def test_upload_writes_into_the_workspace_root(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    response = upload(client, session_id, "hi.txt", b"hello")
    assert response.status_code == 200
    body = response.json()
    assert body["files"][0]["size"] == 5 and body["files"][0]["mime"] == "text/plain"
    assert (session_dir / "hi.txt").read_bytes() == b"hello"
    # the listing is of the whole workspace, not of this upload alone
    assert listed(upload(client, session_id, "zz.txt")) == ["hi.txt", "zz.txt"]
    # an upload replaces a same-named file without asking
    assert upload(client, session_id, "hi.txt", b"new").status_code == 200
    assert (session_dir / "hi.txt").read_bytes() == b"new"


def test_upload_several_files_in_one_request_last_duplicate_wins(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    response = client.post(
        f"/api/team/{session_id}/files/upload",
        files=[
            ("files", ("one.txt", b"1", "text/plain")),
            ("files", ("two.txt", b"22", "text/plain")),
            ("files", ("one.txt", b"333", "text/plain")),
        ],
    )
    assert listed(response) == ["one.txt", "two.txt"]
    assert (session_dir / "one.txt").read_bytes() == b"333"


def test_upload_subfolder_and_name_cases(
    client: httpx.Client, session_id: str, session_dir: Path, tmp_path: Path
) -> None:
    ok = upload(client, session_id, "../evil.txt", subfolder="d/e")
    # only the final name component is used, so the traversal in the name is dropped
    assert "d/e/evil.txt" in listed(ok)
    assert not (session_dir / "evil.txt").exists() and not (session_dir.parent / "evil.txt").exists()
    # "." and ".." names are skipped silently
    before = tree(session_dir)
    for name in ("..", "."):
        assert upload(client, session_id, name).status_code == 200
    assert tree(session_dir) == before
    # a path in the name keeps the last component only
    assert "dd.txt" in listed(upload(client, session_id, "sub/../dd.txt"))
    assert "abs.txt" in listed(upload(client, session_id, "/etc/abs.txt"))
    assert "uni-ünï.txt" in listed(upload(client, session_id, "uni-ünï.txt"))
    assert "with space.txt" in listed(upload(client, session_id, "with space.txt"))
    # an empty body is a valid file
    assert "empty.txt" in listed(upload(client, session_id, "empty.txt", b""))
    assert (session_dir / "empty.txt").read_bytes() == b""
    # "." as the subfolder is the root
    assert "dot-sub.txt" in listed(upload(client, session_id, "dot-sub.txt", subfolder="."))
    assert (session_dir / "dot-sub.txt").is_file()
    assert not (tmp_path / "evil.txt").exists()


def test_upload_subfolder_refusals(
    client: httpx.Client, session_id: str, session_dir: Path, outside: Path
) -> None:
    before = tree(outside)
    for sub in ("../d", "a/../../d", str(outside)):
        response = upload(client, session_id, "x.txt", subfolder=sub)
        assert response.status_code == 400, sub
        assert response.json() == {"detail": "Invalid subfolder path."}
    assert tree(outside) == before
    assert not (session_dir.parent / "d").exists()
    # an inner ".." that stays inside is refused too (any ".." part)
    inner = upload(client, session_id, "x.txt", subfolder="a/../b")
    assert inner.json() == {"detail": "Invalid subfolder path."}
    # the workspace folder is created by the failed call before the refusal
    assert session_dir.is_dir()


def test_upload_subfolder_through_a_link_that_leaves_the_workspace(
    client: httpx.Client, session_id: str, session_dir: Path, outside: Path
) -> None:
    session_dir.mkdir(parents=True)
    link = session_dir / "jn"
    if not make_dir_link(link, outside):
        pytest.skip("cannot create a directory link on this machine")
    try:
        before = tree(outside)
        response = upload(client, session_id, "x.txt", subfolder="jn")
        assert (response.status_code, response.json()) == (
            400,
            {"detail": "Subfolder escapes workspace root."},
        )
        assert tree(outside) == before
    finally:
        remove_dir_link(link)


def test_upload_needs_a_file_part(client: httpx.Client, session_id: str) -> None:
    response = client.post(f"/api/team/{session_id}/files/upload")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "files"]
    only_field = client.post(
        f"/api/team/{session_id}/files/upload", data={"files": "not-a-file"}
    )
    assert only_field.status_code == 422


def test_upload_has_no_size_limit(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    """Suspected bug S5: the whole part is read into memory and written; no cap."""
    big = b"a" * (12 * 1024 * 1024)
    response = upload(client, session_id, "big.bin", big)
    assert response.status_code == 200
    assert (session_dir / "big.bin").stat().st_size == len(big)
    entry = next(i for i in response.json()["files"] if i["path"] == "big.bin")
    assert entry["size"] == len(big)


@WINDOWS
def test_upload_names_windows_rewrites(
    client: httpx.Client, session_id: str, session_dir: Path, outside: Path
) -> None:
    """Suspected bug B3: names are not normalised, so Windows picks another file."""
    before = tree(outside)
    assert "a.txt" in listed(upload(client, session_id, "a.txt", b"first"))
    # a stream name writes the default stream of the real file
    assert "a.txt" in listed(upload(client, session_id, "a.txt::$DATA", b"second"))
    assert (session_dir / "a.txt").read_bytes() == b"second"
    # a trailing dot or space is stripped
    names = listed(upload(client, session_id, "dot."))
    assert "dot" in names and "dot." not in names
    assert "sp" in listed(upload(client, session_id, "sp "))
    # a backslash path keeps its last component on Windows
    assert "up.txt" in listed(upload(client, session_id, "..\\up.txt"))
    assert "abs2.txt" in listed(upload(client, session_id, "C:\\x\\abs2.txt"))
    # an over-long name is a 500 after earlier files of the request were written
    long_name = "x" * 300 + ".txt"
    failed = client.post(
        f"/api/team/{session_id}/files/upload",
        files=[
            ("files", ("early.txt", b"e", "text/plain")),
            ("files", (long_name, b"l", "text/plain")),
        ],
    )
    assert failed.status_code == 500
    assert failed.json()["detail"].startswith(f"Write failed for {long_name}: ")
    assert (session_dir / "early.txt").read_bytes() == b"e"  # not rolled back
    assert tree(outside) == before


# ── GET /uploads/{filename} ──────────────────────────────────────────────────


def put_upload(workspace_root: Path, sid: str, name: str, data: bytes) -> Path:
    folder = workspace_root / sid / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def test_get_uploaded_file_headers_and_types(
    client: httpx.Client, session_id: str, workspace_root: Path
) -> None:
    put_upload(workspace_root, session_id, "f.png", b"\x89PNG")
    put_upload(workspace_root, session_id, "f.webp", b"RIFF")
    put_upload(workspace_root, session_id, "f.wasm", b"\x00asm")
    put_upload(workspace_root, session_id, "f.avif", b"avif")
    put_upload(workspace_root, session_id, "f.zzz", b"?")
    png = client.get(f"/api/team/{session_id}/uploads/f.png")
    assert png.status_code == 200 and png.content == b"\x89PNG"
    assert png.headers["content-type"] == "image/png"
    # always an attachment, unlike the /media proxy
    assert png.headers["content-disposition"] == 'attachment; filename="f.png"'
    # the modern types the Windows registry may lack come from a fallback table
    assert client.get(f"/api/team/{session_id}/uploads/f.webp").headers["content-type"] == "image/webp"
    assert client.get(f"/api/team/{session_id}/uploads/f.wasm").headers["content-type"] == "application/wasm"
    assert client.get(f"/api/team/{session_id}/uploads/f.avif").headers["content-type"] == "image/avif"
    assert client.get(f"/api/team/{session_id}/uploads/f.zzz").headers["content-type"] == "application/octet-stream"


def test_get_uploaded_file_errors(
    client: httpx.Client, session_id: str, workspace_root: Path
) -> None:
    put_upload(workspace_root, session_id, "ok.txt", b"ok")
    (workspace_root / session_id / "uploads" / "dir").mkdir()
    cases = {
        "missing.png": (404, "Media file not found."),
        "dir": (404, "Media file not found."),
        "%2e": (400, "Invalid upload filename."),
        "a%5Cb": (400, "Invalid upload filename."),
        "%2e%2e": (400, "Invalid upload filename."),
    }
    for name, (status, detail) in cases.items():
        response = client.get(f"/api/team/{session_id}/uploads/{name}")
        assert (response.status_code, response.json()) == (status, {"detail": detail}), name
    # a slash never reaches the handler: the route has no path converter
    assert client.get(f"/api/team/{session_id}/uploads/a%2Fb").status_code == 404
    assert client.get(f"/api/team/{session_id}/uploads/a/b").status_code == 404
    # the session id is checked first
    assert client.get("/api/team/zzz/uploads/ok.txt").json() == {"detail": "Invalid session id."}
    # a session whose folder does not exist is a plain 404
    other = str(uuid.uuid4())
    assert client.get(f"/api/team/{other}/uploads/ok.txt").status_code == 404


@WINDOWS
def test_get_uploaded_file_windows_names_open_the_same_file(
    client: httpx.Client, session_id: str, workspace_root: Path
) -> None:
    """Suspected bug B3: ``f.png.``, ``f.png%20`` and ``f.png::$DATA`` all serve f.png."""
    put_upload(workspace_root, session_id, "f.png", b"\x89PNG")
    for name in ("f.png.", "f.png%20", "f.png::$DATA"):
        response = client.get(f"/api/team/{session_id}/uploads/{name}")
        assert response.status_code == 200, name
        assert response.content == b"\x89PNG"


def test_get_uploaded_file_refuses_a_link_that_leaves_the_folder(
    client: httpx.Client, session_id: str, workspace_root: Path, outside: Path
) -> None:
    folder = workspace_root / session_id / "uploads"
    folder.mkdir(parents=True)
    if not make_file_symlink(folder / "lnk.txt", outside / "secret.txt"):
        pytest.skip("creating a file symlink needs a privilege this account lacks")
    response = client.get(f"/api/team/{session_id}/uploads/lnk.txt")
    assert (response.status_code, response.json()) == (
        400,
        {"detail": "Media path escapes session root."},
    )


def test_session_folder_listing_matches_what_was_written(
    client: httpx.Client, session_id: str, session_dir: Path
) -> None:
    session_dir.mkdir(parents=True)
    (session_dir / "uploads").mkdir()
    (session_dir / "uploads" / "att.png").write_bytes(b"x")
    (session_dir / "out").mkdir()
    (session_dir / "out" / "chart.png").write_bytes(b"y")
    # the attachment folder is part of the workspace, so it is listed too
    assert listed(client.get(f"/api/team/{session_id}/files")) == [
        "out/chart.png",
        "uploads/att.png",
    ]
