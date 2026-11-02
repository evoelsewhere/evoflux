"""Path confinement of the coding-workspace routes: what escapes, what does not.

Every case runs against a temp workspace with a sibling ``outside`` folder that
holds ``secret.txt``. A case passes when Python's answer is the pinned one;
the invariant checks (nothing created or changed outside the workspace) run
for every case. Cases marked "suspected bug" pin behaviour a Rust port should
not copy blindly; they are listed in NOTES.md.

UNC paths are only ever sent to routes that reject them before touching the
file system, and with a host name that cannot resolve.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from ws_helpers import (
    make_dir_link,
    make_file_symlink,
    remove_dir_link,
    same_path,
    tree,
)

FILES = "/api/team/workspace/files"
UNC = "\\\\nonexistent.invalid\\share\\x"
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows path rules")


def snapshot_outside(outside: Path) -> dict[str, bytes | None]:
    return tree(outside)


def read(client: httpx.Client, root: Path, path: str) -> httpx.Response:
    return client.get(f"{FILES}/read", params={"workspace": str(root), "path": path})


def write(client: httpx.Client, root: Path, path: str) -> httpx.Response:
    return client.put(
        f"{FILES}/write", params={"workspace": str(root), "path": path}, json={"content": "PWN"}
    )


def create(client: httpx.Client, root: Path, path: str) -> httpx.Response:
    return client.post(f"{FILES}/create", params={"workspace": str(root), "path": path})


def delete(client: httpx.Client, root: Path, path: str, recursive: bool = False) -> httpx.Response:
    return client.delete(
        f"{FILES}/entry",
        params={"workspace": str(root), "path": path, "recursive": str(recursive).lower()},
    )


def test_parent_traversal_per_route(
    client: httpx.Client, workspace: Path, outside: Path, tmp_path: Path
) -> None:
    before = snapshot_outside(outside)
    escaping = ["../outside/secret.txt", "sub/../../outside/secret.txt"]
    if os.name == "nt":
        escaping.append("..\\outside\\secret.txt")
    for path in escaping:
        # read and write only test containment of the resolved path ...
        assert read(client, workspace, path).status_code == 400, path
        assert read(client, workspace, path).json() == {"detail": "Path escapes workspace root."}
        assert write(client, workspace, path).status_code == 400
        assert write(client, workspace, path).json() == {"detail": "Path escapes workspace root."}
    # ... while the entry routes also refuse any ".." component outright
    # (the second case is a backslash path, so POSIX sees one odd file name).
    for path in ("../x", "sub/../x", "a/../../x"):
        for response in (
            create(client, workspace, path),
            delete(client, workspace, path),
        ):
            assert response.status_code == 400, path
            assert response.json() == {"detail": "Path must not traverse upward."}
        move = client.post(
            f"{FILES}/move",
            params={"workspace": str(workspace)},
            json={"from_path": "a.txt", "to_path": path},
        )
        assert move.json() == {"detail": "Path must not traverse upward."}
        copy = client.post(
            f"{FILES}/copy",
            params={"workspace": str(workspace)},
            json={"from_path": path, "to_path": "z"},
        )
        assert copy.json() == {"detail": "Path must not traverse upward."}
    assert snapshot_outside(outside) == before
    assert (workspace / "a.txt").exists()
    assert not (tmp_path / "x").exists()


def test_dotdot_that_stays_inside_is_allowed_on_read_and_write_only(
    client: httpx.Client, workspace: Path
) -> None:
    assert read(client, workspace, "sub/../a.txt").content == b"hello\n"
    assert write(client, workspace, "sub/../w.txt").json() == {"ok": True}
    assert (workspace / "w.txt").is_file()
    # the entry routes refuse the same spelling
    assert create(client, workspace, "sub/../c.txt").status_code == 400
    assert not (workspace / "c.txt").exists()


def test_absolute_paths_per_route(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    before = snapshot_outside(outside)
    target = str(outside / "secret.txt")
    # Python's read and write catch the escape only through the containment
    # check; the entry routes have two different messages for a rooted path.
    assert read(client, workspace, target).json() == {"detail": "Path escapes workspace root."}
    assert write(client, workspace, target).json() == {"detail": "Path escapes workspace root."}
    if os.name == "nt":
        # a drive-qualified path hits the early drive-letter rule
        assert create(client, workspace, target).json() == {"detail": "Path must be relative."}
        assert delete(client, workspace, target).json() == {"detail": "Path must be relative."}
    assert create(client, workspace, "/abs-new.txt").status_code == 400
    assert delete(client, workspace, "/secret.txt").status_code == 400
    assert snapshot_outside(outside) == before
    assert not Path("/abs-new.txt").exists()


def test_empty_and_root_paths(client: httpx.Client, workspace: Path) -> None:
    assert create(client, workspace, "").json() == {"detail": "Empty path."}
    assert create(client, workspace, "   ").json() == {"detail": "Empty path."}
    assert create(client, workspace, ".").json() == {"detail": "Path must name an entry."}
    assert delete(client, workspace, "").json() == {"detail": "Empty path."}
    assert read(client, workspace, "").status_code == 404
    assert read(client, workspace, ".").status_code == 404


@WINDOWS
def test_drive_relative_and_drive_absolute_paths(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    before = snapshot_outside(outside)
    drive = str(workspace)[:2]  # "C:"
    # A drive-absolute path to a different place is refused ...
    assert read(client, workspace, f"{drive}\\Windows\\win.ini").status_code == 400
    assert write(client, workspace, f"{drive}\\w.txt").status_code == 400
    assert create(client, workspace, f"{drive}\\w.txt").json() == {"detail": "Path must be relative."}
    # ... but the entry routes refuse every "X:" prefix, including a drive-relative one
    assert create(client, workspace, "C:rel.txt").json() == {"detail": "Path must be relative."}
    assert create(client, workspace, "Z:rel.txt").json() == {"detail": "Path must be relative."}
    # read and write have no such rule: "C:name" on the workspace's own drive
    # is joined as a relative path, so it lands inside the workspace.
    # Suspected bug B2: an inconsistent rule, harmless here, a different file
    # name from the one the caller sent.
    assert write(client, workspace, f"{drive}w-driverel.txt").json() == {"ok": True}
    assert (workspace / "w-driverel.txt").read_bytes().strip() == b"PWN"
    assert read(client, workspace, f"{drive}a.txt").content == b"hello\n"
    assert read(client, workspace, f"{drive}nope.txt").status_code == 404
    assert snapshot_outside(outside) == before


@WINDOWS
def test_unc_paths_are_refused_without_a_network_round_trip(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    before = snapshot_outside(outside)
    assert read(client, workspace, UNC).status_code == 400
    assert write(client, workspace, UNC).status_code == 400
    assert create(client, workspace, UNC).json() == {"detail": "Path must be relative."}
    assert delete(client, workspace, UNC).json() == {"detail": "Path must be relative."}
    assert snapshot_outside(outside) == before


@WINDOWS
def test_trailing_dot_and_space_names_collapse_on_windows(
    client: httpx.Client, workspace: Path
) -> None:
    """Suspected bug B3: names Windows rewrites are accepted, so the file
    created differs from the name sent, and one name can address another file."""
    # read: "a.txt." and "a.txt " open a.txt
    assert read(client, workspace, "a.txt.").content == b"hello\n"
    assert read(client, workspace, "a.txt ").content == b"hello\n"
    # alternate data stream syntax opens the default stream of a.txt
    assert read(client, workspace, "a.txt::$DATA").content == b"hello\n"
    # write: the trailing dot/space is stripped by Win32
    assert write(client, workspace, "w1.txt.").json() == {"ok": True}
    assert write(client, workspace, "w2.txt ").json() == {"ok": True}
    assert (workspace / "w1.txt").is_file() and (workspace / "w2.txt").is_file()
    # create reports the name it was given, not the one it made
    created = create(client, workspace, "c1.txt.")
    assert created.json() == {"path": "c1.txt."}
    assert (workspace / "c1.txt").is_file()
    # delete addresses the file the same way
    assert delete(client, workspace, "c1.txt.").json() == {"ok": True}
    assert not (workspace / "c1.txt").exists()


@WINDOWS
def test_reserved_device_names_do_not_escape(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    before = snapshot_outside(outside)
    for name in ("nul", "con", "aux", "prn", "com1", "lpt1"):
        response = read(client, workspace, name)
        assert response.status_code == 404, name
    assert snapshot_outside(outside) == before


def test_dir_link_to_outside_is_refused_on_every_route(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    link = workspace / "jn"
    if not make_dir_link(link, outside):
        pytest.skip("cannot create a directory link on this machine")
    try:
        before = snapshot_outside(outside)
        for response in (
            read(client, workspace, "jn/secret.txt"),
            read(client, workspace, "jn"),
            write(client, workspace, "jn/new.txt"),
            create(client, workspace, "jn/c.txt"),
            delete(client, workspace, "jn/secret.txt"),
            delete(client, workspace, "jn", recursive=True),
        ):
            assert response.status_code == 400
            assert response.json() == {"detail": "Path escapes workspace root."}
        copy = client.post(
            f"{FILES}/copy",
            params={"workspace": str(workspace)},
            json={"from_path": "jn/secret.txt", "to_path": "stolen.txt"},
        )
        assert copy.status_code == 400
        move = client.post(
            f"{FILES}/move",
            params={"workspace": str(workspace)},
            json={"from_path": "a.txt", "to_path": "jn/a.txt"},
        )
        assert move.status_code == 400
        assert snapshot_outside(outside) == before
        assert not (workspace / "stolen.txt").exists()
        # the listing does not follow the link either
        listing = client.get(f"{FILES}/list", params={"workspace": str(workspace)}).json()
        assert [f["path"] for f in listing["files"]] == ["a.txt", "sub/b.py"]
    finally:
        remove_dir_link(link)
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "SECRET"


def test_dir_link_inside_the_workspace_is_followed(
    client: httpx.Client, workspace: Path
) -> None:
    link = workspace / "alias"
    if not make_dir_link(link, workspace / "sub"):
        pytest.skip("cannot create a directory link on this machine")
    try:
        assert read(client, workspace, "alias/b.py").content == b"x = 1\n"
        assert write(client, workspace, "alias/new.txt").json() == {"ok": True}
        assert (workspace / "sub" / "new.txt").is_file()
    finally:
        remove_dir_link(link)


def test_file_symlink_to_outside_is_refused_for_read_and_copy(
    client: httpx.Client, workspace: Path, outside: Path
) -> None:
    link = workspace / "sl.txt"
    if not make_file_symlink(link, outside / "secret.txt"):
        pytest.skip("creating a file symlink needs a privilege this account lacks")
    assert read(client, workspace, "sl.txt").status_code == 400
    assert write(client, workspace, "sl.txt").status_code == 400
    # a rename or delete of the link itself is also judged by where it leads
    assert delete(client, workspace, "sl.txt").status_code == 400
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "SECRET"
    listing = client.get(f"{FILES}/list", params={"workspace": str(workspace)}).json()
    assert "sl.txt" not in [f["path"] for f in listing["files"]]


def test_workspace_that_is_itself_reached_through_a_link(
    client: httpx.Client, workspace: Path, tmp_path: Path
) -> None:
    alias = tmp_path / "alias-root"
    if not make_dir_link(alias, workspace):
        pytest.skip("cannot create a directory link on this machine")
    try:
        body = client.get(f"{FILES}/list", params={"workspace": str(alias)}).json()
        assert same_path(body["workspace"], workspace)
        assert read(client, alias, "a.txt").content == b"hello\n"
        assert read(client, alias, "../a.txt").status_code in (400, 404)
    finally:
        remove_dir_link(alias)


def test_every_coding_route_accepts_any_folder_as_the_root(
    client: httpx.Client, tmp_path: Path
) -> None:
    """Suspected bug S1: there is no workspace allowlist; the token is the only gate.

    ``tmp_path`` is neither EVOFLUX_WORKSPACE_DIR nor an EVOFLUX_WORKSPACE_ROOTS
    folder, and the files routes read and write there all the same.
    """
    root = tmp_path / "anywhere"
    root.mkdir()
    assert write(client, root, "x.txt").json() == {"ok": True}
    assert read(client, root, "x.txt").content.strip() == b"PWN"
    assert delete(client, root, "x.txt").json() == {"ok": True}
