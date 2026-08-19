"""Repository Search Everywhere aggregation."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)
from app.core.config import settings
from app.services.git_ops import run_git
from app.services.problems_service import list_problems

SearchKind = Literal[
    "file",
    "folder",
    "symbol",
    "code",
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
        _code_items(workspace, query, limit),
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


async def _code_items(
    workspace: Path, query: str, limit: int
) -> list[SearchEverywhereItem]:
    from app.services.code_index.models import RepositoryScope
    from app.services.code_index.service import query_code_context

    caller_match = re.search(
        r"(?:callers?|người gọi)\s+(?:of|của)?\s*[`'\"]?([A-Za-z_$][\w.$:]*)",
        query,
        re.IGNORECASE,
    )
    action = "callers" if caller_match else "search"
    value = caller_match.group(1) if caller_match else query
    result = await query_code_context(
        scopes=(RepositoryScope(root=workspace, label=workspace.name),),
        action=action,
        query=value,
        depth=1,
        limit=limit,
        refresh=True,
    )
    rows: list[SearchEverywhereItem] = []
    for symbol in result.matches[:limit]:
        rows.append(
            SearchEverywhereItem(
                id=f"symbol:{symbol.id}",
                kind="symbol",
                label=symbol.qualified_name or symbol.name,
                description=symbol.signature or f"{symbol.kind} · {symbol.file_path}",
                path=symbol.file_path,
                line=symbol.line_start,
                metadata={
                    "language": symbol.language,
                    "strategy": result.strategy,
                    **_file_metadata(workspace, symbol.file_path),
                },
            )
        )
    for hit in result.hits[:limit]:
        rows.append(
            SearchEverywhereItem(
                id=f"code:{hit.file_path}:{hit.line_start}:{hit.symbol or ''}",
                kind="symbol" if hit.symbol else "code",
                label=hit.symbol or f"{hit.file_path}:{hit.line_start}",
                description=" ".join(hit.content.strip().split())[:240],
                path=hit.file_path,
                line=hit.line_start,
                metadata={
                    "language": hit.language,
                    "score": hit.score,
                    **_file_metadata(workspace, hit.file_path),
                },
            )
        )
    for relation in result.relations[:limit]:
        rows.append(
            SearchEverywhereItem(
                id=f"relation:{relation.callsite_file}:{relation.callsite_line}:{relation.source.id}",
                kind="code",
                label=f"{relation.source.name} → {relation.target.name}",
                description=f"{relation.kind} · {relation.callsite_file}:{relation.callsite_line}",
                path=relation.callsite_file,
                line=relation.callsite_line,
                metadata=_file_metadata(workspace, relation.callsite_file),
            )
        )
    return rows[:limit]


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
    from app.agent.skills.discovery import (
        discover_skill_records,
        select_skill_records_for_mode,
        standard_skill_roots,
    )

    roots = standard_skill_roots(
        workspace_roots=[workspace],
        evoflux_global=Path(settings.SKILLS_DIR),
    )
    records = select_skill_records_for_mode(discover_skill_records(roots), "coding")
    needle = query.casefold()
    return [
        SearchEverywhereItem(
            id=f"skill:{record.name}",
            kind="skill",
            label=record.display_name or record.name,
            description=record.short_description or record.description,
            metadata={"name": record.name},
        )
        for record in records.values()
        if needle
        in " ".join(
            filter(None, (record.name, record.display_name, record.description))
        ).casefold()
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
