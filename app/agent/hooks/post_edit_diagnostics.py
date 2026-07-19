"""PostEditDiagnosticsHook — auto-lint a file right after the agent edits it.

Closes the edit→verify feedback loop: around a successful ``edit``/``write``
on a Python file, run ``ruff check`` on just that file before and after the
mutation and append **newly introduced** diagnostics to the tool result. The
model sees errors it just caused in the same round instead of discovering
them later (or never) via a manual ``lsp_diagnostics`` call — while
pre-existing issues in the file stay out of the way, so the agent is not
lured into out-of-scope fixes.

Scope is deliberately narrow:

- Python only — single-file ruff is ~tens of milliseconds. TypeScript is
  excluded because ``tsc`` has no fast single-file mode (whole-project
  typecheck per edit would add seconds of latency).
- ``edit`` and ``write`` only — ``patch`` can touch many files; its envelope
  parsing is not worth duplicating here.
- Best-effort — any failure (no ruff, timeout, parse error) leaves the tool
  result untouched. This hook must never break tool execution.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext

_LINT_TOOLS = frozenset({"edit", "write"})
_PY_SUFFIXES = (".py", ".pyi")
_RUFF_TIMEOUT_S = 15.0
_MAX_ISSUES_SHOWN = 10


def _ruff_command() -> list[str] | None:
    """Resolve a ruff invocation, mirroring lsp.py's module-vs-binary logic."""
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("python"):
        return ["python", "-m", "ruff"]
    return None


class PostEditDiagnosticsHook(BaseAgentHook):
    """Append newly-introduced ruff diagnostics to edit/write tool results."""

    def __init__(self) -> None:
        # Resolved lazily on first use; None = probed and unavailable.
        self._ruff_cmd: list[str] | None | bool = False  # False = not probed yet

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler,
    ) -> str:
        path: Path | None = None
        before: list[dict] | None = None
        try:
            if tool_call.function.name in _LINT_TOOLS:
                path = self._target_path(tool_call)
                if path is not None and str(path).endswith(_PY_SUFFIXES):
                    before = await self._run_ruff(path)
                else:
                    path = None
        except Exception as exc:  # noqa: BLE001 — never break tool execution
            logger.debug("post_edit_diagnostics_pre_skipped error={}", exc)
            path = None

        result = await handler(ctx, state, tool_call)

        try:
            if path is None or not isinstance(result, str):
                return result
            # tool_executor stringifies tool failures as "Error: ..." — a
            # failed edit wrote nothing, so there is nothing to lint.
            if result.startswith("Error"):
                return result
            after = await self._run_ruff(path)
            # before is None = ruff unavailable or the pre-scan failed; skip
            # rather than misattribute pre-existing issues to this edit.
            if after is None or before is None:
                return result
            introduced = self._new_issues(before, after)
            if introduced:
                result += f"\n\n[auto-diagnostics] {self._format(path, introduced)}"
        except Exception as exc:  # noqa: BLE001 — never break tool execution
            logger.debug("post_edit_diagnostics_skipped error={}", exc)
        return result

    @staticmethod
    def _target_path(tool_call: "ToolCall") -> Path | None:
        """Extract the edited file's path from the tool-call arguments."""
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError):
            return None
        raw = args.get("path")
        if not raw or not isinstance(raw, str):
            return None
        from app.agent.sandbox import get_sandbox

        try:
            return get_sandbox().validate_path(raw)
        except Exception:  # noqa: BLE001 — sandbox rejection = nothing to lint
            return None

    @staticmethod
    def _new_issues(before: list[dict], after: list[dict]) -> list[dict]:
        """Issues present after the edit but not before.

        Rows shift when lines are inserted, so identity is (code, message) —
        an issue that merely moved is not "new".
        """

        def _key(issue: dict) -> tuple[str, str]:
            return (str(issue.get("code")), str(issue.get("message")))

        seen = Counter(_key(i) for i in before)
        fresh: list[dict] = []
        for issue in after:
            key = _key(issue)
            if seen[key] > 0:
                seen[key] -= 1
            else:
                fresh.append(issue)
        return fresh

    async def _run_ruff(self, path: Path) -> list[dict] | None:
        """Run ``ruff check`` on one file; return parsed issues or None on failure."""
        if self._ruff_cmd is False:
            self._ruff_cmd = _ruff_command()
        if self._ruff_cmd is None:
            return None
        if not path.exists():
            return []  # new file about to be created — nothing pre-existing
        cmd = [*self._ruff_cmd, "check", str(path), "--output-format", "json", "--quiet"]

        def _sync() -> str | None:
            try:
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_RUFF_TIMEOUT_S,
                    check=False,
                )
                return r.stdout
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
    def _format(path: Path, issues: list[dict]) -> str:
        shown = issues[:_MAX_ISSUES_SHOWN]
        header = f"this change introduced {len(issues)} ruff issue(s)"
        if len(issues) > _MAX_ISSUES_SHOWN:
            header += f" (showing first {_MAX_ISSUES_SHOWN})"
        lines = [header + ":"]
        for issue in shown:
            loc = issue.get("location", {})
            lines.append(
                f"  {path.name}:{loc.get('row', '?')}:{loc.get('column', '?')}  "
                f"{issue.get('code', '?')}  {issue.get('message', '')}"
            )
        lines.append("  Fix these before moving on, or say why they are expected.")
        return "\n".join(lines)
