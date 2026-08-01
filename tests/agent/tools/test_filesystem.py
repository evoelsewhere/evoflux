"""Tests for app/tools/builtin/filesystem — all filesystem tools."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.artifacts import session_artifact_dir
from app.agent.errors import ToolExecutionError
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.state import AgentState
from app.core.config import settings
from app.agent.tools.builtin.filesystem import (
    glob_files,
    grep_files,
    list_directory,
    read_file,
    write_file,
)
from app.agent.tools.builtin.filesystem.grep import _grep_files
from app.agent.tools.builtin.filesystem.rm import _remove_path
from app.agent.tools.builtin.filesystem.glob import _glob_files as _search_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path):
    sb = SandboxConfig(workspace=str(tmp_path))
    token = set_sandbox(sb)
    yield sb, tmp_path
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


@pytest.fixture
def sandbox_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = SandboxConfig(workspace=str(workspace))
    set_sandbox(config)
    yield workspace


@pytest.fixture
def workspace(tmp_path):
    """Workspace with sample files for grep/glob tests."""
    sb = SandboxConfig(workspace=str(tmp_path))
    set_sandbox(sb)
    (tmp_path / "hello.py").write_text("def hello():\n    print('hello')\n")
    (tmp_path / "world.py").write_text("def world():\n    return 42\n")
    (tmp_path / "readme.md").write_text("# Project\nThis is a readme.\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.py").write_text("import os\nprint(os.getcwd())\n")
    return tmp_path


# ---------------------------------------------------------------------------
# write_file / read_file — integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_and_read_file(sandbox_workspace):
    result = await write_file.arun(path="test.txt", content="hello world")
    assert "Written" in result
    assert f"Resolved path: {sandbox_workspace / 'test.txt'}" in result
    assert (sandbox_workspace / "test.txt").read_text() == "hello world"

    read_content = await read_file.arun(path="test.txt")
    assert read_content == "00001| hello world"


@pytest.mark.asyncio
async def test_write_file_no_overwrite(sandbox_workspace):
    (sandbox_workspace / "existing.txt").write_text("old")
    with pytest.raises(ToolExecutionError):
        await write_file.arun(path="existing.txt", content="new", overwrite=False)


@pytest.mark.asyncio
async def test_read_file_not_found(sandbox_workspace):
    with pytest.raises(ToolExecutionError):
        await read_file.arun(path="missing.txt")


@pytest.mark.asyncio
async def test_read_file_is_directory(sandbox_workspace):
    (sandbox_workspace / "subdir").mkdir()
    with pytest.raises(ToolExecutionError):
        await read_file.arun(path="subdir")


@pytest.mark.asyncio
async def test_read_file_truncation(sandbox_workspace, monkeypatch):
    read_file_module = importlib.import_module(
        "app.agent.tools.builtin.filesystem.read"
    )
    monkeypatch.setattr(read_file_module, "_MAX_READ_BYTES", 5)
    (sandbox_workspace / "big.txt").write_text("ABCDEFGHIJ")
    result = await read_file.arun(path="big.txt")
    assert result == "00001| ABCDE"


@pytest.mark.asyncio
async def test_read_file_caps_large_text_for_context(sandbox_workspace, monkeypatch):
    read_file_module = importlib.import_module(
        "app.agent.tools.builtin.filesystem.read"
    )
    monkeypatch.setattr(read_file_module, "_MAX_CONTEXT_CHARS", 10)
    (sandbox_workspace / "material-icons.json").write_text("A" * 50)

    result = await read_file.arun(path="material-icons.json")

    assert result.startswith("00001| AAA")
    assert "read output truncated for LLM context" in result
    assert "Use offset and limit" in result
    assert len(result) < 300


@pytest.mark.asyncio
async def test_read_file_latin1_fallback(sandbox_workspace):
    (sandbox_workspace / "latin.bin").write_bytes(b"\xff\xfe")
    result = await read_file.arun(path="latin.bin")
    assert result == "00001| ÿþ"


@pytest.mark.asyncio
async def test_read_file_pagination(sandbox_workspace):
    lines = "\n".join(f"line{i}" for i in range(1, 11))
    (sandbox_workspace / "paged.txt").write_text(lines)
    result = await read_file.arun(path="paged.txt", offset=2, limit=3)
    assert result.startswith("[2-4/10]")
    assert "line2" in result
    assert "line4" in result
    assert "line5" not in result


@pytest.mark.asyncio
async def test_read_file_default_numbers_lines_without_header(sandbox_workspace):
    """Default reads add 'NNNNN| ' line numbers but no pagination header."""
    content = "line1\nline2\nline3"
    (sandbox_workspace / "plain.txt").write_text(content)

    result = await read_file.arun(path="plain.txt")

    assert result == "00001| line1\n00002| line2\n00003| line3"


@pytest.mark.asyncio
async def test_read_file_offset_matches_grep_line_numbers(sandbox_workspace):
    """Offsets are 1-indexed so callers can pass line numbers from grep."""
    (sandbox_workspace / "paged.txt").write_text("alpha\nbeta\ngamma\ndelta\n")

    result = await read_file.arun(path="paged.txt", offset=3, limit=1)

    assert result == "[3-3/4]\n00003| gamma\n"


# ---------------------------------------------------------------------------
# list_directory — integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory(sandbox_workspace):
    (sandbox_workspace / "dir1").mkdir()
    (sandbox_workspace / "file1.txt").write_text("f1")
    (sandbox_workspace / "file2.txt").write_text("f2")

    result = await list_directory.arun(path=".")
    assert "[d] dir1/" in result
    assert "[f] file1.txt  (2 bytes)" in result
    assert "[f] file2.txt  (2 bytes)" in result


@pytest.mark.asyncio
async def test_list_directory_not_found(sandbox_workspace):
    with pytest.raises(ToolExecutionError):
        await list_directory.arun(path="nonexistent_dir")


@pytest.mark.asyncio
async def test_list_directory_on_file(sandbox_workspace):
    (sandbox_workspace / "file.txt").write_text("x")
    with pytest.raises(ToolExecutionError):
        await list_directory.arun(path="file.txt")


# ---------------------------------------------------------------------------
# glob (filename-only mode, replaces search_files) — integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_name_match(sandbox_workspace):
    (sandbox_workspace / "subdir").mkdir()
    (sandbox_workspace / "test1.py").write_text("p1")
    (sandbox_workspace / "subdir" / "test2.py").write_text("p2")
    (sandbox_workspace / "other.txt").write_text("t1")

    result = await glob_files.arun(pattern="*.py", match="name")
    assert "test1.py" in result
    assert "test2.py" in result
    assert "other.txt" not in result


@pytest.mark.asyncio
async def test_glob_name_match_no_match(sandbox_workspace):
    (sandbox_workspace / "other.txt").write_text("hello")
    result = await glob_files.arun(pattern="*.py", match="name")
    assert "No files matching" in result


# ---------------------------------------------------------------------------
# Sandbox path validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_allows_active_session_artifact_path_only(sandbox_workspace):
    from app.agent.sandbox import _sandbox_ctx

    session_id = "session-read-artifact"
    token = set_sandbox(
        SandboxConfig(workspace=str(sandbox_workspace), session_id=session_id)
    )
    try:
        artifact = (
            session_artifact_dir(session_id) / ".tool_results" / "lead" / "call.txt"
        )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("artifact content", encoding="utf-8")
        other = (
            session_artifact_dir("other-session")
            / ".tool_results"
            / "lead"
            / "call.txt"
        )
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("other content", encoding="utf-8")

        state = AgentState(messages=[], metadata={"session_id": session_id})

        assert (
            await read_file.arun(
                path=str(artifact.resolve()), _injected={"_state": state}
            )
            == "00001| artifact content"
        )
        with pytest.raises(ToolExecutionError):
            await read_file.arun(path=str(other.resolve()), _injected={"_state": state})
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_read_rejects_data_dir_outside_active_session(sandbox_workspace):
    from app.agent.sandbox import _sandbox_ctx

    token = set_sandbox(SandboxConfig(workspace=str(sandbox_workspace), session_id="s"))
    try:
        data_file = session_artifact_dir("s").parent.parent / "evoflux.db"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text("db bytes", encoding="utf-8")

        with pytest.raises(ToolExecutionError):
            await read_file.arun(path=str(data_file.resolve()))
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_read_allows_log_paths(sandbox_workspace):
    from app.agent.sandbox import _sandbox_ctx

    token = set_sandbox(SandboxConfig(workspace=str(sandbox_workspace), session_id="s"))
    try:
        # Test-owned filename under the logs allowlist — avoids the live
        # ``app.log`` sink the running logger appends to.
        log_path = Path(settings.EVOFLUX_STATE_DIR) / "logs" / "app" / "read-test.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("log content", encoding="utf-8")

        assert (
            await read_file.arun(path=str(log_path.resolve())) == "00001| log content"
        )
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_sandbox_validation(sandbox_workspace, tmp_path):
    """Denylist model: paths under denied roots are rejected.

    Under the current sandbox (commit ``b9ed918``), arbitrary out-of-workspace
    paths are *allowed* unless they fall under ``EVOFLUX_DATA_DIR`` /
    ``STATE_DIR`` / ``CACHE_DIR`` or match a deny-pattern.  This test
    exercises the denied-root branch by pointing the sandbox at a temp
    directory and trying to write into it.
    """
    denied = tmp_path / "denied_root"
    denied.mkdir()
    set_sandbox(
        SandboxConfig(
            workspace=str(sandbox_workspace),
            denied_roots=[denied],
            denied_patterns=[],
        )
    )

    # Reading a non-existent relative path still fails (FileNotFoundError
    # → ToolExecutionError) — verifies the tool surface still raises.
    with pytest.raises(ToolExecutionError):
        await read_file.arun(path="missing.txt")

    # Writing into a denied root is rejected by the sandbox itself.
    with pytest.raises(ToolExecutionError):
        await write_file.arun(path=str(denied / "evil.txt"), content="evil")


# ---------------------------------------------------------------------------
# _search_files: internal unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_name_not_a_directory_raises(sandbox):
    sb, tmp_path = sandbox
    f = tmp_path / "not_a_dir.txt"
    f.write_text("content")
    with pytest.raises(NotADirectoryError, match="Not a directory"):
        await _search_files("*.txt", directory="not_a_dir.txt", match="name")


@pytest.mark.asyncio
async def test_glob_name_non_recursive_via_path_match(sandbox):
    sb, tmp_path = sandbox
    (tmp_path / "root.py").write_text("# root")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.py").write_text("# nested")

    # match='path' with no ** only matches in the root dir (non-recursive)
    result = await _search_files("*.py", directory=".", match="path")
    assert "root.py" in result
    assert "nested.py" not in result


@pytest.mark.asyncio
async def test_glob_name_no_match(sandbox):
    sb, tmp_path = sandbox
    (tmp_path / "only.txt").write_text("text")
    result = await _search_files("*.py", directory=".", match="name")
    assert "No files matching" in result


@pytest.mark.asyncio
async def test_glob_name_limits_to_200_results(sandbox):
    sb, tmp_path = sandbox
    for i in range(205):
        (tmp_path / f"file_{i:03d}.py").write_text("# content")
    result = await _search_files("*.py", directory=".", match="name")
    assert len(result.strip().splitlines()) == 200


# ---------------------------------------------------------------------------
# grep_files — integration
# ---------------------------------------------------------------------------


class TestGrepFiles:
    async def test_grep_finds_matches(self, workspace):
        result = await grep_files.arun(pattern="def ", directory=".")
        assert "hello.py" in result
        assert "world.py" in result

    async def test_grep_with_include_filter(self, workspace):
        result = await grep_files.arun(pattern="print", directory=".", include="*.py")
        assert "hello.py" in result
        assert "nested.py" in result
        assert "readme.md" not in result

    async def test_grep_no_matches(self, workspace):
        result = await grep_files.arun(pattern="ZZZZNOTFOUND", directory=".")
        assert "No matches" in result

    async def test_grep_invalid_regex(self, workspace):
        with pytest.raises(ToolExecutionError):
            await grep_files.arun(pattern="[invalid", directory=".")

    async def test_grep_not_a_directory(self, workspace):
        with pytest.raises(ToolExecutionError):
            await grep_files.arun(pattern="test", directory="hello.py")

    async def test_grep_max_results(self, workspace):
        result = await grep_files.arun(pattern=".", directory=".", max_results=2)
        assert len(result.strip().split("\n")) == 2

    async def test_grep_skips_hidden_dirs(self, workspace):
        hidden = workspace / ".hidden"
        hidden.mkdir()
        (hidden / "secret.py").write_text("SECRET_KEY = 'abc'\n")
        result = await grep_files.arun(pattern="SECRET_KEY", directory=".")
        assert "No matches" in result

    async def test_grep_respects_gitignore_and_common_generated_dirs(self, workspace):
        (workspace / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (workspace / "ignored.py").write_text("SECRET_KEY = 'ignored'\n")

        node_modules = workspace / "node_modules"
        node_modules.mkdir()
        (node_modules / "dep.py").write_text("SECRET_KEY = 'dep'\n")

        pycache = workspace / "__pycache__"
        pycache.mkdir()
        (pycache / "cache.py").write_text("SECRET_KEY = 'cache'\n")

        ruff_cache = workspace / ".ruff_cache"
        ruff_cache.mkdir()
        (ruff_cache / "cache.py").write_text("SECRET_KEY = 'ruff'\n")

        pytest_cache = workspace / ".pytest_cache"
        pytest_cache.mkdir()
        (pytest_cache / "cache.py").write_text("SECRET_KEY = 'pytest'\n")

        result = await grep_files.arun(pattern="SECRET_KEY", directory=".")
        assert "No matches" in result
        assert "ruff" not in result
        assert ".pytest_cache" not in result


# ---------------------------------------------------------------------------
# _grep_files: internal unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_files_skips_binary_files(sandbox):
    sb, tmp_path = sandbox
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe invalid utf-8")
    (tmp_path / "good.py").write_text("hello world")
    result = await _grep_files("hello", directory=".")
    assert "good.py" in result
    assert "binary.py" not in result


@pytest.mark.asyncio
async def test_grep_files_skips_oserror_on_read(sandbox):
    sb, tmp_path = sandbox
    (tmp_path / "good.py").write_text("target_pattern")
    (tmp_path / "bad.py").write_text("should be skipped")

    real_read_text = Path.read_text

    def patched_read_text(self, encoding="utf-8"):
        if self.name != "good.py":
            raise OSError("permission denied")
        return real_read_text(self, encoding=encoding)

    with patch.object(Path, "read_text", patched_read_text):
        result = await _grep_files("target_pattern", directory=".")
    assert "good.py" in result


# ---------------------------------------------------------------------------
# glob_files — integration
# ---------------------------------------------------------------------------


class TestGlobFiles:
    async def test_glob_finds_py_files(self, workspace):
        result = await glob_files.arun(pattern="**/*.py", directory=".")
        assert "hello.py" in result
        assert "world.py" in result
        assert "nested.py" in result

    async def test_glob_finds_md_files(self, workspace):
        result = await glob_files.arun(pattern="*.md", directory=".")
        assert "readme.md" in result
        assert ".py" not in result

    async def test_glob_no_matches(self, workspace):
        result = await glob_files.arun(pattern="*.xyz", directory=".")
        assert "No files matching" in result

    async def test_glob_not_a_directory(self, workspace):
        with pytest.raises(ToolExecutionError):
            await glob_files.arun(pattern="*", directory="hello.py")

    async def test_glob_skips_hidden_dirs(self, workspace):
        hidden = workspace / ".hidden"
        hidden.mkdir()
        (hidden / "secret.txt").write_text("secret")
        result = await glob_files.arun(pattern="**/*.txt", directory=".")
        assert "secret.txt" not in result

    async def test_glob_max_results(self, workspace):
        for i in range(10):
            (workspace / f"file_{i}.txt").write_text(f"content {i}")
        result = await glob_files.arun(pattern="*.txt", directory=".", max_results=3)
        assert len(result.strip().split("\n")) == 3

    async def test_glob_respects_gitignore_and_common_generated_dirs(self, workspace):
        (workspace / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (workspace / "ignored.txt").write_text("ignored")

        node_modules = workspace / "node_modules"
        node_modules.mkdir()
        (node_modules / "dep.txt").write_text("dep")

        pycache = workspace / "__pycache__"
        pycache.mkdir()
        (pycache / "cache.txt").write_text("cache")

        ruff_cache = workspace / ".ruff_cache"
        ruff_cache.mkdir()
        (ruff_cache / "cache.txt").write_text("ruff")

        pytest_cache = workspace / ".pytest_cache"
        pytest_cache.mkdir()
        (pytest_cache / "cache.txt").write_text("pytest")

        result = await glob_files.arun(pattern="**/*.txt", directory=".")
        assert "ignored.txt" not in result
        assert "dep.txt" not in result
        assert "cache.txt" not in result
        assert "ruff" not in result
        assert ".pytest_cache" not in result


# ---------------------------------------------------------------------------
# _remove_path: internal unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_path_file(sandbox):
    _, tmp_path = sandbox
    f = tmp_path / "del.txt"
    f.write_text("bye")
    result = await _remove_path("del.txt")
    assert '@@ EvoFlux-diff-meta {"path":"del.txt","deleted_lines":1}' in result
    assert "Removed file" in result
    assert f"Resolved path: {f}" in result
    assert not f.exists()


@pytest.mark.asyncio
async def test_remove_path_binary_file_still_deletes(sandbox):
    _, tmp_path = sandbox
    f = tmp_path / "binary.bin"
    f.write_bytes(b"\xff\xfe\n\x00")
    result = await _remove_path("binary.bin")
    assert '"deleted_lines":2' in result
    assert not f.exists()


@pytest.mark.asyncio
async def test_remove_path_symlink_to_workspace_target_allowed(sandbox):
    """Symlinks pointing to workspace-internal targets are now allowed.

    `validate_path` resolves through the symlink, so removing it operates on
    the resolved target.  Both the link and the target are gone afterwards
    (the symlink becomes dangling, and `unlink()` is called on the target).
    """
    _, tmp_path = sandbox
    target = tmp_path / "target.txt"
    target.write_text("data")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        # Windows without Developer Mode / SeCreateSymbolicLinkPrivilege.
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation requires elevated privilege on Windows")
        raise
    result = await _remove_path("link.txt")
    assert "Removed file" in result
    # The resolved target was removed; the dangling link still exists as an
    # entry but its target is gone.
    assert not target.exists()


@pytest.mark.asyncio
async def test_remove_path_not_found_raises(sandbox):
    with pytest.raises(FileNotFoundError, match="Path not found"):
        await _remove_path("missing.txt")


@pytest.mark.asyncio
async def test_remove_path_empty_dir(sandbox):
    _, tmp_path = sandbox
    d = tmp_path / "emptydir"
    d.mkdir()
    result = await _remove_path("emptydir")
    assert "Removed directory" in result
    assert not d.exists()


@pytest.mark.asyncio
async def test_remove_path_nonempty_dir_no_recursive_raises(sandbox):
    _, tmp_path = sandbox
    d = tmp_path / "filled"
    d.mkdir()
    (d / "file.txt").write_text("x")
    with pytest.raises(OSError, match="recursive=true"):
        await _remove_path("filled", recursive=False)


@pytest.mark.asyncio
async def test_remove_path_recursive(sandbox):
    _, tmp_path = sandbox
    d = tmp_path / "tree"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("b")
    result = await _remove_path("tree", recursive=True)
    assert "Removed directory" in result
    assert not d.exists()


# ---------------------------------------------------------------------------
# grep_files — case_insensitive / context flags (python fallback path)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_rg(monkeypatch):
    """Force the pure-Python grep fallback regardless of installed tools."""
    import shutil as _shutil

    real_which = _shutil.which
    monkeypatch.setattr(
        _shutil,
        "which",
        lambda name, *a, **kw: None if name == "rg" else real_which(name, *a, **kw),
    )


class TestGrepFlags:
    async def test_case_insensitive(self, workspace, no_rg):
        result = await grep_files.arun(
            pattern="DEF HELLO", directory=".", case_insensitive=True
        )
        assert "hello.py:1:" in result

    async def test_case_sensitive_by_default(self, workspace, no_rg):
        result = await grep_files.arun(pattern="DEF HELLO", directory=".")
        assert "No matches" in result

    async def test_context_lines(self, workspace, no_rg):
        result = await grep_files.arun(
            pattern="print", directory=".", include="hello.py", context=1
        )
        # Match on line 2 pulls in line 1 as '-'-separated context.
        assert "hello.py-1- def hello():" in result
        assert "hello.py:2:" in result

    async def test_context_blocks_separated(self, workspace, no_rg):
        (workspace / "multi.txt").write_text(
            "match one\nfiller\nfiller\nfiller\nfiller\nmatch two\n"
        )
        result = await grep_files.arun(
            pattern="match", directory=".", include="multi.txt", context=1
        )
        assert "--" in result
        assert "multi.txt:1: match one" in result
        assert "multi.txt:6: match two" in result

    async def test_context_capped_max_results(self, workspace, no_rg):
        (workspace / "caps.txt").write_text("hit\nhit\nhit\n")
        result = await grep_files.arun(
            pattern="hit", directory=".", include="caps.txt", context=1, max_results=2
        )
        match_lines = [
            line for line in result.split("\n") if ":" in line and ": hit" in line
        ]
        assert len(match_lines) == 2


# ---------------------------------------------------------------------------
# grep_files — ripgrep backend (parsing exercised via a fake rg binary)
# ---------------------------------------------------------------------------


def _install_fake_rg(tmp_path, monkeypatch, body: str):
    import shutil as _shutil
    import sys as _sys

    # On Windows a shebang script is not directly executable (WinError 193).
    # Drop a ``.cmd`` launcher that forwards to the same Python interpreter.
    if _sys.platform == "win32":
        script = tmp_path / "fake_rg.py"
        script.write_text(body, encoding="utf-8")
        launcher = tmp_path / "fake-rg.cmd"
        launcher.write_text(
            f'@echo off\r\n"{_sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        target = launcher
    else:
        script = tmp_path / "fake-rg"
        script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        script.chmod(0o755)
        target = script

    real_which = _shutil.which
    monkeypatch.setattr(
        _shutil,
        "which",
        lambda name, *a, **kw: (
            str(target) if name == "rg" else real_which(name, *a, **kw)
        ),
    )
    return target


class TestGrepRipgrep:
    async def test_rg_output_parsed(self, workspace, tmp_path, monkeypatch):
        _install_fake_rg(
            tmp_path,
            monkeypatch,
            "import sys\n"
            "sys.stdout.write('hello.py\\x1f1\\x1fdef hello():\\n')\n"
            "sys.stdout.write('--\\n')\n"
            "sys.stdout.write('sub/nested.py\\x1e2\\x1eprint(os.getcwd())\\n')\n",
        )
        result = await grep_files.arun(pattern="anything", directory=".")
        assert "hello.py:1: def hello():" in result
        assert "--" in result
        assert "sub/nested.py-2- print(os.getcwd())" in result

    async def test_rg_max_results_stops_early(self, workspace, tmp_path, monkeypatch):
        _install_fake_rg(
            tmp_path,
            monkeypatch,
            "import sys\n"
            "for i in range(1, 6):\n"
            "    sys.stdout.write(f'hello.py\\x1f{i}\\x1fline {i}\\n')\n",
        )
        result = await grep_files.arun(pattern="anything", directory=".", max_results=2)
        assert result.count("hello.py:") == 2

    async def test_rg_error_falls_back_to_python(
        self, workspace, tmp_path, monkeypatch
    ):
        _install_fake_rg(tmp_path, monkeypatch, "import sys\nsys.exit(2)\n")
        result = await grep_files.arun(pattern="def hello", directory=".")
        # Fallback scan still finds the real file content.
        assert "hello.py:1:" in result

    @pytest.mark.skipif(
        importlib.import_module("shutil").which("rg") is None,
        reason="ripgrep not installed",
    )
    async def test_real_rg_matches_legacy_format(self, workspace):
        result = await grep_files.arun(pattern="def ", directory=".")
        assert "hello.py:1: def hello():" in result
        assert "world.py:1: def world():" in result


# ---------------------------------------------------------------------------
# glob — mtime ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_orders_newest_first(sandbox):
    import os as _os
    import time as _time

    _, tmp_path = sandbox
    old = tmp_path / "old.py"
    new = tmp_path / "new.py"
    old.write_text("old")
    new.write_text("new")
    now = _time.time()
    _os.utime(old, (now - 1000, now - 1000))
    _os.utime(new, (now, now))

    result = await _search_files(pattern="*.py", match="name")
    lines = result.split("\n")
    assert lines.index("new.py") < lines.index("old.py")

    result_path = await _search_files(pattern="*.py")
    lines_path = result_path.split("\n")
    assert lines_path.index("new.py") < lines_path.index("old.py")
