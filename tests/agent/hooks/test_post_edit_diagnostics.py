"""Tests for the repository post-edit semantic feedback loop.

Requires ruff (a dev dependency of this repo). Tests run real single-file
ruff checks against files in a tmp sandbox workspace.
"""

from __future__ import annotations

import json
import shutil
from unittest.mock import AsyncMock, patch

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


def _patch_tool_call(patch_text: str) -> ToolCall:
    return ToolCall(
        id="tc-patch",
        function=FunctionCall(
            name="patch",
            arguments=json.dumps({"patch_text": patch_text}),
        ),
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

    assert "[auto-diagnostics]" in result
    assert "F401" not in result
    assert "No new diagnostics were introduced" in result


@pytest.mark.asyncio
async def test_clean_edit_appends_bounded_non_test_receipt(sandbox):
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

    assert "No new diagnostics were introduced" in result
    assert "not a substitute for behavioral tests" in result


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
async def test_multi_file_patch_reports_new_python_issues(sandbox):
    _, tmp_path = sandbox
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("x = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()
    call = _patch_tool_call(
        """*** Begin Patch
*** Update File: first.py
@@
-x = 1
+print(missing_name)
*** Add File: second.py
+import os
*** End Patch"""
    )

    async def handler(ctx, state, tool_call):
        first.write_text("print(missing_name)\n", encoding="utf-8")
        second.write_text("import os\n", encoding="utf-8")
        return "Patch applied successfully"

    result = await hook.wrap_tool_call(None, None, call, handler)

    assert "first.py" in result
    assert "F821" in result
    assert "second.py" in result
    assert "F401" in result
    assert result.count("[auto-diagnostics]") == 1


@pytest.mark.asyncio
async def test_mapped_language_reports_unavailable_server(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "notes.md"
    hook = PostEditDiagnosticsHook()

    result = await hook.wrap_tool_call(
        None,
        None,
        _tool_call("edit", "notes.md"),
        _handler_writing(target, "# heading\n"),
    )

    assert "[auto-diagnostics]" in result
    assert "notes.md" in result
    assert "1 unavailable" in result


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


@pytest.mark.asyncio
async def test_typescript_edit_receives_current_version_lsp_delta(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "mod.ts"
    target.write_text("const value = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()
    lsp_client = AsyncMock()
    lsp_client.diagnostics.side_effect = [
        [],
        [
            {
                "severity": 1,
                "code": "TS2322",
                "message": "Type 'string' is not assignable to type 'number'.",
                "range": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 11},
                },
            }
        ],
    ]

    with patch(
        "app.agent.hooks.post_edit_diagnostics.get_language_server",
        new_callable=AsyncMock,
        return_value=lsp_client,
    ):
        result = await hook.wrap_tool_call(
            None,
            None,
            _tool_call("edit", "mod.ts"),
            _handler_writing(target, 'const value: number = "bad"\n'),
        )

    assert "introduced 1 lsp issue(s)" in result
    assert "TS2322" in result
    assert lsp_client.diagnostics.await_args_list[0].kwargs == {
        "require_current_version": False
    }
    assert lsp_client.diagnostics.await_args_list[1].kwargs == {
        "require_current_version": True
    }


@pytest.mark.asyncio
async def test_stale_lsp_result_is_never_injected(sandbox):
    _, tmp_path = sandbox
    target = tmp_path / "mod.ts"
    target.write_text("const value = 1\n", encoding="utf-8")
    hook = PostEditDiagnosticsHook()
    lsp_client = AsyncMock()
    calls = 0

    async def diagnostics(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        target.write_text("const value = 3\n", encoding="utf-8")
        return [
            {
                "severity": 1,
                "code": "STALE",
                "message": "stale diagnostic",
                "range": {"start": {"line": 0, "character": 0}},
            }
        ]

    lsp_client.diagnostics.side_effect = diagnostics
    with patch(
        "app.agent.hooks.post_edit_diagnostics.get_language_server",
        new_callable=AsyncMock,
        return_value=lsp_client,
    ):
        result = await hook.wrap_tool_call(
            None,
            None,
            _tool_call("edit", "mod.ts"),
            _handler_writing(target, "const value = 2\n"),
        )

    assert "STALE" not in result
    assert "stale diagnostic" not in result
