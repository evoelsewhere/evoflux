"""Tests for SandboxConfig.read_only_paths — the AIM base-source
write-deny mechanism (documents/research/aim-framework.md §3.3).

Read-only paths are NOT denied roots: agents can still read/search them
via ls/grep/glob/read and via shell. Only mutating fs tools (write/edit/
patch/rm) and shell redirects into a read-only path are rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig


def _make_sandbox(tmp_path: Path, *, read_only: list[Path]) -> SandboxConfig:
    return SandboxConfig(
        workspace=str(tmp_path / "ws"),
        denied_roots=[],
        denied_patterns=[],
        read_only_paths=[str(p) for p in read_only],
    )


def test_read_of_read_only_path_is_allowed(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    result = sandbox.validate_path(str(source / "file.cbl"))
    assert result == (source / "file.cbl").resolve()


def test_write_to_read_only_path_is_rejected(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    with pytest.raises(PermissionError, match="read-only"):
        sandbox.validate_path(str(source / "file.cbl"), is_write=True)


def test_write_outside_read_only_path_still_allowed(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    # Writing inside the session's own workspace_root is unaffected.
    result = sandbox.validate_path("output.txt", is_write=True)
    assert result == (tmp_path / "ws" / "output.txt").resolve()


def test_write_to_nested_file_under_read_only_path_is_rejected(tmp_path):
    source = tmp_path / "source-repo"
    nested = source / "sub" / "dir"
    nested.mkdir(parents=True)
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    with pytest.raises(PermissionError, match="read-only"):
        sandbox.validate_path(str(nested / "file.cbl"), is_write=True)


def test_no_read_only_paths_configured_allows_all_writes(tmp_path):
    other = tmp_path / "other-repo"
    other.mkdir()
    sandbox = SandboxConfig(workspace=str(tmp_path / "ws"), denied_roots=[], denied_patterns=[])

    result = sandbox.validate_path(str(other / "file.txt"), is_write=True)
    assert result == (other / "file.txt").resolve()


# ---------------------------------------------------------------------------
# check_command — shell redirect detection
# ---------------------------------------------------------------------------


def test_check_command_blocks_redirect_into_read_only_path(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    hit = sandbox.check_command(f"echo bad > {source}/file.cbl")
    assert hit is not None
    resolved, denied = hit
    assert resolved == (source / "file.cbl").resolve()


def test_check_command_blocks_append_redirect_into_read_only_path(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    hit = sandbox.check_command(f"echo bad >> {source}/file.cbl")
    assert hit is not None


def test_check_command_allows_read_only_reference_without_redirect(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    (source / "file.cbl").write_text("IDENTIFICATION DIVISION.")
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    hit = sandbox.check_command(f"cat {source}/file.cbl")
    assert hit is None


def test_check_command_ignores_redirect_outside_read_only_path(tmp_path):
    source = tmp_path / "source-repo"
    source.mkdir()
    sandbox = _make_sandbox(tmp_path, read_only=[source])

    hit = sandbox.check_command("echo ok > output.txt")
    assert hit is None
