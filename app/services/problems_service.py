"""Unified in-memory Problems hub for one repository workspace."""

from __future__ import annotations

import hashlib
import json
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

#: Findings are derived state — every producer republishes them — but the
#: user's decisions about them are not reproducible by anything. Losing a
#: suppression to a backend restart means the rule the user silenced comes
#: back red, so decisions live on disk beside the repository they describe.
_DECISIONS_FILENAME = "problems-decisions.json"
_loaded_roots: set[str] = set()


def _decisions_path(root: str) -> Path:
    return Path(root) / ".evoflux" / _DECISIONS_FILENAME


def _load_decisions(root: str) -> None:
    """Read this workspace's decisions once per process."""
    if root in _loaded_roots:
        return
    _loaded_roots.add(root)
    try:
        raw = json.loads(_decisions_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    keys = raw.get("suppressions")
    if isinstance(keys, list):
        _suppressions.setdefault(root, set()).update(
            key for key in keys if isinstance(key, str)
        )
    ids = raw.get("dismissed")
    if isinstance(ids, list):
        _dismissed.setdefault(root, set()).update(
            item for item in ids if isinstance(item, str)
        )


def _save_decisions(root: str) -> None:
    path = _decisions_path(root)
    payload = {
        "suppressions": sorted(_suppressions.get(root, set())),
        "dismissed": sorted(_dismissed.get(root, set())),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        # A read-only or missing workspace must not break publishing.
        pass


#: Dismissals are keyed by problem id, which survives only while the finding
#: keeps its exact message and position — that is the intended lifetime.
_dismissed: dict[str, set[str]] = {}


def publish_problems(
    workspace: str | Path,
    *,
    source: ProblemSource,
    scope: str,
    problems: list[ProblemInput],
    session_id: str | None = None,
    supersedes_prefix: str | None = None,
) -> list[Problem]:
    """Replace one producer scope while preserving matching user decisions.

    ``supersedes_prefix`` retires sibling scopes of the same source that
    share the prefix. A producer whose scope carries a per-run hash — a
    command, a content digest — otherwise never clears anything: each run
    lands in a scope of its own and the previous run's findings stay in the
    panel forever, including the ones the run just proved fixed.
    """
    root = str(Path(workspace).resolve())
    _load_decisions(root)
    workspace_store = _problems.setdefault(root, {})
    suppressed = _suppressions.setdefault(root, set())
    dismissed = _dismissed.setdefault(root, set())
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
        # Read the dismissal from the record rather than from the row it
        # replaces: a restarted backend has no previous row to carry it.
        if problem_id in dismissed:
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
        and problem_id not in incoming
        and (
            problem.scope == scope
            or (
                supersedes_prefix is not None
                and problem.scope.startswith(supersedes_prefix)
            )
        )
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
    _load_decisions(root)
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
    root = str(Path(workspace).resolve())
    problem.status = "dismissed"
    problem.updated_at = time.time()
    _dismissed.setdefault(root, set()).add(problem_id)
    _save_decisions(root)
    return problem


def suppress_problem(workspace: str | Path, problem_id: str) -> Problem:
    problem = _require_problem(workspace, problem_id)
    root = str(Path(workspace).resolve())
    _suppressions.setdefault(root, set()).add(problem.suppression_key)
    _save_decisions(root)
    for row in _problems.get(root, {}).values():
        if row.suppression_key == problem.suppression_key:
            row.status = "suppressed"
            row.updated_at = time.time()
    return problem


def restore_problem(workspace: str | Path, problem_id: str) -> Problem:
    """Undo a dismissal or a suppression.

    Both decisions were one-way: a suppression key, once added, stayed for
    the life of the process, and the panel offered no way back. Suppressing
    is workspace-wide, so restoring lifts it for every row that shares the
    key rather than only the one the user clicked.
    """
    problem = _require_problem(workspace, problem_id)
    root = str(Path(workspace).resolve())
    now = time.time()
    suppressed = _suppressions.setdefault(root, set())
    if problem.suppression_key in suppressed:
        suppressed.discard(problem.suppression_key)
        for row in _problems.get(root, {}).values():
            if row.suppression_key == problem.suppression_key and (
                row.status == "suppressed"
            ):
                row.status = "open"
                row.updated_at = now
    _dismissed.setdefault(root, set()).discard(problem_id)
    problem.status = "open"
    problem.updated_at = now
    _save_decisions(root)
    return problem


def suppression_blast_radius(workspace: str | Path, problem_id: str) -> int:
    """How many currently-known rows a suppression would hide."""
    problem = _require_problem(workspace, problem_id)
    root = str(Path(workspace).resolve())
    return sum(
        1
        for row in _problems.get(root, {}).values()
        if row.suppression_key == problem.suppression_key and row.status != "dismissed"
    )


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
    _dismissed.clear()
    _loaded_roots.clear()


def _require_problem(workspace: str | Path, problem_id: str) -> Problem:
    root = str(Path(workspace).resolve())
    _load_decisions(root)
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
