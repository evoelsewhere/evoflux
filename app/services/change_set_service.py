"""Guarded, repository-local semantic change proposals.

ChangeSets are intentionally short-lived review objects. They hold proposed
UTF-8 file contents, base hashes/document versions, and unified previews. An
apply validates every selected base before writing anything, then rolls back
already-written files if a later atomic replacement fails.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse
from uuid import uuid4

from app.agent.tools.builtin.filesystem._atomic import atomic_write_bytes

ChangeSetOrigin = Literal["lsp", "ai", "agent", "review", "git"]
ChangeSetStatus = Literal["pending", "applied", "rejected", "partial"]
ChangeFileStatus = Literal["pending", "applied", "rejected"]

_MAX_FILES = 100
_MAX_FILE_BYTES = 2_000_000
_MAX_TOTAL_BYTES = 10_000_000
_TTL_SECONDS = 60 * 60


class ChangeSetError(ValueError):
    """Base error for invalid or unavailable proposals."""


class ChangeSetNotFound(ChangeSetError):
    """The requested proposal is absent or expired."""


class ChangeSetStale(ChangeSetError):
    """One or more files changed since the proposal was built."""

    def __init__(self, paths: list[str]) -> None:
        self.paths = sorted(paths)
        super().__init__("Files changed since preview: " + ", ".join(self.paths))


@dataclass(frozen=True, slots=True)
class ChangeFileInput:
    path: str
    proposed_content: str
    base_hash: str | None = None
    document_version: int | None = None


@dataclass(slots=True)
class ChangeFile:
    path: str
    base_hash: str | None
    proposed_hash: str
    base_content: str
    proposed_content: str
    document_version: int | None
    diff: str
    additions: int
    deletions: int
    status: ChangeFileStatus = "pending"


@dataclass(slots=True)
class ChangeSet:
    id: str
    workspace: str
    origin: ChangeSetOrigin
    title: str
    description: str | None
    files: list[ChangeFile]
    status: ChangeSetStatus = "pending"
    snapshot_hash: str | None = None
    verification_commands: list[str] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_change_sets: dict[str, ChangeSet] = {}
_workspace_locks: dict[str, asyncio.Lock] = {}


def _workspace_lock(workspace: Path) -> asyncio.Lock:
    key = str(workspace.resolve())
    lock = _workspace_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _workspace_locks[key] = lock
    return lock


def create_change_set(
    workspace: Path,
    *,
    origin: ChangeSetOrigin,
    title: str,
    description: str | None = None,
    files: list[ChangeFileInput] | None = None,
    workspace_edit: dict[str, Any] | None = None,
    verification_commands: list[str] | None = None,
) -> ChangeSet:
    """Create a guarded proposal from full contents and/or an LSP WorkspaceEdit."""
    root = workspace.resolve()
    inputs = list(files or [])
    if workspace_edit:
        inputs.extend(inputs_from_workspace_edit(root, workspace_edit))
    if not inputs:
        raise ChangeSetError("A ChangeSet requires at least one file proposal.")
    if len(inputs) > _MAX_FILES:
        raise ChangeSetError(f"A ChangeSet may contain at most {_MAX_FILES} files.")

    by_path: dict[str, ChangeFileInput] = {}
    for item in inputs:
        normalized = _normalize_relative_path(root, item.path)
        if normalized in by_path:
            raise ChangeSetError(f"Duplicate file proposal: {normalized}")
        by_path[normalized] = ChangeFileInput(
            path=normalized,
            proposed_content=item.proposed_content,
            base_hash=item.base_hash,
            document_version=item.document_version,
        )

    total_bytes = 0
    proposed_files: list[ChangeFile] = []
    stale: list[str] = []
    for path, item in by_path.items():
        target = root / path
        original = _read_utf8(target)
        current_hash = (
            _hash_bytes(original.encode("utf-8")) if original is not None else None
        )
        if item.base_hash is not None and item.base_hash != current_hash:
            stale.append(path)
            continue
        proposed_bytes = item.proposed_content.encode("utf-8")
        if len(proposed_bytes) > _MAX_FILE_BYTES:
            raise ChangeSetError(f"Proposed file is too large: {path}")
        total_bytes += len(proposed_bytes)
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ChangeSetError("ChangeSet proposed content exceeds 10 MB.")
        diff, additions, deletions = _preview_diff(
            path, original or "", item.proposed_content
        )
        proposed_files.append(
            ChangeFile(
                path=path,
                base_hash=current_hash,
                proposed_hash=_hash_bytes(proposed_bytes),
                base_content=original or "",
                proposed_content=item.proposed_content,
                document_version=item.document_version,
                diff=diff,
                additions=additions,
                deletions=deletions,
            )
        )
    if stale:
        raise ChangeSetStale(stale)

    _purge_expired()
    record = ChangeSet(
        id=str(uuid4()),
        workspace=str(root),
        origin=origin,
        title=title.strip() or "Proposed changes",
        description=description,
        files=proposed_files,
        verification_commands=_verification_commands(
            root,
            [item.path for item in proposed_files],
            verification_commands or [],
        ),
    )
    _change_sets[record.id] = record
    return record


async def apply_change_set(
    change_set_id: str,
    workspace: Path,
    *,
    paths: list[str] | None = None,
    session_id: str | None = None,
    verify: bool = True,
) -> ChangeSet:
    """Apply selected pending files after validating every base hash."""
    root = workspace.resolve()
    record = get_change_set(change_set_id, root)
    selected = _select_pending(record, paths)
    if not selected:
        raise ChangeSetError("No pending files selected for apply.")

    async with _workspace_lock(root):
        stale = [
            item.path
            for item in selected
            if _current_hash(root / item.path) != item.base_hash
        ]
        if stale:
            raise ChangeSetStale(stale)

        if session_id:
            from app.services import snapshot_service

            record.snapshot_hash = await snapshot_service.track(session_id, root)

        originals: dict[str, bytes | None] = {}
        applied: list[ChangeFile] = []
        try:
            for item in selected:
                target = root / item.path
                originals[item.path] = target.read_bytes() if target.exists() else None
            for item in selected:
                target = root / item.path
                atomic_write_bytes(target, item.proposed_content.encode("utf-8"))
                applied.append(item)
        except Exception as exc:
            for item in reversed(applied):
                target = root / item.path
                original = originals[item.path]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(target, original)
            raise ChangeSetError(
                f"Atomic apply failed and was rolled back: {exc}"
            ) from exc

        for item in selected:
            item.status = "applied"
        record.updated_at = time.time()
        _refresh_status(record)
    if verify:
        record.verification = await verify_change_set(
            record,
            root,
            paths=[item.path for item in selected],
            session_id=session_id,
        )
        record.updated_at = time.time()
    return record


def reject_change_set(
    change_set_id: str, workspace: Path, *, paths: list[str] | None = None
) -> ChangeSet:
    """Reject selected pending files without mutating the repository."""
    record = get_change_set(change_set_id, workspace.resolve())
    selected = _select_pending(record, paths)
    if not selected:
        raise ChangeSetError("No pending files selected for rejection.")
    for item in selected:
        item.status = "rejected"
    record.updated_at = time.time()
    _refresh_status(record)
    return record


def get_change_set(change_set_id: str, workspace: Path) -> ChangeSet:
    _purge_expired()
    record = _change_sets.get(change_set_id)
    if record is None or record.workspace != str(workspace.resolve()):
        raise ChangeSetNotFound("ChangeSet not found or expired.")
    return record


def get_change_file_contents(
    change_set_id: str, workspace: Path, path: str
) -> dict[str, Any]:
    record = get_change_set(change_set_id, workspace)
    normalized = _normalize_relative_path(workspace.resolve(), path)
    item = next((row for row in record.files if row.path == normalized), None)
    if item is None:
        raise ChangeSetNotFound("ChangeSet file not found.")
    return {
        "path": item.path,
        "base_hash": item.base_hash,
        "proposed_hash": item.proposed_hash,
        "original_content": item.base_content,
        "proposed_content": item.proposed_content,
        "document_version": item.document_version,
        "status": item.status,
    }


def serialize_change_set(record: ChangeSet) -> dict[str, Any]:
    return {
        "id": record.id,
        "workspace": record.workspace,
        "origin": record.origin,
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "snapshot_hash": record.snapshot_hash,
        "verification_commands": record.verification_commands,
        "verification": record.verification,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "files": [
            {
                "path": item.path,
                "base_hash": item.base_hash,
                "proposed_hash": item.proposed_hash,
                "document_version": item.document_version,
                "diff": item.diff,
                "additions": item.additions,
                "deletions": item.deletions,
                "status": item.status,
            }
            for item in record.files
        ],
    }


def inputs_from_workspace_edit(
    workspace: Path, workspace_edit: dict[str, Any]
) -> list[ChangeFileInput]:
    """Convert LSP text edits to guarded full-content proposals."""
    edits_by_path: dict[str, list[dict[str, Any]]] = {}
    versions: dict[str, int | None] = {}
    raw_changes = workspace_edit.get("changes")
    if isinstance(raw_changes, dict):
        for uri, edits in raw_changes.items():
            path = _path_from_uri(workspace, str(uri))
            if isinstance(edits, list):
                edits_by_path.setdefault(path, []).extend(
                    edit for edit in edits if isinstance(edit, dict)
                )

    document_changes = workspace_edit.get("documentChanges")
    if isinstance(document_changes, list):
        for change in document_changes:
            if not isinstance(change, dict) or "textDocument" not in change:
                raise ChangeSetError(
                    "LSP resource create/rename/delete operations are not supported."
                )
            document = change.get("textDocument")
            edits = change.get("edits")
            if not isinstance(document, dict) or not isinstance(edits, list):
                raise ChangeSetError("Invalid TextDocumentEdit in WorkspaceEdit.")
            path = _path_from_uri(workspace, str(document.get("uri") or ""))
            edits_by_path.setdefault(path, []).extend(
                edit for edit in edits if isinstance(edit, dict)
            )
            raw_version = document.get("version")
            versions[path] = raw_version if isinstance(raw_version, int) else None

    if not edits_by_path:
        raise ChangeSetError("WorkspaceEdit contains no text edits.")

    result: list[ChangeFileInput] = []
    for path, edits in edits_by_path.items():
        target = workspace / path
        original = _read_utf8(target)
        if original is None:
            raise ChangeSetError(f"LSP text edit target does not exist: {path}")
        proposed = _apply_lsp_text_edits(original, edits)
        result.append(
            ChangeFileInput(
                path=path,
                proposed_content=proposed,
                base_hash=_hash_bytes(original.encode("utf-8")),
                document_version=versions.get(path),
            )
        )
    return result


async def verify_change_set(
    record: ChangeSet,
    workspace: Path,
    *,
    paths: list[str],
    session_id: str | None,
) -> list[dict[str, Any]]:
    """Run bounded LSP checks and allowlisted existing verification commands."""
    results: list[dict[str, Any]] = []
    from app.agent.lsp_manager import (
        LanguageServerUnavailable,
        get_language_server,
        language_server_spec,
    )
    from app.agent.sandbox import SandboxConfig, set_sandbox
    from app.services.problems_service import (
        ProblemInput,
        ProblemSeverity,
        publish_problems,
    )

    token = set_sandbox(SandboxConfig(workspace=str(workspace), session_id=session_id))
    try:
        for relative in paths:
            target = workspace / relative
            if not target.is_file() or language_server_spec(target) is None:
                continue
            try:
                client = await get_language_server(workspace, target)
                diagnostics = await client.diagnostics(
                    target, require_current_version=True
                )
                severity: dict[int, ProblemSeverity] = {
                    1: "error",
                    2: "warning",
                    3: "info",
                    4: "hint",
                }
                problem_inputs: list[ProblemInput] = []
                for item in diagnostics[:200]:
                    raw_severity = item.get("severity")
                    problem_severity: ProblemSeverity = (
                        severity.get(raw_severity, "warning")
                        if isinstance(raw_severity, int)
                        else "warning"
                    )
                    start = (item.get("range") or {}).get("start") or {}
                    problem_inputs.append(
                        ProblemInput(
                            message=str(item.get("message") or "LSP problem"),
                            severity=problem_severity,
                            path=relative,
                            line=int(start.get("line", 0)) + 1,
                            column=int(start.get("character", 0)) + 1,
                            code=(
                                str(item["code"])
                                if item.get("code") is not None
                                else None
                            ),
                            provenance={"producer": item.get("source") or "LSP"},
                        )
                    )
                publish_problems(
                    workspace,
                    source="lsp",
                    scope=f"lsp:{relative}",
                    problems=problem_inputs,
                    session_id=session_id,
                )
                results.append(
                    {
                        "kind": "lsp",
                        "path": relative,
                        "status": "passed" if not diagnostics else "failed",
                        "diagnostics": len(diagnostics),
                        "note": "LSP diagnostics do not replace behavioral tests.",
                    }
                )
            except (LanguageServerUnavailable, OSError, RuntimeError) as exc:
                results.append(
                    {
                        "kind": "lsp",
                        "path": relative,
                        "status": "unavailable",
                        "message": str(exc),
                    }
                )

        for command in record.verification_commands:
            results.append(
                await _run_verification_command(
                    workspace, command, session_id=session_id
                )
            )
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)
    return results


async def _run_verification_command(
    workspace: Path, command: str, *, session_id: str | None
) -> dict[str, Any]:
    argv = shlex.split(command, posix=os.name != "nt")
    if not argv:
        return {"kind": "command", "command": command, "status": "skipped"}
    try:
        from app.agent.tools.builtin.shell import _scrubbed_env

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workspace),
            env=_scrubbed_env(inherit=False),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=120)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > 32_000:
            output = output[-32_000:]
        status = "passed" if process.returncode == 0 else "failed"
        from app.agent.hooks.problem_capture import publish_command_output

        publish_command_output(
            workspace,
            command=command,
            result=f"[{'Succeeded' if status == 'passed' else 'Failed'}]\n{output}",
            session_id=session_id,
        )
        return {
            "kind": "command",
            "command": command,
            "status": status,
            "exit_code": process.returncode,
            "output": output,
        }
    except TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        return {
            "kind": "command",
            "command": command,
            "status": "failed",
            "message": "Timed out after 120 seconds.",
        }
    except OSError as exc:
        return {
            "kind": "command",
            "command": command,
            "status": "unavailable",
            "message": str(exc),
        }


def _apply_lsp_text_edits(content: str, edits: list[dict[str, Any]]) -> str:
    normalized: list[tuple[int, int, str]] = []
    for edit in edits:
        raw_range = edit.get("range")
        new_text = edit.get("newText")
        if not isinstance(raw_range, dict) or not isinstance(new_text, str):
            raise ChangeSetError("Invalid LSP TextEdit.")
        start = raw_range.get("start")
        end = raw_range.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            raise ChangeSetError("Invalid LSP TextEdit range.")
        start_offset = _utf16_offset(content, start)
        end_offset = _utf16_offset(content, end)
        if start_offset > end_offset:
            raise ChangeSetError("LSP TextEdit has an inverted range.")
        normalized.append((start_offset, end_offset, new_text))

    normalized.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(normalized, normalized[1:]):
        if current[0] < previous[1]:
            raise ChangeSetError("Overlapping LSP TextEdits are not safe to apply.")
    result = content
    for start, end, replacement in reversed(normalized):
        result = result[:start] + replacement + result[end:]
    return result


def _utf16_offset(content: str, position: dict[str, Any]) -> int:
    line = position.get("line")
    character = position.get("character")
    if (
        not isinstance(line, int)
        or not isinstance(character, int)
        or line < 0
        or character < 0
    ):
        raise ChangeSetError("Invalid LSP position.")
    lines = content.splitlines(keepends=True)
    if line == len(lines) and character == 0:
        return len(content)
    if line >= len(lines):
        raise ChangeSetError("LSP position is outside the document.")
    line_text = lines[line]
    logical_line = line_text.rstrip("\r\n")
    used = 0
    for index, char in enumerate(logical_line):
        if used == character:
            return sum(len(part) for part in lines[:line]) + index
        used += len(char.encode("utf-16-le")) // 2
        if used > character:
            raise ChangeSetError("LSP position splits a UTF-16 surrogate pair.")
    if used == character:
        return sum(len(part) for part in lines[:line]) + len(logical_line)
    raise ChangeSetError("LSP character offset is outside the line.")


def _path_from_uri(workspace: Path, uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ChangeSetError(f"Only file:// WorkspaceEdit URIs are supported: {uri}")
    path = Path(unquote(parsed.path)).resolve()
    try:
        return path.relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        raise ChangeSetError("WorkspaceEdit target escapes the repository.") from exc


def _normalize_relative_path(workspace: Path, raw_path: str) -> str:
    candidate = Path(raw_path)
    if candidate.is_absolute() or (len(raw_path) >= 2 and raw_path[1] == ":"):
        raise ChangeSetError("ChangeSet paths must be repository-relative.")
    resolved = (workspace / candidate).resolve(strict=False)
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise ChangeSetError("ChangeSet path escapes the repository.") from exc
    if not relative.parts:
        raise ChangeSetError("ChangeSet path cannot be the repository root.")
    return relative.as_posix()


def normalize_change_path(workspace: Path, raw_path: str) -> str:
    """Public path guard shared by proposal producers before construction."""
    return _normalize_relative_path(workspace.resolve(), raw_path)


def _read_utf8(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ChangeSetError(f"ChangeSet target is not a file: {path}")
    data = path.read_bytes()
    if len(data) > _MAX_FILE_BYTES:
        raise ChangeSetError(f"Existing file is too large: {path.name}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChangeSetError(
            f"ChangeSet target is not UTF-8 text: {path.name}"
        ) from exc


def _preview_diff(path: str, original: str, proposed: str) -> tuple[str, int, int]:
    rows = list(
        difflib.unified_diff(
            original.splitlines(),
            proposed.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    additions = sum(
        1 for row in rows if row.startswith("+") and not row.startswith("+++")
    )
    deletions = sum(
        1 for row in rows if row.startswith("-") and not row.startswith("---")
    )
    return "\n".join(rows), additions, deletions


def _current_hash(path: Path) -> str | None:
    return _hash_bytes(path.read_bytes()) if path.exists() and path.is_file() else None


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _select_pending(record: ChangeSet, paths: list[str] | None) -> list[ChangeFile]:
    requested = set(paths or [])
    if requested:
        known = {item.path for item in record.files}
        unknown = sorted(requested - known)
        if unknown:
            raise ChangeSetError("Unknown ChangeSet paths: " + ", ".join(unknown))
    return [
        item
        for item in record.files
        if item.status == "pending" and (not requested or item.path in requested)
    ]


def _verification_commands(
    workspace: Path, paths: list[str], requested: list[str]
) -> list[str]:
    # Model-provided command strings are suggestions, never executable
    # authority. In particular, an allowlisted launcher such as ``python`` or
    # ``npm`` can execute arbitrary code through ``-c``/``exec``. Verification
    # is therefore derived only from deterministic, existing project files.
    del requested

    candidates = [workspace / path for path in paths]
    if (workspace / "pyproject.toml").is_file() and (workspace / "tests").is_dir():
        return [
            "uv run pytest --no-cov -q"
            if (workspace / "uv.lock").is_file()
            else "pytest -q"
        ]
    if (workspace / "Cargo.toml").is_file():
        return ["cargo test"]
    if (workspace / "go.mod").is_file():
        return ["go test ./..."]

    package_roots: list[Path] = []
    for candidate in candidates:
        current = candidate.parent
        while current == workspace or workspace in current.parents:
            if (current / "package.json").is_file():
                package_roots.append(current)
                break
            if current == workspace:
                break
            current = current.parent
    for package_root in package_roots:
        try:
            package = json.loads((package_root / "package.json").read_text())
        except (OSError, ValueError):
            continue
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if not isinstance(scripts, dict) or "test" not in scripts:
            continue
        prefix = package_root.relative_to(workspace).as_posix()
        cwd_arg = f" --cwd {shlex.quote(prefix)}" if prefix != "." else ""
        if (workspace / "bun.lock").is_file() or (workspace / "bun.lockb").is_file():
            return [f"bun{cwd_arg} run test"]
        if (workspace / "pnpm-lock.yaml").is_file():
            return [f"pnpm{cwd_arg} test"]
        return [f"npm{cwd_arg} test"]
    return []


def _refresh_status(record: ChangeSet) -> None:
    states = {item.status for item in record.files}
    if states == {"applied"}:
        record.status = "applied"
    elif states == {"rejected"}:
        record.status = "rejected"
    elif "pending" in states:
        record.status = "pending" if len(states) == 1 else "partial"
    else:
        record.status = "partial"


def _purge_expired() -> None:
    cutoff = time.time() - _TTL_SECONDS
    expired = [
        change_set_id
        for change_set_id, record in _change_sets.items()
        if record.updated_at < cutoff
    ]
    for change_set_id in expired:
        _change_sets.pop(change_set_id, None)


def clear_change_sets() -> None:
    """Test/shutdown helper."""
    _change_sets.clear()
    _workspace_locks.clear()
