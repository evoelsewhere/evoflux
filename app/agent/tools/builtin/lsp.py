"""Static analysis and real LSP code intelligence tools.

The contracts are deliberately distinct:

- ``static_diagnostics`` — one-shot Ruff/tsc checks.
- ``lsp_*`` — a persistent JSON-RPC language server using didOpen/didChange.

These sit alongside ``code_context``: use it for callers/callees/references of a
known symbol, and lsp_* for live correctness checks and location queries.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlparse

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.shell import _scrubbed_env
from app.agent.lsp_manager import LanguageServerUnavailable, get_language_server
from app.agent.tools.registry import InjectedArg, Tool


# ── Helpers ───────────────────────────────────────────────────────────────────

_MAX_DIAG = 100  # cap diagnostics returned to agent


def _resolve_path(path: str) -> Path:
    """Resolve *path* relative to the sandbox workspace root."""
    return get_sandbox().validate_path(path)


def _detect_language(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in (".ts", ".tsx"):
        return "typescript"
    if suffix in (".js", ".jsx", ".mjs", ".cjs"):
        return "javascript"
    if suffix in (".go",):
        return "go"
    if suffix in (".rs",):
        return "rust"
    return None


async def _run(
    *cmd: str,
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    """Run a command in a thread; return (returncode, stdout, stderr)."""

    def _sync() -> tuple[int, str, str]:
        try:
            sandbox = get_sandbox()
            process_cwd = cwd or sandbox.workspace_root
            r = subprocess.run(
                list(cmd),
                capture_output=True,
                text=True,
                cwd=str(process_cwd),
                env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
                timeout=timeout,
                check=False,
            )
            return r.returncode, r.stdout, r.stderr
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return 1, "", str(exc)

    return await asyncio.to_thread(_sync)


# ── lsp_diagnostics ───────────────────────────────────────────────────────────


async def _lsp_diagnostics(
    path: Annotated[
        str,
        Field(
            description=(
                "File or directory to analyse. Workspace-relative or absolute. "
                "E.g. 'app/auth/service.py' or 'app/'. "
                "Defaults to the workspace root when omitted."
            )
        ),
    ] = ".",
    language: Annotated[
        str | None,
        Field(
            description=(
                "Override auto-detected language. "
                "'python' (ruff), 'typescript' / 'javascript' (tsc). "
                "Null = auto-detect from file extension or workspace contents."
            )
        ),
    ] = None,
    include_warnings: Annotated[
        bool,
        Field(description="Include warnings in addition to errors. Default true."),
    ] = True,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Run static analysis on a file or directory and return diagnostics.

    For Python files/directories, runs ``ruff check`` (fast, zero config).
    For TypeScript/JavaScript, runs ``tsc --noEmit`` from the nearest
    ``tsconfig.json``.

    Returns a structured list of errors (and optionally warnings) with
    file paths, line numbers, and messages — ready for the agent to act on.
    """
    target = _resolve_path(path)
    if not target.exists():
        return f"[Error] Path does not exist: {target}"

    lang = language or (_detect_language(target) if target.is_file() else None)

    # ── Python / ruff ─────────────────────────────────────────────────────────
    if lang == "python" or (lang is None and _looks_like_python_project(target)):
        return await _ruff_diagnostics(target, include_warnings=include_warnings)

    # ── TypeScript / tsc ──────────────────────────────────────────────────────
    if lang in ("typescript", "javascript"):
        return await _tsc_diagnostics(target, include_warnings=include_warnings)

    # ── Unknown — try ruff on any .py files, tsc on any .ts files ─────────────
    parts: list[str] = []
    if target.is_dir():
        has_py = any(target.rglob("*.py"))
        has_ts = any(target.rglob("*.ts"))
        if has_py:
            parts.append(
                await _ruff_diagnostics(target, include_warnings=include_warnings)
            )
        if has_ts:
            parts.append(
                await _tsc_diagnostics(target, include_warnings=include_warnings)
            )
        if parts:
            return "\n\n".join(parts)
    return (
        f"[Info] No recognisable language detected for '{path}'. "
        f"Supported: python (ruff), typescript/javascript (tsc)."
    )


def _looks_like_python_project(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() == ".py"
    return (
        any(path.glob("*.py"))
        or (path / "pyproject.toml").exists()
        or (path / "setup.py").exists()
    )


async def _ruff_diagnostics(target: Path, *, include_warnings: bool) -> str:
    # Try ruff as a module first (most reliable), then as a bare command.
    ruff_cmd = (
        ["python", "-m", "ruff"]
        if shutil.which("python") and not shutil.which("ruff")
        else ["ruff"]
    )
    if not shutil.which(ruff_cmd[0]):
        return "[Error] ruff not found. Install with: pip install ruff"

    cmd = [*ruff_cmd, "check", str(target), "--output-format", "json", "--quiet"]
    if not include_warnings:
        cmd += ["--select", "E,F"]

    rc, stdout, stderr = await _run(
        *cmd, cwd=target if target.is_dir() else target.parent
    )

    if not stdout.strip():
        if rc == 0:
            return f"[OK] No issues found in {target}"
        # Non-JSON error
        return f"[Error] ruff failed: {stderr.strip() or '(no output)'}"

    try:
        issues: list[dict] = json.loads(stdout)
    except json.JSONDecodeError:
        return f"[Error] Could not parse ruff output:\n{stdout[:500]}"

    if not issues:
        return f"[OK] No issues found in {target}"

    capped = issues[:_MAX_DIAG]
    lines = [
        f"{len(issues)} issue(s) found{' (showing first ' + str(_MAX_DIAG) + ')' if len(issues) > _MAX_DIAG else ''}:"
    ]
    for issue in capped:
        loc = issue.get("location", {})
        row = loc.get("row", "?")
        col = loc.get("column", "?")
        filename = Path(issue.get("filename", "?")).name
        code = issue.get("code", "?")
        message = issue.get("message", "")
        lines.append(f"  {filename}:{row}:{col}  {code}  {message}")

    return "\n".join(lines)


async def _tsc_diagnostics(target: Path, *, include_warnings: bool) -> str:
    if not shutil.which("tsc"):
        return "[Info] tsc not found. Install TypeScript: npm install -g typescript"

    # Find nearest tsconfig.json
    tsconfig_dir = target if target.is_dir() else target.parent
    while tsconfig_dir != tsconfig_dir.parent:
        if (tsconfig_dir / "tsconfig.json").exists():
            break
        tsconfig_dir = tsconfig_dir.parent
    else:
        tsconfig_dir = target if target.is_dir() else target.parent

    cmd = ["tsc", "--noEmit", "--pretty", "false"]
    rc, stdout, stderr = await _run(*cmd, cwd=tsconfig_dir)

    combined = (stdout + stderr).strip()
    if not combined:
        return f"[OK] No TypeScript errors found in {target}"

    lines_raw = combined.splitlines()
    # tsc output format: "path(row,col): error TSxxxx: message"
    diag_lines = [ln for ln in lines_raw if ": error TS" in ln or ": warning TS" in ln]
    if not include_warnings:
        diag_lines = [ln for ln in diag_lines if ": error TS" in ln]

    if not diag_lines:
        return f"[OK] No TypeScript errors found in {target}"

    capped = diag_lines[:_MAX_DIAG]
    result = [
        f"{len(diag_lines)} TypeScript issue(s){' (showing first ' + str(_MAX_DIAG) + ')' if len(diag_lines) > _MAX_DIAG else ''}:"
    ]
    for line in capped:
        result.append(f"  {line}")
    return "\n".join(result)


# ── Real language-server tools ───────────────────────────────────────────────


async def _real_lsp_diagnostics(
    path: Annotated[
        str,
        Field(description="Workspace-relative source file to diagnose."),
    ],
    include_warnings: Annotated[
        bool,
        Field(description="Include warnings and informational diagnostics."),
    ] = True,
) -> str:
    """Return live diagnostics published by a persistent language server."""
    target = _resolve_path(path)
    if not target.is_file():
        return f"[Error] LSP diagnostics requires an existing source file: {target}"
    try:
        client = await get_language_server(get_sandbox().workspace_root, target)
        diagnostics = await client.diagnostics(target)
    except LanguageServerUnavailable as exc:
        return f"[Unavailable] {exc} Use static_diagnostics as a fallback."
    if not include_warnings:
        diagnostics = [item for item in diagnostics if item.get("severity") == 1]
    if not diagnostics:
        return f"[OK] Language server reports no issues in {path}"
    lines = [f"{len(diagnostics)} live LSP diagnostic(s):"]
    severity_names = {1: "error", 2: "warning", 3: "info", 4: "hint"}
    for item in diagnostics[:_MAX_DIAG]:
        start = (item.get("range") or {}).get("start") or {}
        severity_value = item.get("severity")
        severity = (
            severity_names.get(severity_value, "diagnostic")
            if isinstance(severity_value, int)
            else "diagnostic"
        )
        code = item.get("code")
        code_text = f" {code}" if code is not None else ""
        lines.append(
            f"  {path}:{int(start.get('line', 0)) + 1}:"
            f"{int(start.get('character', 0)) + 1}  {severity}{code_text}  "
            f"{item.get('message', '')}"
        )
    return "\n".join(lines)


async def _real_lsp_definition(
    path: Annotated[str, Field(description="Source file containing the symbol.")],
    line: Annotated[int, Field(description="1-based symbol line number.", ge=1)],
    column: Annotated[int, Field(description="1-based symbol column number.", ge=1)],
) -> str:
    """Resolve a symbol position through textDocument/definition."""
    target = _resolve_path(path)
    if not target.is_file():
        return f"[Error] Source file does not exist: {target}"
    try:
        client = await get_language_server(get_sandbox().workspace_root, target)
        locations = await client.definition(target, line, column)
    except LanguageServerUnavailable as exc:
        return f"[Unavailable] {exc} Use code_context for a known symbol."
    return _format_lsp_locations(locations, "definition")


async def _real_lsp_references(
    path: Annotated[str, Field(description="Source file containing the symbol.")],
    line: Annotated[int, Field(description="1-based symbol line number.", ge=1)],
    column: Annotated[int, Field(description="1-based symbol column number.", ge=1)],
    include_declaration: Annotated[
        bool,
        Field(description="Include the symbol declaration in results."),
    ] = True,
    limit: Annotated[
        int,
        Field(description="Maximum locations to return.", ge=1, le=100),
    ] = 50,
) -> str:
    """Resolve symbol usages through textDocument/references."""
    target = _resolve_path(path)
    if not target.is_file():
        return f"[Error] Source file does not exist: {target}"
    try:
        client = await get_language_server(get_sandbox().workspace_root, target)
        locations = await client.references(
            target,
            line,
            column,
            include_declaration=include_declaration,
        )
    except LanguageServerUnavailable as exc:
        return f"[Unavailable] {exc} Use code_context for a known symbol."
    return _format_lsp_locations(locations[:limit], "reference")


async def _lsp_semantic(
    action: Annotated[
        Literal[
            "hover",
            "code_actions",
            "rename",
            "format",
            "organize_imports",
            "document_symbols",
            "workspace_symbols",
        ],
        Field(description="Repository-local semantic LSP operation."),
    ],
    path: Annotated[
        str,
        Field(
            description=(
                "Workspace-relative source file. For workspace_symbols, this "
                "selects which language server to query."
            )
        ),
    ],
    line: Annotated[
        int | None,
        Field(description="1-based start/cursor line.", ge=1),
    ] = None,
    column: Annotated[
        int | None,
        Field(description="1-based start/cursor column.", ge=1),
    ] = None,
    end_line: Annotated[
        int | None,
        Field(description="1-based selection end line.", ge=1),
    ] = None,
    end_column: Annotated[
        int | None,
        Field(description="1-based selection end column.", ge=1),
    ] = None,
    new_name: Annotated[
        str | None,
        Field(description="New symbol name for rename."),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Symbol query for workspace_symbols."),
    ] = None,
    tab_size: Annotated[
        int,
        Field(description="Formatting tab size.", ge=1, le=16),
    ] = 4,
    insert_spaces: Annotated[
        bool,
        Field(description="Use spaces instead of tabs when formatting."),
    ] = True,
) -> str:
    """Inspect or calculate semantic edits without mutating the repository."""
    target = _resolve_path(path)
    if not target.is_file():
        return f"[Error] Source file does not exist: {target}"
    try:
        client = await get_language_server(get_sandbox().workspace_root, target)
        if action == "hover":
            cursor_line, cursor_column = _require_position(line, column, action)
            result: Any = await client.hover(target, cursor_line, cursor_column)
        elif action == "code_actions":
            start_line, start_column = _require_position(line, column, action)
            diagnostics = await client.diagnostics(target)
            result = await client.code_actions(
                target,
                start_line=start_line,
                start_column=start_column,
                end_line=end_line or start_line,
                end_column=end_column or start_column,
                diagnostics=diagnostics,
            )
        elif action == "rename":
            cursor_line, cursor_column = _require_position(line, column, action)
            if not new_name or not new_name.strip():
                return "[Error] rename requires a non-empty new_name."
            result = await client.rename(
                target,
                cursor_line,
                cursor_column,
                new_name.strip(),
            )
        elif action == "format":
            result = await client.formatting(
                target,
                tab_size=tab_size,
                insert_spaces=insert_spaces,
            )
        elif action == "organize_imports":
            result = await client.organize_imports(target)
        elif action == "document_symbols":
            result = await client.document_symbols(target)
        else:
            result = await client.workspace_symbols(query or "")
    except (LanguageServerUnavailable, RuntimeError, ValueError) as exc:
        return f"[Unavailable] {exc}"

    if result in (None, [], {}):
        return f"No {action.replace('_', ' ')} result returned by the language server."
    return json.dumps(result, indent=2, ensure_ascii=False)[:40_000]


def _require_position(
    line: int | None, column: int | None, action: str
) -> tuple[int, int]:
    if line is None or column is None:
        raise ValueError(f"{action} requires line and column.")
    return line, column


def _format_lsp_locations(locations: list[dict[str, Any]], kind: str) -> str:
    if not locations:
        return f"No {kind} locations returned by the language server."
    sandbox = get_sandbox()
    rows = [f"{len(locations)} LSP {kind} location(s):"]
    for item in locations:
        uri = item.get("uri") or item.get("targetUri") or ""
        parsed = urlparse(str(uri))
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(str(uri))
        location_range = (
            item.get("targetSelectionRange")
            or item.get("targetRange")
            or item.get("range")
            or {}
        )
        start = location_range.get("start") or {}
        rows.append(
            f"  {sandbox.display_path(path)}:{int(start.get('line', 0)) + 1}:"
            f"{int(start.get('character', 0)) + 1}"
        )
    return "\n".join(rows)


# ── Tool objects ──────────────────────────────────────────────────────────────

static_diagnostics = Tool(
    _lsp_diagnostics,
    name="static_diagnostics",
    tiers=("coding",),
    description=(
        "Run static analysis (ruff for Python, tsc for TypeScript) on a file "
        "or directory and return errors and warnings with file:line locations."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Run static diagnostics for a file or directory.",
    observation_kind="runtime",
    search_aliases=(
        "lint",
        "linter",
        "lints",
        "typecheck",
        "types",
        "error",
        "errors",
        "warning",
        "warnings",
        "ruff",
        "tsc",
        "mypy",
        "eslint",
        "syntax",
    ),
)

lsp_diagnostics = Tool(
    _real_lsp_diagnostics,
    name="lsp_diagnostics",
    tiers=("coding",),
    description=(
        "Return live publishDiagnostics results from a persistent language server. "
        "Requires a supported local language-server binary."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Get live diagnostics from a language server.",
    observation_kind="runtime",
    search_aliases=(
        "lint",
        "typecheck",
        "types",
        "error",
        "errors",
        "warning",
        "warnings",
        "syntax",
        "lsp",
    ),
)

lsp_definition = Tool(
    _real_lsp_definition,
    name="lsp_definition",
    tiers=("coding",),
    description=(
        "Go to definition at an exact source file, line, and column through "
        "the Language Server Protocol."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Resolve a source position with a language server.",
    capabilities=("source_navigation",),
    observation_kind="structural",
)

lsp_references = Tool(
    _real_lsp_references,
    name="lsp_references",
    tiers=("coding",),
    description=(
        "Find references at an exact source position through the Language "
        "Server Protocol."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Find live references with a language server.",
    capabilities=("source_navigation",),
    observation_kind="structural",
)

lsp_semantic = Tool(
    _lsp_semantic,
    name="lsp_semantic",
    tiers=("coding",),
    description=(
        "Inspect hover information, quick-fixes/code actions, repository-local "
        "rename edits, formatting, organize-imports actions, and document or "
        "workspace symbols. It returns proposed edits but never applies them."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Inspect semantic code information or calculate LSP edits.",
    capabilities=("source_navigation", "semantic_edits"),
    observation_kind="structural",
    search_aliases=(
        "hover",
        "quick fix",
        "code action",
        "rename",
        "format",
        "organize imports",
        "symbols",
        "lsp",
    ),
)
