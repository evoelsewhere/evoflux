from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "browser_use": "browser_use_tool",
    "webbridge": "webbridge_tool",
    "create_pull_request": "pr",
    "add_code_review_comment": "code_reviews",
    "add_code_review_inline_comment": "code_reviews",
    "close_code_review": "code_reviews",
    "get_code_review": "code_reviews",
    "get_code_review_checks": "code_reviews",
    "list_code_reviews": "code_reviews",
    "merge_code_review": "code_reviews",
    "reopen_code_review": "code_reviews",
    "reopen_code_review_thread": "code_reviews",
    "reply_code_review_thread": "code_reviews",
    "resolve_code_review_thread": "code_reviews",
    "submit_code_review": "code_reviews",
    "update_code_review": "code_reviews",
    "get_date": "date",
    "get_goal": "goal",
    "update_goal": "goal",
    "edit_file": "filesystem",
    "glob_files": "filesystem",
    "grep_files": "filesystem",
    "list_directory": "filesystem",
    "patch_file": "filesystem",
    "read_file": "filesystem",
    "remove_path": "filesystem",
    "write_file": "filesystem",
    "load_tool": "load_tool",
    "memory_search": "memory_search",
    "note_tool": "note",
    "process_tool": "process",
    "python_tool": "python",
    "schedule_task": "schedule",
    "shell_tool": "shell",
    "discover_skills": "skill",
    "load_skill": "skill",
    "todo_manage": "todo",
    "image_search": "web",
    "web_fetch": "web",
    "web_search": "web",
}

_SUBMODULES = {
    "browser_use_tool",
    "process",
    "preview",
    "shell_runtime",
    "skill",
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 - public lazy re-export
    module_name = _EXPORT_MODULES.get(name)
    if module_name is not None:
        value = getattr(import_module(f"{__name__}.{module_name}"), name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "browser_use",
    "create_pull_request",
    "add_code_review_comment",
    "add_code_review_inline_comment",
    "close_code_review",
    "get_code_review",
    "get_code_review_checks",
    "list_code_reviews",
    "merge_code_review",
    "reopen_code_review",
    "reopen_code_review_thread",
    "reply_code_review_thread",
    "resolve_code_review_thread",
    "submit_code_review",
    "update_code_review",
    "webbridge",
    "discover_skills",
    "edit_file",
    "shell_tool",
    "get_date",
    "get_goal",
    "glob_files",
    "grep_files",
    "list_directory",
    "load_tool",
    "patch_file",
    "load_skill",
    "memory_search",
    "note_tool",
    "process_tool",
    "python_tool",
    "read_file",
    "remove_path",
    "schedule_task",
    "todo_manage",
    "update_goal",
    "image_search",
    "web_fetch",
    "web_search",
    "write_file",
]
