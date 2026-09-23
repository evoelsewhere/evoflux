"""Repository Search Everywhere aggregation."""

from __future__ import annotations

import asyncio
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)
from app.services.git_ops import run_git
from app.services.problems_service import list_problems

SearchKind = Literal[
    "file",
    "folder",
    "git_branch",
    "git_commit",
    "problem",
    "skill",
    "workflow",
]


@dataclass(frozen=True, slots=True)
class SearchEverywhereItem:
    id: str
    kind: SearchKind
    label: str
    description: str
    path: str | None = None
    line: int | None = None
    metadata: dict[str, Any] | None = None


def _file_metadata(workspace: Path, relative_path: str) -> dict[str, Any]:
    """Return viewer metadata for an in-workspace file search result."""
    try:
        target = (workspace / relative_path).resolve(strict=True)
        target.relative_to(workspace.resolve())
        if not target.is_file():
            return {}
        stat = target.stat()
    except (OSError, RuntimeError, ValueError):
        return {}
    mime, _ = mimetypes.guess_type(str(target))
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mime": mime or "application/octet-stream",
    }


async def search_everywhere(
    workspace: Path, query: str, *, limit: int = 50
) -> list[SearchEverywhereItem]:
    root = workspace.resolve()
    normalized = query.strip()
    if not normalized:
        return []
    per_source = max(5, min(20, limit // 3))
    groups = await _parallel_sources(root, normalized, per_source)
    items: list[SearchEverywhereItem] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
            if len(items) >= limit:
                return items
    return items


async def _parallel_sources(
    workspace: Path, query: str, limit: int
) -> list[list[SearchEverywhereItem]]:
    results = await asyncio.gather(
        asyncio.to_thread(_path_items, workspace, query, limit),
        asyncio.to_thread(_problem_items, workspace, query, limit),
        _git_items(workspace, query, limit),
        asyncio.to_thread(_skill_items, workspace, query, limit),
        asyncio.to_thread(_workflow_items, workspace, query, limit),
        return_exceptions=True,
    )
    return [result if isinstance(result, list) else [] for result in results]


def _path_items(workspace: Path, query: str, limit: int) -> list[SearchEverywhereItem]:
    needle = query.casefold()
    rules = load_gitignore_rules(workspace)
    rows: list[SearchEverywhereItem] = []
    entries_seen = 0
    for base, directories, files in os.walk(workspace):
        base_path = Path(base)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory != ".git"
            and not is_ignored_workspace_path(
                (base_path / directory).relative_to(workspace).as_posix(),
                is_dir=True,
                rules=rules,
            )
        )
        entries: list[tuple[str, SearchKind]] = [
            *((directory, "folder") for directory in directories),
            *((file, "file") for file in sorted(files)),
        ]
        for name, kind in entries:
            entries_seen += 1
            if entries_seen > 20_000:
                return rows
            path = (base_path / name).relative_to(workspace).as_posix()
            if needle not in path.casefold():
                continue
            rows.append(
                SearchEverywhereItem(
                    id=f"{kind}:{path}",
                    kind=kind,
                    label=path,
                    description="Repository folder"
                    if kind == "folder"
                    else "Repository file",
                    path=path,
                    metadata=_file_metadata(workspace, path)
                    if kind == "file"
                    else None,
                )
            )
            if len(rows) >= limit:
                return rows
    return rows


async def _git_items(
    workspace: Path, query: str, limit: int
) -> list[SearchEverywhereItem]:
    branches, commits = await _git_queries(workspace, query, limit)
    rows = [
        SearchEverywhereItem(
            id=f"git-branch:{branch}",
            kind="git_branch",
            label=branch,
            description="Git branch",
            metadata={"branch": branch},
        )
        for branch in branches
        if query.casefold() in branch.casefold()
    ]
    for raw in commits:
        sha, _, subject = raw.partition("\x1f")
        rows.append(
            SearchEverywhereItem(
                id=f"git-commit:{sha}",
                kind="git_commit",
                label=subject or sha[:8],
                description=sha[:12],
                metadata={"sha": sha},
            )
        )
    return rows[:limit]


async def _git_queries(
    workspace: Path, query: str, limit: int
) -> tuple[list[str], list[str]]:
    branch_result, commit_result = await asyncio.gather(
        run_git(str(workspace), "branch", "--format=%(refname:short)", timeout=5),
        run_git(
            str(workspace),
            "log",
            f"--max-count={limit}",
            f"--grep={query}",
            "--regexp-ignore-case",
            "--format=%H%x1f%s",
            timeout=5,
        ),
    )
    return branch_result.stdout.splitlines(), commit_result.stdout.splitlines()


def _problem_items(
    workspace: Path, query: str, limit: int
) -> list[SearchEverywhereItem]:
    needle = query.casefold()
    rows: list[SearchEverywhereItem] = []
    for problem in list_problems(workspace):
        haystack = " ".join(
            filter(None, (problem.title, problem.message, problem.path, problem.code))
        )
        if needle not in haystack.casefold():
            continue
        rows.append(
            SearchEverywhereItem(
                id=f"problem:{problem.id}",
                kind="problem",
                label=problem.title or problem.message,
                description=f"{problem.severity} · {problem.source}",
                path=problem.path,
                line=problem.line,
                metadata={"problem_id": problem.id},
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _skill_items(workspace: Path, query: str, limit: int) -> list[SearchEverywhereItem]:
    """User-invocable Skills; choosing one fills the composer with ``$name``."""
    from app.agent.skills.registry import discover_skills

    needle = query.casefold()
    return [
        SearchEverywhereItem(
            id=f"skill:{skill.name}",
            kind="skill",
            label=skill.name,
            description=skill.description,
            metadata={"name": skill.name, "insert_text": f"${skill.name} "},
        )
        for skill in discover_skills([workspace]).user_visible()
        if needle in f"{skill.name} {skill.description}".casefold()
    ][:limit]


def _workflow_items(
    workspace: Path, query: str, limit: int
) -> list[SearchEverywhereItem]:
    from app.services.workflows_fs import discover_workflows

    needle = query.casefold()
    rows: list[SearchEverywhereItem] = []
    for workflow in discover_workflows(str(workspace)):
        description = (
            workflow.definition.description
            if workflow.definition is not None
            else "; ".join(workflow.errors)
        )
        if needle not in f"{workflow.name} {description}".casefold():
            continue
        rows.append(
            SearchEverywhereItem(
                id=f"workflow:{workflow.name}",
                kind="workflow",
                label=workflow.name,
                description=description or f"{workflow.root} workflow",
                metadata={"name": workflow.name, "root": workflow.root},
            )
        )
        if len(rows) >= limit:
            break
    return rows
