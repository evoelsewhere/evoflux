"""Shared validation for directory roots used by filesystem search tools."""

from __future__ import annotations

from pathlib import Path

from app.agent.sandbox import SandboxConfig


def validate_search_root(
    sandbox: SandboxConfig,
    directory: str | Path,
    *,
    tool_name: str,
) -> Path:
    """Resolve a search root and explain why it is not a usable directory.

    Distinguish an existing file supplied as the root, a missing directory, and
    a path whose existing component is a file. The specific diagnosis helps an
    agent choose between reading the file, correcting the path, or searching
    the containing directory instead of retrying the same invalid call.
    """
    resolved = sandbox.validate_path(directory)
    if resolved.is_dir():
        return resolved

    display_path = sandbox.display_path(resolved)
    if resolved.is_file():
        parent = sandbox.display_path(resolved.parent)
        raise NotADirectoryError(
            f"{tool_name} search root is a file, not a directory: {display_path}. "
            f"Use `read` to inspect that file, or search its parent directory "
            f"{parent!r} with a narrower pattern."
        )

    existing = resolved
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if existing.is_file():
        component = sandbox.display_path(existing)
        parent = sandbox.display_path(existing.parent)
        raise NotADirectoryError(
            f"{tool_name} search path has a file as a directory component: "
            f"{component} is a file in {display_path!r}. Search its parent "
            f"directory {parent!r} instead."
        )

    raise FileNotFoundError(
        f"{tool_name} search directory does not exist: {display_path}. "
        "Check the path and use an existing directory."
    )
