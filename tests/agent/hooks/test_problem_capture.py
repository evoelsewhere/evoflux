from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent.hooks.problem_capture import ProblemCaptureHook
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import FunctionCall, ToolCall
from app.services.problems_service import clear_problems, list_problems


@pytest.fixture
def sandbox(tmp_path):
    token = set_sandbox(SandboxConfig(workspace=str(tmp_path), session_id="session-1"))
    clear_problems()
    yield tmp_path
    clear_problems()
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


def _call(command: str) -> ToolCall:
    return ToolCall(
        id="tool-1",
        function=FunctionCall(name="shell", arguments=json.dumps({"command": command})),
    )


@pytest.mark.asyncio
async def test_failed_test_output_is_published(sandbox):
    (sandbox / "tests").mkdir()
    (sandbox / "tests/test_app.py").write_text("def test_app(): ...\n")
    hook = ProblemCaptureHook()
    state = SimpleNamespace(metadata={"session_id": "session-1"})

    async def handler(ctx, state, tool_call):
        return (
            "[Failed — exit code 1]\n\ntests/test_app.py:12: AssertionError: expected 2"
        )

    result = await hook.wrap_tool_call(None, state, _call("pytest -q"), handler)

    assert result.startswith("[Failed")
    rows = list_problems(sandbox)
    assert len(rows) == 1
    assert rows[0].source == "test"
    assert rows[0].path == "tests/test_app.py"
    assert rows[0].line == 12


@pytest.mark.asyncio
async def test_successful_repeat_clears_prior_command_scope(sandbox):
    (sandbox / "src.ts").write_text("const value = 1\n")
    hook = ProblemCaptureHook()
    state = SimpleNamespace(metadata={})
    results = iter(
        [
            "[Failed — exit code 2]\n\nsrc.ts(1,7): error TS2322: bad type",
            "[Succeeded]\n\n(No output)",
        ]
    )

    async def handler(ctx, state, tool_call):
        return next(results)

    call = _call("tsc --noEmit")
    await hook.wrap_tool_call(None, state, call, handler)
    assert len(list_problems(sandbox)) == 1
    await hook.wrap_tool_call(None, state, call, handler)
    assert list_problems(sandbox) == []


@pytest.mark.asyncio
async def test_unrelated_shell_command_is_ignored(sandbox):
    hook = ProblemCaptureHook()
    state = SimpleNamespace(metadata={})

    async def handler(ctx, state, tool_call):
        return "[Failed — exit code 1]\n\napp.py:1: error: nope"

    await hook.wrap_tool_call(None, state, _call("git status"), handler)
    assert list_problems(sandbox) == []
