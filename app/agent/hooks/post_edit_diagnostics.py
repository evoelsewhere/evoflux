"""Automatic, version-safe diagnostics after repository mutations.

The harness owns the edit-to-diagnose loop. Successful ``edit``/``write``/
``patch`` calls are inspected automatically, so an agent does not need to
spend another tool call asking whether it introduced a syntax or type error.
Only the diagnostic delta is reported. A clean receipt explicitly says that
LSP evidence is not a substitute for behavioral tests.

LSP is preferred for every mapped language. Python falls back to Ruff when a
language server is unavailable. Failures must never fail the mutation itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.lsp_manager import (
    LanguageServerUnavailable,
    get_language_server,
    language_server_spec,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext

_MUTATION_TOOLS = frozenset({"edit", "write", "patch"})
_PY_SUFFIXES = (".py", ".pyi", ".pyw")
_DIAGNOSTIC_TIMEOUT_S = 6.0
_RUFF_TIMEOUT_S = 10.0
_MAX_ISSUES_SHOWN = 10


@dataclass(slots=True)
class _Scan:
    source: str
    issues: list[dict[str, Any]]
    content_hash: str


def _ruff_command() -> list[str] | None:
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("python"):
        return ["python", "-m", "ruff"]
    return None


class PostEditDiagnosticsHook(BaseAgentHook):
    """Append one aggregated diagnostic observation to a mutation result."""

    def __init__(self) -> None:
        self._ruff_cmd: list[str] | None | bool = False

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler,
    ) -> str:
        target_specs: list[tuple[Path, Path]] = []
        before_by_target: dict[Path, _Scan | None] = {}
        try:
            if tool_call.function.name in _MUTATION_TOOLS:
                target_specs = self._target_specs(tool_call)
                before_results = await asyncio.gather(
                    *(
                        self._scan(before, require_current=False)
                        for before, _ in target_specs
                    )
                )
                before_by_target = {
                    after: scan
                    for (_before, after), scan in zip(
                        target_specs, before_results, strict=True
                    )
                }
        except Exception as exc:  # noqa: BLE001 - diagnostics never break edits
            logger.debug("post_edit_diagnostics_pre_skipped error={}", exc)
            target_specs = []

        result = await handler(ctx, state, tool_call)

        try:
            if (
                not target_specs
                or not isinstance(result, str)
                or result.startswith("Error")
            ):
                return result
            after_results = await asyncio.gather(
                *(self._scan(after, require_current=True) for _, after in target_specs)
            )
            reports: list[str] = []
            checked = 0
            resolved_count = 0
            unavailable: list[str] = []
            for (_before, path), after in zip(target_specs, after_results, strict=True):
                before = before_by_target.get(path)
                if after is None:
                    if language_server_spec(path) is not None:
                        unavailable.append(path.name)
                    continue
                if not self._hash_is_current(path, after.content_hash):
                    logger.debug("post_edit_diagnostics_stale path={}", path)
                    continue
                checked += 1
                baseline = (
                    before.issues
                    if before is not None and before.source == after.source
                    else []
                )
                introduced = self._new_issues(baseline, after.issues)
                resolved_count += len(self._new_issues(after.issues, baseline))
                if introduced:
                    reports.append(self._format(path, after.source, introduced))

            if checked or unavailable:
                lines = [
                    "[auto-diagnostics] Post-edit semantic check "
                    f"({checked} checked, {len(unavailable)} unavailable)."
                ]
                lines.extend(reports)
                if not reports and checked:
                    lines.append("No new diagnostics were introduced.")
                if resolved_count:
                    lines.append(f"Resolved diagnostics: {resolved_count}.")
                if unavailable:
                    lines.append(
                        "No current-version diagnostics for: "
                        + ", ".join(sorted(unavailable))
                        + "."
                    )
                lines.append(
                    "LSP/static diagnostics are not a substitute for behavioral tests."
                )
                result += "\n\n" + "\n".join(lines)
        except Exception as exc:  # noqa: BLE001 - diagnostics never break edits
            logger.debug("post_edit_diagnostics_skipped error={}", exc)
        return result

    @staticmethod
    def _target_specs(tool_call: "ToolCall") -> list[tuple[Path, Path]]:
        """Return repository-local ``(pre-edit path, post-edit path)`` pairs."""
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError):
            return []
        from app.agent.sandbox import get_sandbox

        raw_specs: list[tuple[str, str]] = []
        if tool_call.function.name in {"edit", "write"}:
            raw = args.get("path")
            if isinstance(raw, str):
                raw_specs.append((raw, raw))
        elif tool_call.function.name == "patch":
            patch_text = args.get("patch_text")
            if not isinstance(patch_text, str):
                return []
            current: str | None = None
            for line in patch_text.splitlines():
                match = re.match(r"\*\*\* (Add|Update) File: (.+)", line)
                if match:
                    current = match.group(2).strip()
                    raw_specs.append((current, current))
                    continue
                move = re.match(r"\*\*\* Move to: (.+)", line)
                if move and current and raw_specs:
                    raw_specs[-1] = (current, move.group(1).strip())

        sandbox = get_sandbox()
        targets: list[tuple[Path, Path]] = []
        seen: set[Path] = set()
        try:
            for before_raw, after_raw in raw_specs:
                after = sandbox.validate_path(after_raw)
                if not _supports_diagnostics(after) or after in seen:
                    continue
                seen.add(after)
                targets.append((sandbox.validate_path(before_raw), after))
        except Exception:  # noqa: BLE001 - sandbox rejection means no scan
            return []
        return targets

    async def _scan(self, path: Path, *, require_current: bool) -> _Scan | None:
        if not path.exists() or not path.is_file():
            return None
        content_hash = _content_hash(path)
        spec = language_server_spec(path)
        if spec is not None:
            try:
                from app.agent.sandbox import get_sandbox

                client = await asyncio.wait_for(
                    get_language_server(get_sandbox().workspace_root, path),
                    timeout=_DIAGNOSTIC_TIMEOUT_S,
                )
                issues = await asyncio.wait_for(
                    client.diagnostics(
                        path,
                        require_current_version=require_current,
                    ),
                    timeout=_DIAGNOSTIC_TIMEOUT_S,
                )
                return _Scan("lsp", list(issues), content_hash)
            except (
                LanguageServerUnavailable,
                OSError,
                RuntimeError,
                TimeoutError,
            ) as exc:
                logger.debug("post_edit_lsp_unavailable path={} error={}", path, exc)

        if path.suffix.casefold() in _PY_SUFFIXES:
            issues = await self._run_ruff(path)
            if issues is not None:
                return _Scan("ruff", issues, content_hash)
        return None

    @staticmethod
    def _new_issues(before: list[dict], after: list[dict]) -> list[dict]:
        """Return the multiset delta while ignoring line shifts."""

        def _key(issue: dict) -> tuple[str, str, str]:
            return (
                str(issue.get("code")),
                str(issue.get("message")),
                str(issue.get("severity")),
            )

        seen = Counter(_key(issue) for issue in before)
        fresh: list[dict] = []
        for issue in after:
            key = _key(issue)
            if seen[key] > 0:
                seen[key] -= 1
            else:
                fresh.append(issue)
        return fresh

    async def _run_ruff(self, path: Path) -> list[dict[str, Any]] | None:
        if self._ruff_cmd is False:
            self._ruff_cmd = _ruff_command()
        ruff_cmd = self._ruff_cmd
        if not isinstance(ruff_cmd, list):
            return None
        cmd = [
            *ruff_cmd,
            "check",
            str(path),
            "--output-format",
            "json",
            "--quiet",
        ]

        def _sync() -> str | None:
            try:
                completed = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_RUFF_TIMEOUT_S,
                    check=False,
                )
                return completed.stdout
            except (OSError, subprocess.TimeoutExpired):
                return None

        stdout = await asyncio.to_thread(_sync)
        if stdout is None:
            return None
        if not stdout.strip():
            return []
        try:
            issues = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        return issues if isinstance(issues, list) else None

    @staticmethod
    def _format(path: Path, source: str, issues: list[dict]) -> str:
        shown = issues[:_MAX_ISSUES_SHOWN]
        header = f"{path.name}: introduced {len(issues)} {source} issue(s)"
        if len(issues) > _MAX_ISSUES_SHOWN:
            header += f" (showing first {_MAX_ISSUES_SHOWN})"
        lines = [header + ":"]
        for issue in shown:
            location = issue.get("location") or {}
            start = (issue.get("range") or {}).get("start") or {}
            row = location.get("row", int(start.get("line", -1)) + 1)
            column = location.get("column", int(start.get("character", -1)) + 1)
            lines.append(
                f"  {path.name}:{row}:{column}  "
                f"{issue.get('code', '?')}  {issue.get('message', '')}"
            )
        lines.append("  Fix these before moving on, or say why they are expected.")
        return "\n".join(lines)

    @staticmethod
    def _hash_is_current(path: Path, expected: str) -> bool:
        try:
            return _content_hash(path) == expected
        except OSError:
            return False


def _supports_diagnostics(path: Path) -> bool:
    return (
        language_server_spec(path) is not None or path.suffix.casefold() in _PY_SUFFIXES
    )


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
