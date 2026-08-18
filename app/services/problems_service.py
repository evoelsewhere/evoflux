"""Unified in-memory Problems hub for one repository workspace."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ProblemSource = Literal[
    "lsp",
    "static",
    "build",
    "test",
    "ai_review",
    "security",
    "plugin",
]
ProblemSeverity = Literal["error", "warning", "info", "hint"]
ProblemStatus = Literal["open", "dismissed", "suppressed"]


class ProblemError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProblemInput:
    message: str
    severity: ProblemSeverity = "warning"
    path: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    code: str | None = None
    title: str | None = None
    details: str | None = None
    fix: dict[str, Any] | None = None
    suppression_key: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Problem:
    id: str
    workspace: str
    source: ProblemSource
    scope: str
    message: str
    severity: ProblemSeverity
    path: str | None
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None
    code: str | None
    title: str | None
    details: str | None
    fix: dict[str, Any] | None
    suppression_key: str
    provenance: dict[str, Any]
    session_id: str | None = None
    status: ProblemStatus = "open"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_problems: dict[str, dict[str, Problem]] = {}
_suppressions: dict[str, set[str]] = {}


def publish_problems(
    workspace: str | Path,
    *,
    source: ProblemSource,
    scope: str,
    problems: list[ProblemInput],
    session_id: str | None = None,
) -> list[Problem]:
    """Replace one producer scope while preserving matching user decisions."""
    root = str(Path(workspace).resolve())
    workspace_store = _problems.setdefault(root, {})
    suppressed = _suppressions.setdefault(root, set())
    incoming: dict[str, Problem] = {}
    now = time.time()
    for item in problems:
        relative_path = _normalize_optional_path(Path(root), item.path)
        suppression_key = item.suppression_key or _default_suppression_key(
            source, item.code, item.message
        )
        problem_id = _problem_id(
            root,
            source,
            scope,
            relative_path,
            item.line,
            item.column,
            item.code,
            item.message,
        )
        previous = workspace_store.get(problem_id)
        status: ProblemStatus = (
            "suppressed" if suppression_key in suppressed else "open"
        )
        if previous is not None and previous.status == "dismissed":
            status = "dismissed"
        incoming[problem_id] = Problem(
            id=problem_id,
            workspace=root,
            source=source,
            scope=scope,
            message=item.message,
            severity=item.severity,
            path=relative_path,
            line=item.line,
            column=item.column,
            end_line=item.end_line,
            end_column=item.end_column,
            code=item.code,
            title=item.title,
            details=item.details,
            fix=item.fix,
            suppression_key=suppression_key,
            provenance=dict(item.provenance),
            session_id=session_id,
            status=status,
            created_at=previous.created_at if previous is not None else now,
            updated_at=now,
        )

    stale_ids = [
        problem_id
        for problem_id, problem in workspace_store.items()
        if problem.source == source
        and problem.scope == scope
        and problem_id not in incoming
    ]
    for problem_id in stale_ids:
        workspace_store.pop(problem_id, None)
    workspace_store.update(incoming)
    return list(incoming.values())


def list_problems(
    workspace: str | Path,
    *,
    sources: set[ProblemSource] | None = None,
    include_resolved: bool = False,
) -> list[Problem]:
    root = str(Path(workspace).resolve())
    rows = list(_problems.get(root, {}).values())
    if sources:
        rows = [problem for problem in rows if problem.source in sources]
    if not include_resolved:
        rows = [problem for problem in rows if problem.status == "open"]
    severity_order = {"error": 0, "warning": 1, "info": 2, "hint": 3}
    return sorted(
        rows,
        key=lambda item: (
            severity_order[item.severity],
            item.path or "",
            item.line or 0,
            item.message,
        ),
    )


def dismiss_problem(workspace: str | Path, problem_id: str) -> Problem:
    problem = _require_problem(workspace, problem_id)
    problem.status = "dismissed"
    problem.updated_at = time.time()
    return problem


def suppress_problem(workspace: str | Path, problem_id: str) -> Problem:
    problem = _require_problem(workspace, problem_id)
    root = str(Path(workspace).resolve())
    _suppressions.setdefault(root, set()).add(problem.suppression_key)
    for row in _problems.get(root, {}).values():
        if row.suppression_key == problem.suppression_key:
            row.status = "suppressed"
            row.updated_at = time.time()
    return problem


def serialize_problem(problem: Problem) -> dict[str, Any]:
    return {
        "id": problem.id,
        "workspace": problem.workspace,
        "source": problem.source,
        "scope": problem.scope,
        "message": problem.message,
        "severity": problem.severity,
        "path": problem.path,
        "line": problem.line,
        "column": problem.column,
        "end_line": problem.end_line,
        "end_column": problem.end_column,
        "code": problem.code,
        "title": problem.title,
        "details": problem.details,
        "fix": problem.fix,
        "suppression_key": problem.suppression_key,
        "provenance": problem.provenance,
        "session_id": problem.session_id,
        "status": problem.status,
        "created_at": problem.created_at,
        "updated_at": problem.updated_at,
    }


def clear_problems() -> None:
    _problems.clear()
    _suppressions.clear()


def _require_problem(workspace: str | Path, problem_id: str) -> Problem:
    root = str(Path(workspace).resolve())
    problem = _problems.get(root, {}).get(problem_id)
    if problem is None:
        raise ProblemError("Problem not found.")
    return problem


def _normalize_optional_path(workspace: Path, raw_path: str | None) -> str | None:
    if raw_path is None:
        return None
    candidate = Path(raw_path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (workspace / candidate).resolve()
    )
    try:
        return resolved.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ProblemError("Problem path escapes the repository.") from exc


def _default_suppression_key(
    source: ProblemSource, code: str | None, message: str
) -> str:
    return f"{source}:{code or message}"


def _problem_id(
    workspace: str,
    source: str,
    scope: str,
    path: str | None,
    line: int | None,
    column: int | None,
    code: str | None,
    message: str,
) -> str:
    payload = "\0".join(
        (
            workspace,
            source,
            scope,
            path or "",
            str(line or ""),
            str(column or ""),
            code or "",
            message,
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]
