"""Capture structured build/test failures from the existing shell tool."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext

_TEST_COMMAND = re.compile(
    r"(?:^|\s)(?:pytest|vitest|jest|go test|cargo test|mvn test|gradle\w* test|"
    r"npm test|pnpm test|bun test)(?:\s|$)",
    re.IGNORECASE,
)
_BUILD_COMMAND = re.compile(
    r"(?:^|\s)(?:build|compile|tsc|mypy|ruff|eslint|cargo check|go vet|"
    r"mvn verify|gradle\w* check)(?:\s|$)",
    re.IGNORECASE,
)
_GENERIC = re.compile(
    r"^(?P<path>[^\n:()]+\.[A-Za-z0-9]+):(?P<line>\d+)"
    r"(?::(?P<column>\d+))?:\s*(?:(?P<severity>error|warning|fail(?:ed)?)"
    r"(?:\s+(?P<code>[A-Za-z]+\d+))?[:\s-]*)?(?P<message>.+)$",
    re.IGNORECASE,
)
_PAREN = re.compile(
    r"^(?P<path>.+\.[A-Za-z0-9]+)\((?P<line>\d+),(?P<column>\d+)\):\s*"
    r"(?P<severity>error|warning)\s*(?P<code>[A-Za-z]+\d+)?:?\s*(?P<message>.+)$",
    re.IGNORECASE,
)


class ProblemCaptureHook(BaseAgentHook):
    """Publish file-addressable problems from recognized build/test commands."""

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler,
    ) -> str:
        result = await handler(ctx, state, tool_call)
        if tool_call.function.name != "shell" or not isinstance(result, str):
            return result
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
            command = str(arguments.get("command") or "")
            if _command_source(command) is None:
                return result
            from app.agent.sandbox import get_sandbox

            publish_command_output(
                get_sandbox().workspace_root,
                command=command,
                result=result,
                session_id=str(state.metadata.get("session_id") or "") or None,
            )
        except Exception as exc:  # noqa: BLE001 - capture never breaks shell
            logger.debug("problem_capture_skipped error={}", exc)
        return result


def _command_source(command: str) -> Literal["test", "build"] | None:
    if _TEST_COMMAND.search(command):
        return "test"
    if _BUILD_COMMAND.search(command):
        return "build"
    return None


def publish_command_output(
    workspace: Path,
    *,
    command: str,
    result: str,
    session_id: str | None,
) -> int:
    """Publish addressable problems for a recognized command; return count."""
    from app.services.problems_service import ProblemInput, publish_problems

    source = _command_source(command)
    if source is None:
        return 0
    root = workspace.resolve()
    inputs: list[ProblemInput] = []
    for raw_line in result.splitlines():
        line = raw_line.strip()
        match = _PAREN.match(line) or _GENERIC.match(line)
        if match is None:
            continue
        raw_path = match.group("path").strip().strip('"')
        path = Path(raw_path)
        if not path.is_absolute():
            path = (root / path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        severity_text = (match.groupdict().get("severity") or "error").casefold()
        inputs.append(
            ProblemInput(
                message=match.group("message").strip(),
                severity="warning" if severity_text == "warning" else "error",
                path=str(path),
                line=int(match.group("line")),
                column=int(match.groupdict().get("column") or 1),
                code=match.groupdict().get("code"),
                provenance={
                    "producer": "verification-command",
                    "command_sha256": hashlib.sha256(command.encode()).hexdigest()[:16],
                    "failed": result.startswith("[Failed"),
                },
            )
        )
        if len(inputs) >= 200:
            break
    command_hash = hashlib.sha256(command.encode()).hexdigest()[:16]
    publish_problems(
        root,
        source=source,
        scope=f"shell:{source}:{command_hash}",
        problems=inputs,
        session_id=session_id,
    )
    return len(inputs)
