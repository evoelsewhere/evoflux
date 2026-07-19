"""Tests for PostEditDiagnosticsHook — post-edit ruff feedback loop.

Requires ruff (a dev dependency of this repo). Tests run real single-file
ruff checks against files in a tmp sandbox workspace.
"""

from __future__ import annotations

import json
import shutil

import pytest

from app.agent.hooks.post_edit_diagnostics import PostEditDiagnosticsHook
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import FunctionCall, ToolCall

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None and shutil.which("python") is None,
    reason="ruff not available",
)


@pytest.fixture
def sandbox(tmp_path):
    sb = SandboxConfig(workspace=str(tmp_path))
    token = set_sandbox(sb)
    yield sb, tmp_path
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


def _tool_call(tool: str, path: str) -> ToolCall:
    return ToolCall(
        id="tc-1",
        function=FunctionCall(name=tool, arguments=json.dumps({"path": path})),
    )


def _handler_writing(target, content: str, result: str = "Edit applied successfully"):
    async def handler(ctx, state, tool_call):
        target.write_text(content, encoding="utf-8")
        return result

    return handler


@pytest.mark.asyncio
async def test_reports_issue_introduced_by_edit(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("edit", "mod.py"),
        _handler_writing(target, "x = 1\nprint(undefined_name)\n"),
    )

    assert "[auto-diagnostics]" in result
    assert "F821" in result  # undefined name
    assert "introduced 1 ruff issue(s)" in result


@pytest.mark.asyncio
async def test_pre_existing_issues_not_reported(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "mod.py"
    # File already has an unused import before the edit.
    target.write_text("import os\nx = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("edit", "mod.py"),
        _handler_writing(target, "import os\nx = 2\n"),
    )

    assert "[auto-diagnostics]" not in result


@pytest.mark.asyncio
async def test_clean_edit_appends_nothing(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("edit", "mod.py"),
        _handler_writing(target, "x = 2\n"),
    )

    assert result == "Edit applied successfully"


@pytest.mark.asyncio
async def test_new_file_write_reports_its_issues(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "new_mod.py"
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("write", "new_mod.py"),
        _handler_writing(target, "import os\n"),  # unused import in a new file
    )

    assert "[auto-diagnostics]" in result
    assert "F401" in result


@pytest.mark.asyncio
async def test_non_python_files_ignored(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "notes.md"
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("edit", "notes.md"),
        _handler_writing(target, "# heading\n"),
    )

    assert result == "Edit applied successfully"


@pytest.mark.asyncio
async def test_other_tools_untouched(sandbox):
    hook = PostEditDiagnosticsHook()

    async def handler(ctx, state, tool_call):
        return "grep result"

    result = await hook.wrap_tool_call(
        None, None, _tool_call("grep", "mod.py"), handler
    )

    assert result == "grep result"


@pytest.mark.asyncio
async def test_failed_edit_not_linted(sandbox):
    _, tmp_path = sandbox
    (tmp_path / "mod.py").write_text("import os\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()

    async def handler(ctx, state, tool_call):
        return "Error: Could not find oldString in the file."

    result = await hook.wrap_tool_call(
        None, None, _tool_call("edit", "mod.py"), handler
    )

    assert result == "Error: Could not find oldString in the file."
