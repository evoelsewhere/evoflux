"""Turn-scoped file-change tracker for Cursor-like Changes review.

Accumulates workspace-relative paths touched by ``edit|write|patch|rm``
during an agent turn. On turn completion the coordinator flushes a
``turn_changes`` SSE event and keeps the latest snapshot for REST fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FILE_MUTATING_TOOLS: frozenset[str] = frozenset({"edit", "write", "patch", "rm"})

ChangeStatus = Literal["added", "modified", "removed", "changed"]


@dataclass
class ChangedFile:
    path: str
    status: ChangeStatus = "changed"
    additions: int | None = None
    deletions: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": self.path, "status": self.status}
        if self.additions is not None:
            out["additions"] = self.additions
        if self.deletions is not None:
            out["deletions"] = self.deletions
        return out


@dataclass
class TurnChangesSnapshot:
    session_id: str
    files: list[ChangedFile] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "additions": self.additions,
            "deletions": self.deletions,
            "files": [f.to_dict() for f in self.files],
        }


_active: dict[str, dict[str, ChangedFile]] = {}
_latest: dict[str, TurnChangesSnapshot] = {}


def _norm_path(raw: str) -> str:
    return raw.strip().replace("\\", "/")


def _path_from_args(tool_name: str, args: dict[str, Any]) -> str | None:
    raw = args.get("file_path") or args.get("path") or args.get("target")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _norm_path(raw)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def _stats_for_edit(args: dict[str, Any]) -> tuple[int | None, int | None]:
    old = args.get("old_string")
    new = args.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return None, None
    old_n = _line_count(old)
    new_n = _line_count(new)
    # Cheap line-count delta (matches Cursor chip intent; not a full LCS).
    if new_n >= old_n:
        return new_n - old_n, 0
    return 0, old_n - new_n


def _stats_for_write(args: dict[str, Any]) -> tuple[int | None, int | None]:
    content = args.get("content")
    if not isinstance(content, str):
        return None, None
    return _line_count(content), 0


def _parse_patch_ops(
    patch_text: str,
) -> list[tuple[str, ChangeStatus, int, int]]:
    """Extract (path, status, additions, deletions) from apply-patch text."""
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        return []

    ops: list[tuple[str, ChangeStatus, int, int]] = []
    path: str | None = None
    status: ChangeStatus = "modified"
    additions = 0
    deletions = 0

    def flush() -> None:
        nonlocal path, status, additions, deletions
        if path:
            ops.append((path, status, additions, deletions))
        path = None
        status = "modified"
        additions = 0
        deletions = 0

    for line in lines[1:-1]:
        if line.startswith("*** Add File: "):
            flush()
            path = _norm_path(line.removeprefix("*** Add File: "))
            status = "added"
            continue
        if line.startswith("*** Update File: "):
            flush()
            path = _norm_path(line.removeprefix("*** Update File: "))
            status = "modified"
            continue
        if line.startswith("*** Delete File: "):
            flush()
            path = _norm_path(line.removeprefix("*** Delete File: "))
            status = "removed"
            continue
        if line.startswith("*** Move to: "):
            # Treat move target as the surviving path.
            move_to = _norm_path(line.removeprefix("*** Move to: "))
            if path:
                path = move_to
            continue
        if status == "added" and line.startswith("+"):
            additions += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    flush()
    return ops


def _deleted_lines_from_result(result: str | None) -> int | None:
    if not result:
        return None
    first = result.split("\n", 1)[0]
    prefix = "@@ EvoFlux-diff-meta "
    if not first.startswith(prefix):
        return None
    try:
        import json

        meta = json.loads(first[len(prefix) :])
    except Exception:  # noqa: BLE001
        return None
    deleted = meta.get("deleted_lines") if isinstance(meta, dict) else None
    return deleted if isinstance(deleted, int) else None


def _merge_status(existing: ChangeStatus, incoming: ChangeStatus) -> ChangeStatus:
    """Merge sequential ops on the same path within a turn."""
    if incoming == "removed":
        return "removed"
    # Recreate after delete → added.
    if existing == "removed":
        return "added" if incoming in ("added", "modified", "changed") else incoming
    # First write stays added; later edits keep added.
    if existing == "added":
        return "added"
    if incoming == "added":
        # Overwrite of a previously modified/changed path → modified.
        return "modified"
    return incoming


def begin_turn(session_id: str) -> None:
    """Clear in-flight accumulator for a new turn (idempotent)."""
    _active[session_id] = {}


def _upsert(
    session_id: str,
    path: str,
    status: ChangeStatus,
    *,
    additions: int | None = None,
    deletions: int | None = None,
) -> None:
    bucket = _active.setdefault(session_id, {})
    existing = bucket.get(path)
    if existing is None:
        bucket[path] = ChangedFile(
            path=path,
            status=status,
            additions=additions,
            deletions=deletions,
        )
        return
    existing.status = _merge_status(existing.status, status)
    if additions is not None:
        existing.additions = (existing.additions or 0) + additions
    if deletions is not None:
        existing.deletions = (existing.deletions or 0) + deletions


def record_tool_change(
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    result: str | None = None,
    additions: int | None = None,
    deletions: int | None = None,
) -> None:
    """Record a file-mutating tool against the active turn for ``session_id``."""
    if tool_name not in FILE_MUTATING_TOOLS:
        return

    if tool_name == "patch":
        patch_text = args.get("patch_text")
        if isinstance(patch_text, str) and patch_text.strip():
            ops = _parse_patch_ops(patch_text)
            if ops:
                for path, status, add, rem in ops:
                    _upsert(
                        session_id,
                        path,
                        status,
                        additions=add if add else None,
                        deletions=rem if rem else None,
                    )
                return
        # Fallback: single path if caller provided one.
        path = _path_from_args(tool_name, args)
        if path:
            _upsert(
                session_id, path, "modified", additions=additions, deletions=deletions
            )
        return

    path = _path_from_args(tool_name, args)
    if not path:
        return

    if tool_name == "write":
        status: ChangeStatus = "added"
        if additions is None and deletions is None:
            additions, deletions = _stats_for_write(args)
    elif tool_name == "rm":
        status = "removed"
        if deletions is None:
            deletions = _deleted_lines_from_result(result)
        additions = 0 if deletions is not None else additions
    elif tool_name == "edit":
        status = "modified"
        if additions is None and deletions is None:
            additions, deletions = _stats_for_edit(args)
    else:
        status = "changed"

    _upsert(session_id, path, status, additions=additions, deletions=deletions)


def flush_turn(session_id: str) -> TurnChangesSnapshot | None:
    """Finalize the turn accumulator into a snapshot; return None if empty."""
    bucket = _active.pop(session_id, None) or {}
    if not bucket:
        # Still publish an empty latest snapshot so FE can clear stale chips.
        empty = TurnChangesSnapshot(session_id=session_id)
        _latest[session_id] = empty
        return None
    files = sorted(bucket.values(), key=lambda f: f.path.lower())
    additions = sum(f.additions or 0 for f in files)
    deletions = sum(f.deletions or 0 for f in files)
    snap = TurnChangesSnapshot(
        session_id=session_id,
        files=files,
        additions=additions,
        deletions=deletions,
    )
    _latest[session_id] = snap
    return snap


def get_latest(session_id: str) -> TurnChangesSnapshot | None:
    return _latest.get(session_id)


def clear_session(session_id: str) -> None:
    _active.pop(session_id, None)
    _latest.pop(session_id, None)


def enrich_plan_step(
    tool_name: str, args: dict[str, Any], summary: str
) -> dict[str, Any]:
    """Normalize a plan step dict for FE (path + optional diff_stat hints)."""
    path = _path_from_args(tool_name, args)
    out: dict[str, Any] = {
        "tool": tool_name,
        "args": args,
        "summary": summary,
    }
    if tool_name == "patch":
        patch_text = args.get("patch_text")
        if isinstance(patch_text, str):
            ops = _parse_patch_ops(patch_text)
            if ops:
                # Primary path for grouping; full list stays in args.
                out["path"] = ops[0][0]
                add = sum(o[2] for o in ops)
                rem = sum(o[3] for o in ops)
                if add or rem:
                    out["diff_stat"] = {"additions": add, "deletions": rem}
                return out
    if path:
        out["path"] = path

    add: int | None = None
    rem: int | None = None
    raw_add = args.get("additions") or args.get("added")
    raw_rem = args.get("deletions") or args.get("removed")
    if isinstance(raw_add, int) or isinstance(raw_rem, int):
        add = raw_add if isinstance(raw_add, int) else None
        rem = raw_rem if isinstance(raw_rem, int) else None
    elif tool_name == "edit":
        add, rem = _stats_for_edit(args)
    elif tool_name == "write":
        add, rem = _stats_for_write(args)
    if add is not None or rem is not None:
        out["diff_stat"] = {"additions": add, "deletions": rem}
    return out
