"""Safe text-file operations for the Plugin Center development workspace."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict


MAX_EDITOR_FILE_BYTES = 1024 * 1024
MAX_EDITOR_ENTRIES = 2_000
_IGNORED_DIRECTORIES = {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}


class PluginWorkspaceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    name: str
    kind: Literal["file", "directory"]
    size: int = 0


def _root_path(root: str | Path) -> Path:
    candidate = Path(root).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise ValueError("Plugin workspace root must be a directory.")
    manifest = candidate / "plugin.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError(
            "Plugin workspace root must contain a regular plugin.json file."
        )
    return candidate


def _relative_path(path: str, *, allow_root: bool = False) -> PurePosixPath:
    if "\\" in path:
        raise ValueError("Workspace paths must use forward slashes.")
    relative = PurePosixPath(path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("Workspace path must be a normalized relative path.")
    if not relative.parts and not allow_root:
        raise ValueError("Workspace path is required.")
    return relative


def _workspace_path(root: Path, path: str, *, allow_root: bool = False) -> Path:
    relative = _relative_path(path, allow_root=allow_root)
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Workspace path escapes the plugin root.") from exc

    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("Symbolic links cannot be edited in Plugin Center.")
    return candidate


def list_workspace(root: str | Path) -> list[PluginWorkspaceEntry]:
    plugin_root = _root_path(root)
    entries: list[PluginWorkspaceEntry] = []
    for base, directories, files in os.walk(plugin_root, followlinks=False):
        base_path = Path(base)
        directories[:] = sorted(
            name
            for name in directories
            if name not in _IGNORED_DIRECTORIES and not (base_path / name).is_symlink()
        )
        for name in directories:
            path = base_path / name
            entries.append(
                PluginWorkspaceEntry(
                    path=path.relative_to(plugin_root).as_posix(),
                    name=name,
                    kind="directory",
                )
            )
        for name in sorted(files):
            path = base_path / name
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                continue
            entries.append(
                PluginWorkspaceEntry(
                    path=path.relative_to(plugin_root).as_posix(),
                    name=name,
                    kind="file",
                    size=path.stat().st_size,
                )
            )
        if len(entries) > MAX_EDITOR_ENTRIES:
            raise ValueError(
                f"Plugin workspace exceeds the {MAX_EDITOR_ENTRIES}-entry editor limit."
            )
    return sorted(entries, key=lambda item: (item.path.casefold(), item.kind))


def read_workspace_file(root: str | Path, path: str) -> str:
    plugin_root = _root_path(root)
    target = _workspace_path(plugin_root, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    size = target.stat().st_size
    if size > MAX_EDITOR_FILE_BYTES:
        raise ValueError(f"File exceeds the {MAX_EDITOR_FILE_BYTES}-byte editor limit.")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Only UTF-8 text files can be edited in Plugin Center."
        ) from exc


def write_workspace_file(root: str | Path, path: str, content: str) -> None:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDITOR_FILE_BYTES:
        raise ValueError(f"File exceeds the {MAX_EDITOR_FILE_BYTES}-byte editor limit.")
    plugin_root = _root_path(root)
    target = _workspace_path(plugin_root, path)
    if target.exists() and not target.is_file():
        raise ValueError("Workspace path is not a regular file.")
    if not target.parent.is_dir():
        raise ValueError("Parent directory does not exist.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def create_workspace_entry(
    root: str | Path,
    path: str,
    kind: Literal["file", "directory"],
) -> None:
    plugin_root = _root_path(root)
    target = _workspace_path(plugin_root, path)
    if target.exists():
        raise ValueError("Workspace entry already exists.")
    if not target.parent.is_dir():
        raise ValueError("Parent directory does not exist.")
    if kind == "directory":
        target.mkdir()
    else:
        target.touch(exist_ok=False)


def delete_workspace_entry(root: str | Path, path: str) -> None:
    plugin_root = _root_path(root)
    target = _workspace_path(plugin_root, path)
    if target.name == "plugin.json" and target.parent == plugin_root:
        raise ValueError("plugin.json cannot be deleted from a plugin workspace.")
    if not target.exists():
        raise FileNotFoundError(path)
    if target.is_dir():
        if any(target.iterdir()):
            raise ValueError("Only empty directories can be deleted.")
        target.rmdir()
    elif target.is_file():
        target.unlink()
    else:
        raise ValueError("Unsupported workspace entry type.")


__all__ = [
    "MAX_EDITOR_ENTRIES",
    "MAX_EDITOR_FILE_BYTES",
    "PluginWorkspaceEntry",
    "create_workspace_entry",
    "delete_workspace_entry",
    "list_workspace",
    "read_workspace_file",
    "write_workspace_file",
]
