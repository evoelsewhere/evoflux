"""Bounded, inspectable context assembly for explicit AI editor actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.agent.tools.builtin.filesystem._ignore import is_gitignored
from app.services.git_ops import run_git

_MAX_ACTIVE_CHARS = 96_000
_MAX_SELECTION_CHARS = 32_000
_MAX_MENTION_CHARS = 32_000
_MAX_MENTIONS = 8
_MAX_INSTRUCTION_CHARS = 32_000
_MAX_TERMINAL_CHARS = 16_000
_MAX_DIFF_CHARS = 64_000


class EditorContextError(ValueError):
    pass


@dataclass(slots=True)
class ContextProvenance:
    kind: str
    source: str
    path: str | None = None
    sha256: str | None = None
    truncated: bool = False


@dataclass(slots=True)
class EditorContextEnvelope:
    workspace: str
    active_file: str
    document_version: int | None
    content: str
    content_sha256: str
    selection: dict[str, Any] | None
    cursor_symbol: str | None
    diagnostics: list[dict[str, Any]]
    git_hunks: str
    related_symbols: list[dict[str, Any]]
    callers: list[dict[str, Any]]
    callees: list[dict[str, Any]]
    recent_agent_changes: dict[str, Any] | None
    relevant_terminal_failure: str | None
    project_instructions: list[dict[str, str]]
    attachments: list[dict[str, str]]
    provenance: list[ContextProvenance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = [asdict(item) for item in self.provenance]
        return payload

    def digest(self) -> str:
        """Hash the exact inspectable payload approved before a model call."""
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return _sha(encoded)


async def build_editor_context(
    workspace: Path,
    *,
    active_file: str,
    content: str,
    document_version: int | None,
    selection: dict[str, Any] | None,
    cursor_symbol: str | None,
    diagnostics: list[dict[str, Any]],
    mention_paths: list[str] | None = None,
    session_id: str | None = None,
    relevant_terminal_failure: str | None = None,
) -> EditorContextEnvelope:
    root = workspace.resolve()
    path = _resolve_file(root, active_file)
    relative = path.relative_to(root).as_posix()
    aiignore = _load_aiignore(root)
    if _is_aiignored(relative, aiignore):
        raise EditorContextError(f"'{relative}' is excluded by .aiignore.")

    active_content, active_truncated = _bounded(content, _MAX_ACTIVE_CHARS)
    selection_value = _normalize_selection(selection)
    if selection_value is not None:
        selected_text, truncated = _bounded(
            str(selection_value.get("text") or ""), _MAX_SELECTION_CHARS
        )
        selection_value["text"] = selected_text
        selection_value["truncated"] = truncated

    provenance = [
        ContextProvenance(
            kind="active_file",
            source="editor-buffer",
            path=relative,
            sha256=_sha(content),
            truncated=active_truncated,
        )
    ]
    git_hunks = await _git_hunks(root, relative)
    if git_hunks:
        provenance.append(
            ContextProvenance(
                kind="git_hunks",
                source="git-diff",
                path=relative,
                sha256=_sha(git_hunks),
                truncated=len(git_hunks) >= _MAX_DIFF_CHARS,
            )
        )

    attachments = _read_mentions(root, mention_paths or [], aiignore, provenance)
    instructions = _read_instruction_chain(root, path, provenance)
    graph = await _graph_context(root, cursor_symbol)
    if graph[0] or graph[1] or graph[2]:
        provenance.append(
            ContextProvenance(kind="related_symbols", source="code-context-index")
        )

    recent_changes = None
    if session_id:
        from app.services.turn_changes import get_latest

        snapshot = get_latest(session_id)
        if snapshot is not None:
            recent_changes = snapshot.to_dict()
            provenance.append(
                ContextProvenance(kind="recent_agent_changes", source="turn-changes")
            )

    terminal = None
    if relevant_terminal_failure:
        terminal, terminal_truncated = _bounded(
            relevant_terminal_failure, _MAX_TERMINAL_CHARS
        )
        provenance.append(
            ContextProvenance(
                kind="terminal_failure",
                source="terminal-selection",
                sha256=_sha(relevant_terminal_failure),
                truncated=terminal_truncated,
            )
        )

    return EditorContextEnvelope(
        workspace=str(root),
        active_file=relative,
        document_version=document_version,
        content=active_content,
        content_sha256=_sha(content),
        selection=selection_value,
        cursor_symbol=cursor_symbol,
        diagnostics=diagnostics[:200],
        git_hunks=git_hunks,
        related_symbols=graph[0],
        callers=graph[1],
        callees=graph[2],
        recent_agent_changes=recent_changes,
        relevant_terminal_failure=terminal,
        project_instructions=instructions,
        attachments=attachments,
        provenance=provenance,
    )


async def _graph_context(
    workspace: Path, symbol: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not symbol or any(char.isspace() for char in symbol.strip()):
        return [], [], []
    from app.services.code_index.models import RepositoryScope
    from app.services.code_index.service import query_code_context

    scope = (RepositoryScope(root=workspace, label=workspace.name),)

    async def query(action: Literal["neighborhood", "callers", "callees"]):
        try:
            return await query_code_context(
                scopes=scope,
                action=action,
                query=symbol.strip(),
                depth=1,
                limit=8,
                refresh=True,
            )
        except (OSError, RuntimeError, ValueError):
            return None

    neighborhood = await query("neighborhood")
    callers = await query("callers")
    callees = await query("callees")
    return (
        _serialize_graph(neighborhood),
        _serialize_graph(callers),
        _serialize_graph(callees),
    )


def _serialize_graph(result) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows: list[dict[str, Any]] = []
    for symbol in [*result.matches, *result.suggestions]:
        rows.append(
            {
                "kind": "symbol",
                "name": symbol.name,
                "qualified_name": symbol.qualified_name,
                "path": symbol.file_path,
                "line_start": symbol.line_start,
                "line_end": symbol.line_end,
                "signature": symbol.signature,
            }
        )
    for relation in result.relations:
        rows.append(
            {
                "kind": relation.kind,
                "source": relation.source.qualified_name,
                "target": relation.target.qualified_name,
                "path": relation.callsite_file,
                "line": relation.callsite_line,
            }
        )
    return rows[:24]


async def _git_hunks(workspace: Path, relative_path: str) -> str:
    result = await run_git(
        str(workspace),
        "diff",
        "--no-ext-diff",
        "--unified=3",
        "--",
        relative_path,
        timeout=5,
        max_output_bytes=_MAX_DIFF_CHARS,
    )
    value = result.stdout if result.ok else ""
    return value[:_MAX_DIFF_CHARS]


def _read_mentions(
    workspace: Path,
    raw_paths: list[str],
    aiignore: list[tuple[str, bool]],
    provenance: list[ContextProvenance],
) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_paths[:_MAX_MENTIONS]:
        try:
            target = _resolve_context_path(workspace, raw)
        except EditorContextError:
            continue
        relative = target.relative_to(workspace).as_posix()
        if relative in seen or _is_aiignored(
            relative, aiignore, is_dir=target.is_dir()
        ):
            continue
        seen.add(relative)
        if target.is_dir():
            listed: list[str] = []
            for child in sorted(target.rglob("*")):
                if not child.is_file():
                    continue
                child_relative = child.relative_to(workspace).as_posix()
                if _is_aiignored(child_relative, aiignore):
                    continue
                listed.append(child_relative)
                if len(listed) >= 200:
                    break
            content = "[Directory context — file listing only]\n" + "\n".join(listed)
            attachments.append({"path": relative + "/", "content": content})
            provenance.append(
                ContextProvenance(
                    kind="attachment",
                    source="explicit-folder-mention",
                    path=relative + "/",
                    sha256=_sha(content),
                    truncated=len(listed) >= 200,
                )
            )
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        bounded, truncated = _bounded(content, _MAX_MENTION_CHARS)
        attachments.append({"path": relative, "content": bounded})
        provenance.append(
            ContextProvenance(
                kind="attachment",
                source="explicit-mention",
                path=relative,
                sha256=_sha(content),
                truncated=truncated,
            )
        )
    return attachments


def _read_instruction_chain(
    workspace: Path,
    target: Path,
    provenance: list[ContextProvenance],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    directories = [workspace]
    current = target.parent
    lineage: list[Path] = []
    while current != workspace and current != current.parent:
        lineage.append(current)
        current = current.parent
    directories.extend(reversed(lineage))
    remaining = _MAX_INSTRUCTION_CHARS
    for directory in directories:
        instruction = directory / "AGENTS.md"
        if not instruction.is_file() or remaining <= 0:
            continue
        try:
            raw = instruction.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        content, truncated = _bounded(raw, remaining)
        remaining -= len(content)
        relative = instruction.relative_to(workspace).as_posix()
        result.append({"path": relative, "content": content})
        provenance.append(
            ContextProvenance(
                kind="project_instructions",
                source="AGENTS.md",
                path=relative,
                sha256=_sha(raw),
                truncated=truncated,
            )
        )
    return result


def _load_aiignore(workspace: Path) -> list[tuple[str, bool]]:
    path = workspace / ".aiignore"
    if not path.is_file():
        return []
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    rules: list[tuple[str, bool]] = []
    for row in rows:
        pattern = row.strip()
        if not pattern or pattern.startswith("#"):
            continue
        include = pattern.startswith("!")
        if include:
            pattern = pattern[1:].strip()
        if pattern:
            rules.append((pattern, include))
    return rules


def _is_aiignored(
    relative: str, rules: list[tuple[str, bool]], *, is_dir: bool = False
) -> bool:
    return is_gitignored(relative, is_dir=is_dir, rules=rules)


def _resolve_file(workspace: Path, raw_path: str) -> Path:
    target = _resolve_context_path(workspace, raw_path)
    if not target.is_file():
        raise EditorContextError(f"Editor context file does not exist: {raw_path}")
    return target


def _resolve_context_path(workspace: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() or (len(raw_path) >= 2 and raw_path[1] == ":"):
        raise EditorContextError("Editor context paths must be repository-relative.")
    target = (workspace / candidate).resolve(strict=False)
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise EditorContextError("Editor context path escapes the repository.") from exc
    if not target.exists() or not (target.is_file() or target.is_dir()):
        raise EditorContextError(f"Editor context path does not exist: {raw_path}")
    return target


def _normalize_selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not selection:
        return None
    return {
        "text": str(selection.get("text") or ""),
        "start_line": selection.get("start_line"),
        "start_column": selection.get("start_column"),
        "end_line": selection.get("end_line"),
        "end_column": selection.get("end_column"),
    }


def _bounded(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n[context truncated]", True


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
