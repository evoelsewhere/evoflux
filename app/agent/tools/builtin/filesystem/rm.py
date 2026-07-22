"""remove_path tool — delete a file or directory."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Annotated

from loguru import logger
from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.filesystem._config_watch import notify_fs_change
from app.agent.tools.registry import Tool


def _count_lines_for_removed_file(path: Path) -> int | None:
    try:
        data = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return None
    return len(data.split(b"\n"))


async def _remove_path(
    path: Annotated[
        str,
        Field(description="Relative path to the file or directory to remove."),
    ],
    recursive: Annotated[
        bool,
        Field(
            description="Remove directories recursively. Required when path is a non-empty directory (default false)."
        ),
    ] = False,
) -> str:
    """Delete a file or directory from the workspace. Use recursive=true to remove a directory tree."""
    sandbox = get_sandbox()
    resolved = sandbox.validate_path(path, is_write=True)
    rel = sandbox.display_path(resolved)

    if not resolved.exists():
        raise FileNotFoundError(f"Path not found: {rel}")

    if resolved.is_file() or resolved.is_symlink():
        line_count = _count_lines_for_removed_file(resolved)
        meta_payload: dict[str, str | int] = {"path": path}
        if line_count is not None:
            meta_payload["deleted_lines"] = line_count
        meta = json.dumps(meta_payload, separators=(",", ":"))
        resolved.unlink()
        logger.info("file_removed path={}", resolved)
        notify_fs_change(resolved)
        return (
            f"@@ EvoFlux-diff-meta {meta}\n"
            f"Removed file: {rel}\nResolved path: {resolved}"
        )

    # Me path is directory
    if recursive:
        await asyncio.to_thread(shutil.rmtree, resolved)
        logger.info("dir_removed path={} recursive=true", resolved)
        notify_fs_change(resolved)
        return f"Removed directory: {rel}\nResolved path: {resolved}"

    # Me try remove empty dir
    try:
        resolved.rmdir()
        logger.info("dir_removed path={} recursive=false", resolved)
        notify_fs_change(resolved)
        return f"Removed directory: {rel}\nResolved path: {resolved}"
    except OSError as exc:
        raise OSError(
            f"Directory not empty: {rel}. Use recursive=true to remove it."
        ) from exc


remove_path = Tool(
    _remove_path,
    name="rm",
    deferred=True,
    deferred_summary="Permanently remove a file or directory from the workspace.",
    description=(
        "Permanently delete a file or directory from the workspace. "
        "Use only when the user asked for removal or deletion is necessary. "
        "Set recursive=true to remove a non-empty directory tree."
    ),
)
