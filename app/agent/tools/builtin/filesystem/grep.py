"""grep_files tool — search file contents by regex.

Uses ripgrep (``rg``) when available — orders of magnitude faster than the
pure-Python scan on large repos, and honours nested ``.gitignore`` files.
Falls back to the original ``os.walk`` + ``re`` scan when ``rg`` is missing
or rejects the pattern (e.g. backreferences, which Rust's regex engine does
not support).
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from pathlib import Path
from typing import Annotated

from loguru import logger
from pydantic import Field

from app.agent.process_sandbox import sandboxed_process_argv
from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.filesystem._ignore import (
    _SKIPPED_DIR_NAMES,
    is_gitignored,
    load_gitignore_rules,
)
from app.agent.tools.registry import Tool

# Me cap regex pattern length — prevents catastrophically complex patterns
_MAX_PATTERN_LEN = 500
# Me timeout for the entire scan in seconds
_SCAN_TIMEOUT_S = 10
# Matched/context lines are truncated to this many characters
_MAX_LINE_CHARS = 200
# Upper bound for the ``context`` parameter
_MAX_CONTEXT = 10
# Field separators requested from rg so ``path``/``line``/``content`` can be
# split unambiguously (paths never contain control characters in practice).
_RG_MATCH_SEP = "\x1f"
_RG_CONTEXT_SEP = "\x1e"


def _format_line(display: str, lineno: str | int, content: str, *, match: bool) -> str:
    """Render one output line; context lines use '-' separators like grep -C."""
    content = content[:_MAX_LINE_CHARS]
    if match:
        return f"{display}:{lineno}: {content}"
    return f"{display}-{lineno}- {content}"


def _safe_kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:  # already exited
        pass


async def _rg_scan(
    rg: str,
    pattern: str,
    root: Path,
    include: str,
    max_results: int,
    case_insensitive: bool,
    context: int,
    sandbox,
    gitignore_rules: list[tuple[str, bool]],
) -> list[str] | None:
    """Search with ripgrep. Returns None when rg errors so callers can fall back."""
    cmd = [
        rg,
        "--line-number",
        "--no-heading",
        "--color=never",
        "--no-messages",
        # Keep single output lines bounded (minified JS etc.) so the stream
        # reader's line limit is never hit; content is re-capped later anyway.
        "--max-columns=500",
        "--max-columns-preview",
        f"--field-match-separator={_RG_MATCH_SEP}",
        f"--field-context-separator={_RG_CONTEXT_SEP}",
    ]
    if case_insensitive:
        cmd.append("--ignore-case")
    if context > 0:
        cmd.extend(["--context", str(context)])
    if include and include != "*":
        cmd.extend(["--glob", include])
    # Parity with the Python scan: skip build/vendor dirs even when the
    # workspace has no .gitignore covering them.
    for name in sorted(_SKIPPED_DIR_NAMES):
        cmd.extend(["--glob", f"!{name}"])
    cmd.extend(["--regexp", pattern, "."])

    try:
        exec_bin, exec_argv = sandboxed_process_argv(
            cmd[0],
            cmd[1:],
            sandbox=sandbox,
            cwd=root,
        )
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=2**20,  # 1 MB line budget, far above --max-columns output
        )
    except OSError as exc:
        logger.warning("grep_rg_spawn_failed error={}", exc)
        return None

    hits: list[str] = []
    match_count = 0
    try:
        async with asyncio.timeout(_SCAN_TIMEOUT_S):
            assert proc.stdout is not None
            while True:
                try:
                    raw = await proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # Pathologically long line despite --max-columns — skip
                    # the rest of the stream rather than fail the search.
                    _safe_kill(proc)
                    break
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if text == "--":
                    if hits and hits[-1] != "--":
                        hits.append("--")
                    continue
                if _RG_MATCH_SEP in text:
                    parts = text.split(_RG_MATCH_SEP, 2)
                    is_match = True
                elif _RG_CONTEXT_SEP in text:
                    parts = text.split(_RG_CONTEXT_SEP, 2)
                    is_match = False
                else:
                    continue
                if len(parts) < 3:
                    continue
                rel, lineno, content = parts
                rel_path = Path(rel)
                if any(part in _SKIPPED_DIR_NAMES for part in rel_path.parts):
                    continue
                if is_gitignored(
                    rel_path.as_posix(), is_dir=False, rules=gitignore_rules
                ):
                    continue
                display = sandbox.display_path(root / rel)
                hits.append(_format_line(display, lineno, content, match=is_match))
                if is_match:
                    match_count += 1
                    if match_count >= max_results:
                        _safe_kill(proc)
                        break
    except TimeoutError:
        _safe_kill(proc)
        raise TimeoutError(
            f"grep scan timed out after {_SCAN_TIMEOUT_S}s — "
            "narrow the directory or make the pattern more specific"
        ) from None
    finally:
        try:
            await proc.wait()
        except ProcessLookupError:  # pragma: no cover — already reaped
            pass

    # rc 0 = matches, 1 = no matches, 2 = error (bad pattern for Rust regex,
    # unreadable root, ...). On error with nothing found, let the Python
    # engine try — its `re` dialect accepts more patterns.
    if proc.returncode not in (0, 1, None) and not hits:
        logger.info(
            "grep_rg_error rc={} — falling back to python scan", proc.returncode
        )
        return None
    while hits and hits[-1] == "--":
        hits.pop()
    return hits


def _python_scan_sync(
    compiled: re.Pattern[str],
    resolved: Path,
    include: str,
    max_results: int,
    context: int,
    sandbox,
    gitignore_rules,
) -> list[str]:
    hits: list[str] = []
    match_count = 0
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
            if not fnmatch.fnmatch(fname, include):
                continue
            fpath = current / fname
            rel = fpath.relative_to(resolved).as_posix()
            if is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            display_path = sandbox.display_path(fpath)
            lines = text.splitlines()
            matched = [i for i, line in enumerate(lines) if compiled.search(line)]
            if not matched:
                continue
            if context == 0:
                for i in matched:
                    hits.append(_format_line(display_path, i + 1, lines[i], match=True))
                    match_count += 1
                    if match_count >= max_results:
                        return hits
                continue
            # Merge overlapping ±context ranges into blocks, '--' between blocks.
            matched_set = set(matched)
            blocks: list[tuple[int, int]] = []
            for i in matched:
                lo, hi = max(0, i - context), min(len(lines) - 1, i + context)
                if blocks and lo <= blocks[-1][1] + 1:
                    blocks[-1] = (blocks[-1][0], hi)
                else:
                    blocks.append((lo, hi))
            for lo, hi in blocks:
                if hits and hits[-1] != "--":
                    hits.append("--")
                for j in range(lo, hi + 1):
                    is_match = j in matched_set
                    hits.append(
                        _format_line(display_path, j + 1, lines[j], match=is_match)
                    )
                    if is_match:
                        match_count += 1
                        if match_count >= max_results:
                            while hits and hits[-1] == "--":
                                hits.pop()
                            return hits
    while hits and hits[-1] == "--":
        hits.pop()
    if hits and hits[0] == "--":
        hits.pop(0)
    return hits


async def _grep_files(
    pattern: Annotated[
        str,
        Field(description="Regex to match per line (e.g. 'def main', 'TODO|FIXME')."),
    ],
    directory: Annotated[
        str,
        Field(description="Search root (default '.' = workspace root)."),
    ] = ".",
    include: Annotated[
        str,
        Field(description="Filename glob to filter files (e.g. '*.py'). Default '*'."),
    ] = "*",
    max_results: Annotated[
        int,
        Field(description="Maximum matching lines to return (default 100)."),
    ] = 100,
    case_insensitive: Annotated[
        bool,
        Field(description="Case-insensitive matching (default false)."),
    ] = False,
    context: Annotated[
        int,
        Field(
            description=(
                "Lines of context to show around each match, like grep -C "
                "(default 0, max 10). Context lines use 'file-line-' prefixes."
            )
        ),
    ] = 0,
) -> str:
    """Search file contents by regex. Returns 'file:line: content'."""
    sandbox = get_sandbox()
    resolved = sandbox.validate_path(directory)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {sandbox.display_path(resolved)}")

    # Me reject patterns that are too long — prevents crafted ReDoS payloads
    if len(pattern) > _MAX_PATTERN_LEN:
        raise ValueError(
            f"Pattern too long ({len(pattern)} chars, max {_MAX_PATTERN_LEN})"
        )

    try:
        compiled = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    context = max(0, min(int(context), _MAX_CONTEXT))

    matches: list[str] | None = None
    gitignore_rules = load_gitignore_rules(resolved)
    rg = shutil.which("rg")
    if rg:
        matches = await _rg_scan(
            rg,
            pattern,
            resolved,
            include,
            max_results,
            case_insensitive,
            context,
            sandbox,
            gitignore_rules,
        )
    if matches is None:
        # Me run scan with timeout to prevent ReDoS from locking the thread pool
        try:
            matches = await asyncio.wait_for(
                asyncio.to_thread(
                    _python_scan_sync,
                    compiled,
                    resolved,
                    include,
                    max_results,
                    context,
                    sandbox,
                    gitignore_rules,
                ),
                timeout=_SCAN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"grep_files scan timed out after {_SCAN_TIMEOUT_S}s — "
                "pattern may be too complex or directory too large"
            )
    if not matches:
        return f"No matches for pattern '{pattern}' in {sandbox.display_path(resolved)} (include={include})"
    return "\n".join(matches)


grep_files = Tool(
    _grep_files,
    name="grep",
    description=(
        "Search file contents by regex (ripgrep-accelerated). Returns "
        "'file:line: content'. Supports case_insensitive matching and "
        "context lines around matches."
    ),
    concurrency_safe=True,
    read_only=True,
    capabilities=("source_navigation",),
)
