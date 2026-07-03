from __future__ import annotations

import pytest

from app.agent.errors import ToolExecutionError
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.tools.builtin.filesystem import patch_file


@pytest.fixture
def sandbox_workspace(tmp_path):
    config = SandboxConfig(workspace=str(tmp_path))
    token = set_sandbox(config)
    yield tmp_path
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_patch_add_update_delete(sandbox_workspace):
    (sandbox_workspace / "modify.txt").write_text("line1\nline2\n", encoding="utf-8")
    (sandbox_workspace / "delete.txt").write_text("obsolete\n", encoding="utf-8")

    result = await patch_file.arun(
        patch_text="""*** Begin Patch
*** Add File: nested/new.txt
+created
*** Update File: modify.txt
@@
-line2
+changed
*** Delete File: delete.txt
*** End Patch"""
    )

    assert "Patch applied successfully" in result
    assert '"path":"modify.txt"' in result
    assert '"old_start":2' in result
    assert (sandbox_workspace / "nested" / "new.txt").read_text(
        encoding="utf-8"
    ) == "created\n"
    assert (sandbox_workspace / "modify.txt").read_text(
        encoding="utf-8"
    ) == "line1\nchanged\n"
    assert not (sandbox_workspace / "delete.txt").exists()


@pytest.mark.asyncio
async def test_patch_reports_old_and_new_start_after_prior_line_delta(
    sandbox_workspace,
):
    (sandbox_workspace / "modify.txt").write_text(
        "line1\nline2\nline3\nline4\n",
        encoding="utf-8",
    )

    result = await patch_file.arun(
        patch_text="""*** Begin Patch
*** Update File: modify.txt
@@
-line1
+line1
+inserted
@@
-line4
+changed
*** End Patch"""
    )

    assert '{"old_start":1,"new_start":1}' in result
    assert '{"old_start":4,"new_start":5}' in result
    assert (sandbox_workspace / "modify.txt").read_text(encoding="utf-8") == (
        "line1\ninserted\nline2\nline3\nchanged\n"
    )


@pytest.mark.asyncio
async def test_patch_moves_file(sandbox_workspace):
    source = sandbox_workspace / "old" / "name.txt"
    source.parent.mkdir()
    source.write_text("old content\n", encoding="utf-8")

    await patch_file.arun(
        patch_text="""*** Begin Patch
*** Update File: old/name.txt
*** Move to: renamed/name.txt
@@
-old content
+new content
*** End Patch"""
    )

    assert not source.exists()
    assert (sandbox_workspace / "renamed" / "name.txt").read_text(
        encoding="utf-8"
    ) == "new content\n"


@pytest.mark.asyncio
async def test_patch_preflight_failure_has_no_side_effects(sandbox_workspace):
    patch_text = """*** Begin Patch
*** Add File: created.txt
+hello
*** Update File: missing.txt
@@
-old
+new
*** End Patch"""

    with pytest.raises(ToolExecutionError):
        await patch_file.arun(patch_text=patch_text)

    assert not (sandbox_workspace / "created.txt").exists()


@pytest.mark.asyncio
async def test_patch_rejects_ambiguous_update(sandbox_workspace):
    target = sandbox_workspace / "repeat.txt"
    target.write_text("same\nsame\n", encoding="utf-8")

    with pytest.raises(ToolExecutionError):
        await patch_file.arun(
            patch_text="""*** Begin Patch
*** Update File: repeat.txt
@@
-same
+changed
*** End Patch"""
        )

    assert target.read_text(encoding="utf-8") == "same\nsame\n"
