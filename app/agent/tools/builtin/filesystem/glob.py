"""glob tool — find files by glob pattern (full-path or filename-only)."""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Annotated

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.filesystem._ignore import (
    _SKIPPED_DIR_NAMES,
    is_gitignored,
    load_gitignore_rules,
)
from app.agent.tools.registry import Tool


# Matches collected before sorting; beyond this the total is reported as "N+".
_MAX_SCAN = 20_000


def _newest_first(hits: list[tuple[float, str]]) -> list[str]:
    """Sort (mtime, display_path) hits newest-first; recency ≈ relevance."""
    return [p for _, p in sorted(hits, key=lambda t: (-t[0], t[1]))]


def _page(matches: list[str], offset: int, limit: int) -> list[str]:
    """Slice one page and end a partial page with a notice for the model."""
    total = len(matches)
    shown = f"{total}+" if total >= _MAX_SCAN else str(total)
    if offset >= total:
        return [f"No entries at offset {offset} — only {shown} files."]
    page = matches[offset : offset + limit]
    end = offset + len(page)
    if end < total:
        page.append(
            f"[Showing files {offset + 1}-{end} of {shown}, newest first. Pass "
            f"offset={end} for the next page, or narrow the pattern or directory.]"
        )
    elif offset > 0:
        page.append(f"[Showing files {offset + 1}-{end} of {shown}.]")
    return page


async def _glob_files(
    pattern: Annotated[
        str,
        Field(
            description=(
                "Glob pattern. Use '**/*.py' or 'src/**/*.ts' to match by full path, "
                "or '*.py' with match='name' to match filename only."
            )
        ),
    ],
    directory: Annotated[
        str,
        Field(description="Search root (default '.' = workspace root)."),
    ] = ".",
    match: Annotated[
        str,
        Field(description="Match against 'path' (default) or 'name' (filename only)."),
    ] = "path",
    max_results: Annotated[
        int,
        Field(description="Maximum number of results to return (default 200)."),
    ] = 200,
    offset: Annotated[
        int,
        Field(
            description=(
                "Skip this many files first. Use the offset a truncation notice "
                "gives to fetch the next page."
            )
        ),
    ] = 0,
) -> str:
    """Find files by glob pattern. match='path' matches the full relative path (supports **); match='name' matches filename only."""
    sandbox = get_sandbox()
    resolved = sandbox.validate_path(directory)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {sandbox.display_path(resolved)}")
    gitignore_rules = load_gitignore_rules(resolved)

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    if match == "name":

        def _scan_name() -> list[str]:
            hits: list[tuple[float, str]] = []
            for root, dirs, files in os.walk(resolved):
                current = Path(root)
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".")
                    and d not in _SKIPPED_DIR_NAMES
                    and not is_gitignored(
                        (current / d).relative_to(resolved).as_posix(),
                        is_dir=True,
                        rules=gitignore_rules,
                    )
                ]
                for fname in files:
                    if fname.startswith("."):
                        continue
                    rel = (current / fname).relative_to(resolved).as_posix()
                    if is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                        continue
                    if fnmatch.fnmatch(fname, pattern):
                        fpath = current / fname
                        hits.append((_mtime(fpath), sandbox.display_path(fpath)))
                        if len(hits) >= _MAX_SCAN:
                            return _newest_first(hits)
            return _newest_first(hits)

        matches = await asyncio.to_thread(_scan_name)
    else:

        def _scan_path() -> list[str]:
            hits: list[tuple[float, str]] = []
            for m in resolved.glob(pattern):
                if not m.is_file():
                    continue
                rel = m.relative_to(resolved)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if any(part in _SKIPPED_DIR_NAMES for part in rel.parts[:-1]):
                    continue
                if is_gitignored(rel.as_posix(), is_dir=False, rules=gitignore_rules):
                    continue
                hits.append((_mtime(m), sandbox.display_path(m)))
                if len(hits) >= _MAX_SCAN:
                    break
            return _newest_first(hits)

        matches = await asyncio.to_thread(_scan_path)

    if not matches:
        return f"No files matching '{pattern}' in {sandbox.display_path(resolved)}"
    return "\n".join(_page(matches, max(0, int(offset)), max(1, int(max_results))))


glob_files = Tool(
    _glob_files,
    name="glob",
    description=(
        "Find files by glob pattern. Use match='path' (default) for full-path patterns "
        "like 'src/**/*.ts', or match='name' for filename-only like '*.py'. "
        "Results are sorted by modification time, newest first; a partial page "
        "ends with a notice giving the offset for the next page."
    ),
    concurrency_safe=True,
    read_only=True,
    capabilities=("source_navigation",),
    observation_kind="discovery",
)
