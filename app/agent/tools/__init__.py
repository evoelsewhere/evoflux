from __future__ import annotations

from importlib import import_module
from typing import Any

from .registry import Tool, tool

_BUILTIN_EXPORTS = {
    "background_process",
    "browser_use",
    "discover_skills",
    "webbridge",
    "shell_tool",
    "get_date",
    "glob_files",
    "grep_files",
    "list_directory",
    "load_skill",
    "patch_file",
    "read_file",
    "remove_path",
    "schedule_task",
    "todo_manage",
    "web_fetch",
    "web_search",
    "write_file",
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 - public lazy re-export
    if name not in _BUILTIN_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("app.agent.tools.builtin"), name)
    globals()[name] = value
    return value


__all__ = [
    "Tool",
    "tool",
    # builtin
    "background_process",
    "browser_use",
    "discover_skills",
    "webbridge",
    "shell_tool",
    "get_date",
    "glob_files",
    "grep_files",
    "list_directory",
    "load_skill",
    "patch_file",
    "read_file",
    "remove_path",
    "schedule_task",
    "todo_manage",
    "web_fetch",
    "web_search",
    "write_file",
]
