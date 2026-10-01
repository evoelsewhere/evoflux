"""grep_files tool — search file contents by regex.

Uses ripgrep (``rg``): the copy bundled with the desktop app first (its path
arrives in ``EVOFLUX_RG_BIN``), then one on ``PATH``. Falls back to an
``os.walk`` + ``re`` scan when neither exists or rg rejects the pattern and
the PCRE2 engine cannot take it either.

Three output modes keep the model's first look cheap: ``files_with_matches``
lists paths newest first, ``count`` sizes a search before reading it, and
``content`` returns the lines. Every mode pages with ``max_results`` +
``offset`` and ends a partial page with a notice naming the next offset, so
the model never mistakes a cut-off result for the whole answer.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

from loguru import logger
from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.filesystem._ignore import (
    _SKIPPED_DIR_NAMES,
    is_gitignored,
    load_gitignore_rules,
)
from app.agent.tools.registry import Tool

OutputMode = Literal["content", "files_with_matches", "count"]

# Path of the ripgrep binary shipped inside the desktop sidecar bundle.
RG_BIN_ENV = "EVOFLUX_RG_BIN"
# Me cap regex pattern length — prevents catastrophically complex patterns
_MAX_PATTERN_LEN = 500
# Me timeout for the entire scan in seconds
_SCAN_TIMEOUT_S = 10
# Matched/context lines are truncated to this many characters
_MAX_LINE_CHARS = 200
# Upper bound for the ``context`` parameter
_MAX_CONTEXT = 10
# Upper bound for one page of results
_MAX_PAGE = 1000
# Matching lines a multi-threaded rg pass may collect for sorting in memory;
# a search past this reruns single-threaded in rg's own path order.
_PARALLEL_CAP = 1000
# Field separators requested from rg so ``path``/``line``/``content`` can be
# split unambiguously (paths never contain control characters in practice).
_RG_MATCH_SEP = "\x1f"
_RG_CONTEXT_SEP = "\x1e"
_TYPE_NAME = re.compile(r"^[A-Za-z0-9_+-]{1,32}$")
# File globs for common ripgrep ``--type`` names, used only by the Python
# fallback; with rg the full built-in type list applies.
_FALLBACK_TYPE_GLOBS: dict[str, tuple[str, ...]] = {
    "c": ("*.c", "*.h"),
    "cpp": ("*.cpp", "*.cc", "*.cxx", "*.hpp", "*.hh", "*.hxx", "*.h"),
    "cs": ("*.cs",),
    "css": ("*.css", "*.scss", "*.sass", "*.less"),
    "go": ("*.go",),
    "html": ("*.html", "*.htm"),
    "java": ("*.java",),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs", "*.vue"),
    "json": ("*.json",),
    "kotlin": ("*.kt", "*.kts"),
    "markdown": ("*.md", "*.markdown", "*.mdx"),
    "md": ("*.md", "*.markdown", "*.mdx"),
    "php": ("*.php",),
    "py": ("*.py", "*.pyi"),
    "ruby": ("*.rb",),
    "rust": ("*.rs",),
    "sh": ("*.sh", "*.bash", "*.zsh"),
    "sql": ("*.sql",),
    "swift": ("*.swift",),
    "toml": ("*.toml",),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "yaml": ("*.yaml", "*.yml"),
}


@dataclass(frozen=True)
class _Query:
    pattern: str
    root: Path
    include: str
    file_type: str
    mode: OutputMode
    case_insensitive: bool
    fixed_strings: bool
    multiline: bool
    context: int
    # content mode stops once it has seen this many matching lines; the
    # extra one past the page proves more exist without scanning everything.
    stop_after: int


@dataclass
class _Hits:
    """Raw backend output before paging.

    ``entries`` (content mode) holds ``None`` for a block separator and
    ``(is_match, display, lineno, text)`` for a line. ``files`` holds
    ``(path, matching_line_count)``; the count is 0 in files mode.
    ``complete`` is False when the scan stopped early, so more may exist.
    ``order`` maps each content display path to its sort key, and ``pcre2``
    records that rg only accepted the pattern with its PCRE2 engine.
    """

    entries: list[tuple[bool, str, int, str] | None]
    files: list[tuple[Path, int]]
    complete: bool
    order: dict[str, tuple[str, ...]] = field(default_factory=dict)
    pcre2: bool = False


def _contains_line_break_expression(pattern: str) -> bool:
    """Return whether a line-oriented regex asks to cross a line boundary.

    Ripgrep rejects these expressions without multiline mode, while the Python
    fallback accepts them but evaluates each line separately and can therefore
    never satisfy that branch. Failing fast avoids an expensive full-tree scan
    that cannot produce the requested cross-line match. An escaped literal
    ``\\\\n`` remains valid and is not mistaken for a newline token.
    """

    if "\n" in pattern or "\r" in pattern:
        return True
    index = 0
    while index < len(pattern):
        if pattern[index] != "\\":
            index += 1
            continue
        start = index
        while index < len(pattern) and pattern[index] == "\\":
            index += 1
        slash_count = index - start
        if slash_count % 2 == 1 and index < len(pattern) and pattern[index] in "nr":
            return True
    return False


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


def bundled_ripgrep() -> str | None:
    """Return the ripgrep shipped with the desktop app, if this is one."""
    bundled = os.environ.get(RG_BIN_ENV, "").strip()
    return bundled if bundled and Path(bundled).is_file() else None


def ripgrep_binary() -> str | None:
    """Return the bundled ripgrep when present, else one on ``PATH``."""
    return bundled_ripgrep() or shutil.which("rg")


def _is_excluded(rel_path: Path, gitignore_rules: list[tuple[str, bool]]) -> bool:
    """Parity with the Python scan for rg output: skip build/vendor dirs and
    root ``.gitignore`` entries even when rg's own ignore files miss them."""
    if any(part in _SKIPPED_DIR_NAMES for part in rel_path.parts):
        return True
    return is_gitignored(rel_path.as_posix(), is_dir=False, rules=gitignore_rules)


def _path_key(path: Path) -> tuple[str, ...]:
    """Component-wise path order, the same order ``rg --sort=path`` uses."""
    return path.parts


def _rg_command(rg: str, query: _Query, *, pcre2: bool, sort: bool) -> list[str]:
    cmd = [rg, "--color=never", "--no-messages", "--no-require-git"]
    if query.mode == "content":
        cmd += [
            "--line-number",
            "--no-heading",
            # Keep single output lines bounded (minified JS etc.) so the stream
            # reader's line limit is never hit; content is re-capped later.
            "--max-columns=500",
            "--max-columns-preview",
            f"--field-match-separator={_RG_MATCH_SEP}",
            f"--field-context-separator={_RG_CONTEXT_SEP}",
        ]
        if sort:
            # Single-threaded (about 2x slower), only used to stream the
            # first pages of a search too large to sort in memory.
            cmd.append("--sort=path")
        if query.context > 0:
            cmd += ["--context", str(query.context)]
    elif query.mode == "count":
        # Sorted by path afterwards, so rg stays multi-threaded.
        cmd.append("--count")
    else:
        # Sorted by mtime afterwards, so rg stays multi-threaded.
        cmd.append("--files-with-matches")
    if query.case_insensitive:
        cmd.append("--ignore-case")
    if query.fixed_strings:
        cmd.append("--fixed-strings")
    if query.multiline:
        cmd += ["--multiline", "--multiline-dotall"]
    if pcre2:
        cmd.append("--pcre2")
    if query.include and query.include != "*":
        cmd += ["--glob", query.include]
    if query.file_type:
        cmd.append(f"--type={query.file_type}")
    for name in sorted(_SKIPPED_DIR_NAMES):
        cmd += ["--glob", f"!{name}"]
    cmd += ["--regexp", query.pattern, "."]
    return cmd


async def _run_rg(
    cmd: list[str], root: Path, on_line: Callable[[str], bool]
) -> tuple[int | None, str] | None:
    """Stream rg stdout into ``on_line`` until it returns False.

    Returns ``(returncode, stderr)`` with returncode ``None`` when the stream
    was cut short, or ``None`` when rg could not be started.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=2**20,  # 1 MB line budget, far above --max-columns output
        )
    except OSError as exc:
        logger.warning("grep_rg_spawn_failed error={}", exc)
        return None

    # Drain stderr alongside stdout so a chatty rg can never block on a full
    # pipe; --no-messages keeps it to pattern/argument errors in practice.
    assert proc.stdout is not None and proc.stderr is not None
    stderr_task = asyncio.ensure_future(proc.stderr.read())
    stopped = False
    try:
        async with asyncio.timeout(_SCAN_TIMEOUT_S):
            while True:
                try:
                    raw = await proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # Pathologically long line despite --max-columns — skip
                    # the rest of the stream rather than fail the search.
                    stopped = True
                    _safe_kill(proc)
                    break
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not on_line(text):
                    stopped = True
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
        stderr = await stderr_task
    return (None if stopped else proc.returncode), stderr.decode(
        "utf-8", errors="replace"
    )


async def _rg_scan(
    rg: str,
    query: _Query,
    sandbox,
    gitignore_rules: list[tuple[str, bool]],
) -> _Hits | None:
    """Search with ripgrep. Returns None when rg errors so callers can fall back.

    Content mode runs multi-threaded first and puts a complete result in path
    order here. Only a search with more than ``_PARALLEL_CAP`` matching lines
    is rerun in rg's sorted, single-threaded order, which streams the first
    pages and stops. Both orders compare paths component-wise, so offset
    pages stay consistent whichever pass served them.
    """
    if query.mode != "content":
        return await _rg_pass(rg, query, sandbox, gitignore_rules, stop_after=0)
    hits = await _rg_pass(
        rg,
        query,
        sandbox,
        gitignore_rules,
        stop_after=max(query.stop_after, _PARALLEL_CAP),
    )
    if hits is None or hits.complete:
        return _in_path_order(hits, query.context) if hits else None
    return await _rg_pass(
        rg,
        query,
        sandbox,
        gitignore_rules,
        stop_after=query.stop_after,
        pcre2=hits.pcre2,
        sort=True,
    )


def _in_path_order(hits: _Hits, context: int) -> _Hits:
    """Order a complete multi-threaded result the way ``rg --sort=path`` would."""
    by_file: dict[str, list[tuple[bool, str, int, str]]] = {}
    for entry in hits.entries:
        if entry is not None:
            by_file.setdefault(entry[1], []).append(entry)
    ordered: list[tuple[bool, str, int, str] | None] = []
    for display in sorted(by_file, key=lambda name: hits.order[name]):
        previous: int | None = None
        for entry in sorted(by_file[display], key=lambda item: item[2]):
            # rg separates files, and non-adjacent context blocks, with "--".
            if context and ordered and (previous is None or entry[2] > previous + 1):
                ordered.append(None)
            ordered.append(entry)
            previous = entry[2]
    hits.entries = ordered
    return hits


async def _rg_pass(
    rg: str,
    query: _Query,
    sandbox,
    gitignore_rules: list[tuple[str, bool]],
    *,
    stop_after: int,
    pcre2: bool = False,
    sort: bool = False,
) -> _Hits | None:
    """Run rg once; content mode stops after ``stop_after`` matching lines."""
    hits = _Hits(entries=[], files=[], complete=True, pcre2=pcre2)
    match_count = 0

    def on_content(text: str) -> bool:
        nonlocal match_count
        if text == "--":
            if hits.entries and hits.entries[-1] is not None:
                hits.entries.append(None)
            return True
        if _RG_MATCH_SEP in text:
            parts = text.split(_RG_MATCH_SEP, 2)
            is_match = True
        elif _RG_CONTEXT_SEP in text:
            parts = text.split(_RG_CONTEXT_SEP, 2)
            is_match = False
        else:
            return True
        if len(parts) < 3 or not parts[1].isdigit():
            return True
        rel, lineno, content = parts
        if _is_excluded(Path(rel), gitignore_rules):
            return True
        path = query.root / rel
        display = sandbox.display_path(path)
        if display not in hits.order:
            hits.order[display] = _path_key(path)
        hits.entries.append((is_match, display, int(lineno), content))
        if is_match:
            match_count += 1
            return match_count < stop_after
        return True

    def on_file(text: str) -> bool:
        rel, count = text, 0
        if query.mode == "count":
            rel, _, raw_count = text.rpartition(":")
            if not raw_count.isdigit():
                return True
            count = int(raw_count)
        if rel and not _is_excluded(Path(rel), gitignore_rules):
            hits.files.append((query.root / rel, count))
        return True

    outcome = await _run_rg(
        _rg_command(rg, query, pcre2=pcre2, sort=sort),
        query.root,
        on_content if query.mode == "content" else on_file,
    )
    if outcome is None:
        return None
    returncode, stderr = outcome
    hits.complete = returncode is not None
    found = bool(hits.entries or hits.files)
    # rc 0 = matches, 1 = no matches, 2 = error (bad pattern for Rust regex,
    # unknown --type, unreadable root, ...).
    if returncode not in (0, 1, None) and not found:
        if "unrecognized file type" in stderr:
            raise ValueError(
                f"Unknown type '{query.file_type}'. Use a ripgrep type name "
                "such as py, ts, js, rust, go, java or md, or filter with include."
            )
        if not pcre2 and "--pcre2" in stderr:
            # Backreferences and look-around: rg's PCRE2 engine takes them.
            return await _rg_pass(
                rg,
                query,
                sandbox,
                gitignore_rules,
                stop_after=stop_after,
                pcre2=True,
                sort=sort,
            )
        logger.info("grep_rg_error rc={} — falling back to python scan", returncode)
        return None
    while hits.entries and hits.entries[-1] is None:
        hits.entries.pop()
    return hits


def _matched_line_indexes(
    compiled: re.Pattern[str], text: str, lines: list[str], multiline: bool
) -> list[int]:
    if not multiline:
        return [i for i, line in enumerate(lines) if compiled.search(line)]
    # Mark every line a match spans, as rg does in multiline mode.
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    matched: set[int] = set()
    for found in compiled.finditer(text):
        first = bisect_right(starts, found.start()) - 1
        last = bisect_right(starts, max(found.start(), found.end() - 1)) - 1
        matched.update(range(first, last + 1))
    return sorted(matched)


def _python_scan_sync(
    compiled: re.Pattern[str],
    query: _Query,
    sandbox,
    gitignore_rules,
) -> _Hits:
    hits = _Hits(entries=[], files=[], complete=True)
    if query.file_type:
        globs = _FALLBACK_TYPE_GLOBS.get(query.file_type.lower())
        if globs is None:
            raise ValueError(
                f"Unknown type '{query.file_type}'. Use one of "
                f"{', '.join(sorted(_FALLBACK_TYPE_GLOBS))}, or filter with include."
            )
    else:
        globs = None
    match_count = 0
    for root, dirs, files in os.walk(query.root):
        current = Path(root)
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and d not in _SKIPPED_DIR_NAMES
            and not is_gitignored(
                (current / d).relative_to(query.root).as_posix(),
                is_dir=True,
                rules=gitignore_rules,
            )
        )
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            if not fnmatch.fnmatch(fname, query.include):
                continue
            if globs is not None and not any(fnmatch.fnmatch(fname, g) for g in globs):
                continue
            fpath = current / fname
            rel = fpath.relative_to(query.root).as_posix()
            if is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = text.splitlines()
            matched = _matched_line_indexes(compiled, text, lines, query.multiline)
            if not matched:
                continue
            if query.mode != "content":
                hits.files.append((fpath, len(matched)))
                continue
            display_path = sandbox.display_path(fpath)
            # Merge overlapping ±context ranges into blocks, None between blocks.
            matched_set = set(matched)
            blocks: list[tuple[int, int]] = []
            for i in matched:
                lo = max(0, i - query.context)
                hi = min(len(lines) - 1, i + query.context)
                if blocks and lo <= blocks[-1][1] + 1:
                    blocks[-1] = (blocks[-1][0], hi)
                else:
                    blocks.append((lo, hi))
            for lo, hi in blocks:
                if query.context and hits.entries and hits.entries[-1] is not None:
                    hits.entries.append(None)
                for j in range(lo, hi + 1):
                    is_match = j in matched_set
                    hits.entries.append((is_match, display_path, j + 1, lines[j]))
                    if is_match:
                        match_count += 1
                        if match_count >= query.stop_after:
                            hits.complete = False
                            return hits
    return hits


def _page_notice(noun: str, offset: int, shown: int, total: int | None) -> str:
    """Tell the model a page is partial and how to get the rest."""
    span = f"{noun} {offset + 1}-{offset + shown}"
    if total is None:
        return (
            f"[Showing {span}; more exist. Pass offset={offset + shown} for the "
            "next page, or narrow directory/include/type.]"
        )
    if offset + shown < total:
        return (
            f"[Showing {span} of {total}. Pass offset={offset + shown} for the "
            "next page, or narrow directory/include/type.]"
        )
    return f"[Showing {span} of {total}.]"


def _is_context(entry: tuple[bool, str, int, str] | None) -> bool:
    return entry is not None and not entry[0]


def _render_content(hits: _Hits, offset: int, limit: int) -> list[str]:
    entries = hits.entries
    positions = [i for i, e in enumerate(entries) if e is not None and e[0]]
    total = len(positions)
    if offset >= total:
        return [f"No entries at offset {offset} — only {total} matching lines."]
    more = total > offset + limit or not hits.complete
    if offset == 0 and not more:
        window = entries
    else:
        # Keep the context lines around the page's matches, but stop at the
        # next match or block separator so no off-page match slips in.
        start = positions[offset]
        end = positions[min(offset + limit, total) - 1]
        while start > 0 and _is_context(entries[start - 1]):
            start -= 1
        while end + 1 < len(entries) and _is_context(entries[end + 1]):
            end += 1
        window = entries[start : end + 1]
    lines: list[str] = []
    for entry in window:
        if entry is None:
            if lines and lines[-1] != "--":
                lines.append("--")
            continue
        is_match, display, lineno, text = entry
        lines.append(_format_line(display, lineno, text, match=is_match))
    while lines and lines[-1] == "--":
        lines.pop()
    shown = min(offset + limit, total) - offset
    if more:
        lines.append(_page_notice("matching lines", offset, shown, None))
    elif offset > 0:
        lines.append(_page_notice("matching lines", offset, shown, total))
    return lines


def _render_files(
    hits: _Hits, mode: OutputMode, offset: int, limit: int, sandbox
) -> list[str]:
    files = hits.files
    if mode == "files_with_matches":

        def _mtime(item: tuple[Path, int]) -> float:
            try:
                return item[0].stat().st_mtime
            except OSError:
                return 0.0

        # Recently edited files are usually the ones the task is about.
        files = sorted(files, key=lambda item: (-_mtime(item), _path_key(item[0])))
    else:
        files = sorted(files, key=lambda item: _path_key(item[0]))
    total = len(files)
    noun = "files"
    if offset >= total:
        return [f"No entries at offset {offset} — only {total} {noun}."]
    page = files[offset : offset + limit]
    if mode == "files_with_matches":
        lines = [sandbox.display_path(path) for path, _ in page]
    else:
        lines = [f"{sandbox.display_path(path)}:{count}" for path, count in page]
    partial = offset > 0 or total > offset + limit
    if mode == "count":
        matching = sum(count for _, count in files)
        summary = f"[{matching} matching lines in {total} files"
        if partial:
            summary += f"; showing files {offset + 1}-{offset + len(page)}"
            if offset + len(page) < total:
                summary += f". Pass offset={offset + len(page)} for the next page"
        lines.append(summary + ".]")
    elif partial:
        lines.append(_page_notice(noun, offset, len(page), total))
    return lines


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
    type: Annotated[
        str,
        Field(
            description=(
                "File type to search, as a ripgrep type name (e.g. 'py', 'ts', "
                "'rust'). Faster and broader than include for a language."
            )
        ),
    ] = "",
    output_mode: Annotated[
        OutputMode,
        Field(
            description=(
                "'content' (default): matching lines as 'file:line: text'. "
                "'files_with_matches': only file paths, newest first — the "
                "cheapest way to locate code. 'count': matching lines per file "
                "plus a total."
            )
        ),
    ] = "content",
    max_results: Annotated[
        int,
        Field(
            description=(
                "Maximum entries per page: matching lines, files or per-file "
                "counts depending on output_mode (default 100, max 1000)."
            )
        ),
    ] = 100,
    offset: Annotated[
        int,
        Field(
            description=(
                "Skip this many entries first. Use the offset a truncation "
                "notice gives to fetch the next page."
            )
        ),
    ] = 0,
    case_insensitive: Annotated[
        bool,
        Field(description="Case-insensitive matching (default false)."),
    ] = False,
    fixed_strings: Annotated[
        bool,
        Field(description="Treat pattern as a literal string, not a regex."),
    ] = False,
    multiline: Annotated[
        bool,
        Field(
            description=(
                "Let the pattern span lines; '.' also matches newlines. Write "
                "\\r?\\n to also match Windows line endings (default false)."
            )
        ),
    ] = False,
    context: Annotated[
        int,
        Field(
            description=(
                "Lines of context to show around each match in content mode, "
                "like grep -C (default 0, max 10). Context lines use "
                "'file-line-' prefixes."
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
    if output_mode not in ("content", "files_with_matches", "count"):
        raise ValueError(
            "output_mode must be 'content', 'files_with_matches' or 'count'"
        )
    file_type = type.strip()
    if file_type and not _TYPE_NAME.match(file_type):
        raise ValueError(
            f"Invalid type '{type}'. Use a ripgrep type name such as 'py'."
        )

    if not multiline:
        crosses_lines = (
            "\n" in pattern or "\r" in pattern
            if fixed_strings
            else _contains_line_break_expression(pattern)
        )
        if crosses_lines:
            raise ValueError(
                "grep is line-oriented and cannot match newline expressions. "
                "Pass multiline=true, search each line pattern separately, or "
                "use a scoped source search query for cross-line relationships."
            )

    flags = re.IGNORECASE if case_insensitive else 0
    if multiline:
        flags |= re.MULTILINE | re.DOTALL
    try:
        compiled = re.compile(re.escape(pattern) if fixed_strings else pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    limit = max(1, min(int(max_results), _MAX_PAGE))
    offset = max(0, int(offset))
    query = _Query(
        pattern=pattern,
        root=resolved,
        include=include or "*",
        file_type=file_type,
        mode=output_mode,
        case_insensitive=case_insensitive,
        fixed_strings=fixed_strings,
        multiline=multiline,
        context=max(0, min(int(context), _MAX_CONTEXT)),
        stop_after=offset + limit + 1,
    )

    hits: _Hits | None = None
    gitignore_rules = load_gitignore_rules(resolved)
    rg = ripgrep_binary()
    if rg:
        hits = await _rg_scan(rg, query, sandbox, gitignore_rules)
    if hits is None:
        # Me run scan with timeout to prevent ReDoS from locking the thread pool
        try:
            hits = await asyncio.wait_for(
                asyncio.to_thread(
                    _python_scan_sync, compiled, query, sandbox, gitignore_rules
                ),
                timeout=_SCAN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"grep_files scan timed out after {_SCAN_TIMEOUT_S}s — "
                "pattern may be too complex or directory too large"
            )
    if not hits.entries and not hits.files:
        scope = f"include={query.include}"
        if file_type:
            scope += f", type={file_type}"
        return (
            f"No matches for pattern '{pattern}' in "
            f"{sandbox.display_path(resolved)} ({scope})"
        )
    if output_mode == "content":
        lines = _render_content(hits, offset, limit)
    else:
        lines = _render_files(hits, output_mode, offset, limit, sandbox)
    return "\n".join(lines)


grep_files = Tool(
    _grep_files,
    name="grep",
    description=(
        "Search file contents by regex (ripgrep). output_mode 'content' "
        "(default) returns 'file:line: text'; 'files_with_matches' returns only "
        "paths, newest first — start there to locate code; 'count' returns "
        "matching lines per file plus a total. Filter with include (filename "
        "glob) or type (e.g. 'py'). A partial page ends with a notice giving "
        "the offset for the next page."
    ),
    concurrency_safe=True,
    read_only=True,
    capabilities=("source_navigation",),
    observation_kind="discovery",
)
