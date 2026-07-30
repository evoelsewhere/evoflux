"""PostEditDiagnosticsHook — auto-lint Python files after mutations.

Closes the edit→verify feedback loop: around successful ``edit``/``write``/
``patch`` calls, run ``ruff check`` on changed Python files before and after the
mutation and append **newly introduced** diagnostics to the tool result. The
model sees errors it just caused in the same round instead of discovering
them later (or never) via a manual ``lsp_diagnostics`` call — while
pre-existing issues in the file stay out of the way, so the agent is not
lured into out-of-scope fixes.

Scope remains latency-bounded: single-file Ruff checks run concurrently and
TypeScript stays in the completion contract because ``tsc`` has no fast
single-file mode. Any failure (no Ruff, timeout, parse error) leaves the tool
  result untouched. This hook must never break tool execution.
"""

from __future__ import annotations

import asyncio
import json
import re
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

_LINT_TOOLS = frozenset({"edit", "write", "patch"})
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
        target_specs: list[tuple[Path, Path]] = []
        before_by_target: dict[Path, list[dict] | None] = {}
        try:
            if tool_call.function.name in _LINT_TOOLS:
                target_specs = self._target_specs(tool_call)
                before_results = await asyncio.gather(
                    *(self._run_ruff(before) for before, _after in target_specs)
                )
                before_by_target = {
                    after: diagnostics
                    for (_before, after), diagnostics in zip(
                        target_specs, before_results, strict=True
                    )
                }
        except Exception as exc:  # noqa: BLE001 — never break tool execution
            logger.debug("post_edit_diagnostics_pre_skipped error={}", exc)
            target_specs = []

        result = await handler(ctx, state, tool_call)

        try:
            if not target_specs or not isinstance(result, str):
                return result
            # tool_executor stringifies tool failures as "Error: ..." — a
            # failed edit wrote nothing, so there is nothing to lint.
            if result.startswith("Error"):
                return result
            after_results = await asyncio.gather(
                *(self._run_ruff(after) for _before, after in target_specs)
            )
            reports: list[str] = []
            for (_before, path), after in zip(target_specs, after_results, strict=True):
                before = before_by_target.get(path)
                # None means Ruff was unavailable or a scan failed; skip rather
                # than attributing pre-existing issues to this mutation.
                if after is None or before is None:
                    continue
                introduced = self._new_issues(before, after)
                if introduced:
                    reports.append(self._format(path, introduced))
            if reports:
                result += "\n\n[auto-diagnostics] " + "\n".join(reports)
        except Exception as exc:  # noqa: BLE001 — never break tool execution
            logger.debug("post_edit_diagnostics_skipped error={}", exc)
        return result

    @staticmethod
    def _target_specs(tool_call: "ToolCall") -> list[tuple[Path, Path]]:
        """Return ``(pre-edit path, post-edit path)`` Python targets."""
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
        try:
            for before_raw, after_raw in raw_specs:
                if not after_raw.endswith(_PY_SUFFIXES):
                    continue
                targets.append(
                    (
                        sandbox.validate_path(before_raw),
                        sandbox.validate_path(after_raw),
                    )
                )
        except Exception:  # noqa: BLE001 — sandbox rejection = nothing to lint
            return []
        return targets

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
        ruff_cmd = self._ruff_cmd
        if not isinstance(ruff_cmd, list):
            return None
        if not path.exists():
            return []  # new file about to be created — nothing pre-existing
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
