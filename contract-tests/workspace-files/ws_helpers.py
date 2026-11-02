"""Shared builders for the ``workspace-files`` contract.

Every path a route returns lives under the test's temp dir. Nothing here
touches the real home folder, the network or a real language server: all
workspaces are temp folders, and Windows-only name rules are tested by name,
never by reaching a UNC share.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

#: Every route of the unit as (method, path, query, JSON body). The values are
#: valid, so a 401 proves authentication runs before anything else. Path
#: parameters use a UUID that has no session row.
SID = "11111111-1111-1111-1111-111111111111"
WS = "C:/does-not-matter"

ROUTES: list[tuple[str, str, dict[str, str], object]] = [
    ("GET", "/api/team/workspace/validate", {"workspace": WS}, None),
    ("GET", "/api/team/workspace/browse", {}, None),
    ("GET", "/api/team/workspace/tree", {}, None),
    ("GET", "/api/team/workspace/files/list", {"workspace": WS}, None),
    ("GET", "/api/team/workspace/files/read", {"workspace": WS, "path": "a"}, None),
    ("GET", "/api/team/workspace/files/preview", {"workspace": WS, "path": "a"}, None),
    (
        "PUT",
        "/api/team/workspace/files/write",
        {"workspace": WS, "path": "a"},
        {"content": "x"},
    ),
    (
        "POST",
        "/api/team/workspace/files/create",
        {"workspace": WS, "path": "a"},
        None,
    ),
    (
        "POST",
        "/api/team/workspace/files/move",
        {"workspace": WS},
        {"from_path": "a", "to_path": "b"},
    ),
    (
        "POST",
        "/api/team/workspace/files/copy",
        {"workspace": WS},
        {"from_path": "a", "to_path": "b"},
    ),
    ("DELETE", "/api/team/workspace/files/entry", {"workspace": WS, "path": "a"}, None),
    (
        "POST",
        "/api/team/workspace/lsp/diagnostics",
        {"workspace": WS},
        {"path": "a.txt", "content": "x"},
    ),
    (
        "POST",
        "/api/team/workspace/lsp/semantic",
        {"workspace": WS},
        {"action": "format", "path": "a.txt"},
    ),
    ("GET", "/api/team/workspace/git-diff/view", {"workspace": WS}, None),
    ("GET", "/api/team/workspace/status", {"workspace": WS}, None),
    (
        "POST",
        "/api/team/workspace/language-servers/status",
        {},
        {"workspaces": []},
    ),
    ("POST", "/api/team/workspace/language-servers/go/install", {}, None),
    ("POST", "/api/team/workspace/language-servers/go/install/dismiss", {}, None),
    ("GET", f"/api/team/{SID}/files", {}, None),
    ("GET", f"/api/team/{SID}/workspace", {}, None),
    ("PUT", f"/api/team/{SID}/workspace", {}, {"path": None}),
    ("GET", f"/api/team/{SID}/uploads/a.png", {}, None),
    ("POST", f"/api/team/{SID}/files/create", {"path": "a"}, None),
    ("POST", f"/api/team/{SID}/files/move", {}, {"from_path": "a", "to_path": "b"}),
    ("POST", f"/api/team/{SID}/files/copy", {}, {"from_path": "a", "to_path": "b"}),
    ("DELETE", f"/api/team/{SID}/files/a", {}, None),
]


class Scrub:
    """Replace the temp dir in JSON-able values and fold path separators."""

    def __init__(self, tmp: Path) -> None:
        self._roots = {str(tmp), str(tmp.resolve())}

    def text(self, value: str) -> str:
        for root in self._roots:
            pattern = re.escape(root) + r"[^\s'\"<>|?*:]*"
            value = re.sub(
                pattern,
                lambda m: m.group(0).replace(root, "<tmp>").replace("\\", "/"),
                value,
            )
        return value

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        return value


def same_path(left: str | Path, right: str | Path) -> bool:
    """Equal after link resolution and (on Windows) case folding."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
        os.path.realpath(right)
    )


def tree(root: Path) -> dict[str, bytes | None]:
    """Every file (bytes) and directory (``None``) below ``root``, POSIX keys.

    Does not follow links, so a junction or symlink is listed as one entry.
    """
    found: dict[str, bytes | None] = {}
    if not root.exists():
        return found
    for base, directories, filenames in os.walk(root, followlinks=False):
        for name in directories:
            path = Path(base, name)
            found[path.relative_to(root).as_posix()] = None
        for name in filenames:
            path = Path(base, name)
            try:
                found[path.relative_to(root).as_posix()] = path.read_bytes()
            except OSError:
                found[path.relative_to(root).as_posix()] = None
    return dict(sorted(found.items()))


def make_dir_link(link: Path, target: Path) -> bool:
    """A directory link ``link`` -> ``target``; ``False`` when the OS refuses.

    Windows uses a junction, which needs no privilege; elsewhere a symlink.
    """
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        return False
    return True


def make_file_symlink(link: Path, target: Path) -> bool:
    """A file symlink; ``False`` when the OS refuses (Windows without the privilege)."""
    try:
        os.symlink(target, link)
    except OSError:
        return False
    return True


def remove_dir_link(link: Path) -> None:
    """Remove a link made by ``make_dir_link`` without touching its target."""
    try:
        os.rmdir(link)
    except OSError:
        link.unlink(missing_ok=True)


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=t@example.test",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def init_repo(root: Path, **files: str) -> None:
    """A repository whose first commit holds ``files`` (name -> text)."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8", newline="")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "first")


def error_detail(response: httpx.Response) -> object:
    return response.json()["detail"]
