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
    from app.services.problems_service import ProblemSeverity

_TEST_COMMAND = re.compile(
    r"(?:^|\s)(?:pytest|vitest|jest|go test|cargo test|mvn test|gradle\w* test|"
    r"npm test|pnpm test|bun test)(?:\s|$)",
    re.IGNORECASE,
)
# ``build`` and ``compile`` used to sit here as bare words, which made
# ``rm -rf build``, ``cd build && ls`` and ``echo build`` all count as build
# commands whose output was then mined for problems. A build is named by the
# tool that runs it, so name the tools.
_BUILD_COMMAND = re.compile(
    r"(?:^|\s)(?:"
    r"tsc|mypy|ruff|eslint|make"
    r"|go\s+(?:build|vet)"
    r"|cargo\s+(?:build|check|clippy)"
    r"|(?:npm|pnpm|yarn|bun)\s+run\s+[\w:-]*build[\w:-]*"
    r"|(?:ninja|bazel|dotnet|msbuild)\s+\S*build"
    r"|gradle\w*\s+(?:build|check|assemble)"
    r"|mvn\s+(?:verify|compile|package)"
    r")(?:\s|$)",
    re.IGNORECASE,
)
_GENERIC = re.compile(
    r"^(?P<path>[^\n:()]+\.[A-Za-z0-9]+):(?P<line>\d+)"
    r"(?::(?P<column>\d+))?:\s*(?:(?P<severity>error|warning|fail(?:ed)?)"
    r"(?:\s+(?P<code>[A-Za-z]+\d+))?[:\s-]*)?(?P<message>.+)$",
    re.IGNORECASE,
)
# Python names its warning categories ``…Warning``, and a warnings summary
# line states the category where a compiler would state a severity.
_WARNING_CLASS = re.compile(r"^\w*Warning\b", re.IGNORECASE)
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


def _severity_of(match: "re.Match[str]") -> ProblemSeverity:
    """Read the severity a line states, and believe it when it states none.

    Defaulting an unlabelled line to ``error`` turned every mypy ``note:``
    into a red error in the panel — and mypy emits a note for nearly every
    error it reports, so a single type failure arrived as a pile of them.
    A line that does not call itself a failure is reported as information.
    """
    stated = (match.groupdict().get("severity") or "").casefold()
    if stated == "warning":
        return "warning"
    if stated:
        return "error"
    message = match.group("message").strip()
    if message.casefold().startswith("note:"):
        return "info"
    if _WARNING_CLASS.match(message):
        return "warning"
    # An unlabelled line from a failing test run is still a failure; only
    # the two shapes above are known to be something milder.
    return "error"


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
        inputs.append(
            ProblemInput(
                message=match.group("message").strip(),
                severity=_severity_of(match),
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
        # The latest run is the current truth for this kind of check. Without
        # this, changing the command at all — one file instead of the suite,
        # an added flag — stranded the previous run's findings in a scope
        # nothing would ever publish to again.
        supersedes_prefix=f"shell:{source}:",
    )
    return len(inputs)
