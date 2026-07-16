"""End-to-end proof that the mutating filesystem tools (write/edit/patch/rm)
reject a path under SandboxConfig.read_only_paths, while reads keep
working — the AIM-2 acceptance criterion "every write tool is blocked on
base source" (documents/research/aim-framework.md §4.1).
"""

from __future__ import annotations

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.filesystem import edit_file, patch_file, remove_path, write_file
from app.agent.tools.builtin.filesystem.read import read_file


@pytest.fixture
def read_only_source(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    (source / "existing.cbl").write_text("IDENTIFICATION DIVISION.\n")
    config = SandboxConfig(
        workspace=str(tmp_path / "target-repo"),
        read_only_paths=[str(source)],
    )
    token = set_sandbox(config)
    yield source
    _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_write_to_source_is_blocked(read_only_source):
    with pytest.raises(PermissionError, match="read-only"):
        await write_file(path=str(read_only_source / "new.cbl"), content="x")


@pytest.mark.asyncio
async def test_edit_existing_source_file_is_blocked(read_only_source):
    with pytest.raises(PermissionError, match="read-only"):
        await edit_file(
            path=str(read_only_source / "existing.cbl"),
            old_string="IDENTIFICATION DIVISION.",
            new_string="CHANGED.",
        )


@pytest.mark.asyncio
async def test_rm_source_file_is_blocked(read_only_source):
    with pytest.raises(PermissionError, match="read-only"):
        await remove_path(path=str(read_only_source / "existing.cbl"))


@pytest.mark.asyncio
async def test_patch_source_file_is_blocked(read_only_source):
    with pytest.raises(PermissionError, match="read-only"):
        await patch_file(
            patch_text=f"""*** Begin Patch
*** Update File: {read_only_source / "existing.cbl"}
@@
-IDENTIFICATION DIVISION.
+CHANGED.
*** End Patch"""
        )


@pytest.mark.asyncio
async def test_reading_source_file_still_works(read_only_source):
    result = await read_file(path=str(read_only_source / "existing.cbl"))
    assert "IDENTIFICATION DIVISION." in result


@pytest.mark.asyncio
async def test_write_to_own_workspace_still_works(read_only_source, tmp_path):
    result = await write_file(path="output.txt", content="hello")
    assert (tmp_path / "target-repo" / "output.txt").read_text() == "hello"
    assert "Written" in result
