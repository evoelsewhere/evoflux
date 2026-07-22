"""LSP-style code intelligence tools.

Three tools that complement the structural code graph with live analysis:

- ``lsp_diagnostics``  — run static analysis (ruff / tsc) and return
  errors/warnings for a file or directory.
- ``lsp_definition``   — find the definition of a symbol with optional
  file:line context for disambiguation when the same name exists in
  multiple modules.
- ``lsp_references``   — find every location that references a symbol,
  with optional file context.

These sit alongside the code-graph tools: use code-graph for topology
(call chains, class hierarchies) and lsp_* for live correctness checks
and precise location queries.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool


# ── Helpers ───────────────────────────────────────────────────────────────────

_MAX_DIAG = 100  # cap diagnostics returned to agent


def _resolve_path(path: str) -> Path:
    """Resolve *path* relative to the sandbox workspace root."""
    sandbox = get_sandbox()
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    return (sandbox.workspace_root / p).resolve()


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
            r = subprocess.run(
                list(cmd),
                capture_output=True,
                text=True,
                cwd=str(cwd) if cwd else None,
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


# ── lsp_definition ────────────────────────────────────────────────────────────


async def _lsp_definition(
    name: Annotated[
        str,
        Field(description="Symbol name to resolve (function, class, variable, type)."),
    ],
    file: Annotated[
        str | None,
        Field(
            description=(
                "Optional: the file where you encountered the symbol "
                "(workspace-relative). Used to disambiguate when multiple "
                "modules define a symbol with the same name."
            )
        ),
    ] = None,
    line: Annotated[
        int | None,
        Field(
            description=(
                "Optional: the line number in *file* where the symbol appears. "
                "Enables import-aware disambiguation."
            )
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Find the definition of a symbol using the code knowledge graph.

    Accepts an optional file and line to disambiguate when multiple modules
    define a symbol with the same name.  Returns the file path, line number,
    signature, and docstring (if available).

    Use this when you see a symbol in the code and want to jump to where it
    is defined — equivalent to "Go to Definition" in an IDE.
    """
    try:
        from app.core.db import async_session_factory
        import app.services.code_graph_service as svc
    except ImportError as exc:
        return f"[Error] Code graph not available: {exc}"

    sandbox = get_sandbox()
    workspace_path = str(sandbox.workspace_root)

    async with async_session_factory() as db:
        workspace_id = await svc.resolve_workspace_id(db, path=workspace_path)
        if workspace_id is None:
            return (
                "[Info] Workspace not indexed. Run 'Build index' in the Graph tab "
                "or call code_overview to index the workspace."
            )

        matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=10
        )

    if not matches:
        return f"No definition found for '{name}' in the code index."

    # Disambiguate: prefer nodes in same file, then fall back to first match
    if file and len(matches) > 1:
        file_path = str(_resolve_path(file))
        # Normalize to workspace-relative comparison
        workspace = sandbox.workspace_root
        try:
            rel_file = str(Path(file_path).relative_to(workspace))
        except ValueError:
            rel_file = file_path

        same_file = [
            n
            for n in matches
            if n.file_path
            and (
                n.file_path == rel_file
                or n.file_path.endswith(rel_file)
                or rel_file.endswith(n.file_path)
            )
        ]
        if same_file:
            matches = same_file

    node = matches[0]
    lines = [f"[{node.kind}] {node.qualified_name}"]
    if node.file_path:
        loc = f"{node.file_path}"
        if node.line_start:
            loc += f":{node.line_start}"
        lines.append(f"  location : {loc}")
    if node.signature:
        lines.append(f"  signature: {node.signature}")
    if node.docstring:
        first_doc_line = node.docstring.split("\n")[0].strip()
        if first_doc_line:
            lines.append(f"  docstring: {first_doc_line}")
    if len(matches) > 1:
        lines.append(
            f"\n  ({len(matches) - 1} other definition(s) named '{name}' — "
            f"use code_search('{name}') to see all)"
        )

    return "\n".join(lines)


# ── lsp_references ────────────────────────────────────────────────────────────


async def _lsp_references(
    name: Annotated[
        str,
        Field(description="Symbol name whose usages to find."),
    ],
    file: Annotated[
        str | None,
        Field(
            description=(
                "Optional: restrict to the definition found in this file "
                "(helps when multiple modules export the same name)."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum references to return (default 30, max 60)."),
    ] = 30,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Find all places in the codebase that reference a symbol.

    Answers "where is X used?" — callers of a function, importers of a
    class, subclasses of a base, etc.  Backed by the code knowledge graph.

    The optional *file* parameter narrows the definition lookup when the
    same name appears in multiple modules.
    """
    try:
        from app.core.db import async_session_factory
        import app.services.code_graph_service as svc
    except ImportError as exc:
        return f"[Error] Code graph not available: {exc}"

    capped = max(1, min(limit, 60))
    sandbox = get_sandbox()
    workspace_path = str(sandbox.workspace_root)

    async with async_session_factory() as db:
        workspace_id = await svc.resolve_workspace_id(db, path=workspace_path)
        if workspace_id is None:
            return (
                "[Info] Workspace not indexed. Run 'Build index' in the Graph tab "
                "or call code_overview to index the workspace."
            )

        matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=10
        )

        if not matches:
            return f"No symbol named '{name}' found in the code index."

        # File-based disambiguation (same as lsp_definition)
        if file and len(matches) > 1:
            file_path = str(_resolve_path(file))
            workspace = sandbox.workspace_root
            try:
                rel_file = str(Path(file_path).relative_to(workspace))
            except ValueError:
                rel_file = file_path
            same_file = [
                n
                for n in matches
                if n.file_path
                and (
                    n.file_path == rel_file
                    or n.file_path.endswith(rel_file)
                    or rel_file.endswith(n.file_path)
                )
            ]
            if same_file:
                matches = same_file

        node = matches[0]
        refs = await svc.find_references(
            db, workspace_id=workspace_id, node_id=node.id, limit=capped
        )

    if not refs:
        return (
            f"[{node.kind}] {node.qualified_name}  ({node.file_path})\n"
            f"  No references found."
        )

    head = (
        f"[{node.kind}] {node.qualified_name}  "
        f"({node.file_path}:{node.line_start})\n"
        f"{len(refs)} reference(s):"
    )
    rows: list[str] = []
    for edge_kind, src_node, line_no in refs:
        loc = (
            f"{src_node.file_path}:{line_no}" if line_no else src_node.file_path or "?"
        )
        rows.append(
            f"  {edge_kind:<12} [{src_node.kind}] {src_node.qualified_name}  — {loc}"
        )
    return head + "\n" + "\n".join(rows)


# ── Tool objects ──────────────────────────────────────────────────────────────

lsp_diagnostics = Tool(
    _lsp_diagnostics,
    name="lsp_diagnostics",
    description=(
        "Run static analysis (ruff for Python, tsc for TypeScript) on a file "
        "or directory and return errors and warnings with file:line locations."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Run static diagnostics for a file or directory.",
)

lsp_definition = Tool(
    _lsp_definition,
    name="lsp_definition",
    description=(
        "Find the definition of a symbol (function, class, variable) in the "
        "code graph. Accepts an optional file+line to disambiguate when the "
        "same name exists in multiple modules."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Find the definition of a code symbol.",
)

lsp_references = Tool(
    _lsp_references,
    name="lsp_references",
    description=(
        "Find every location in the codebase that references a symbol — callers, "
        "importers, subclasses, decorators. Backed by the code knowledge graph."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Find references to a code symbol across the workspace.",
)
