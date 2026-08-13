"""Tests for SandboxConfig.read_only_paths — write-deny for readable roots.

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


def test_no_read_only_paths_configured_rejects_external_writes(tmp_path):
    other = tmp_path / "other-repo"
    other.mkdir()
    sandbox = SandboxConfig(
        workspace=str(tmp_path / "ws"),
        denied_roots=[],
        denied_patterns=[],
    )

    with pytest.raises(PermissionError, match="outside the allowed sandbox roots"):
        sandbox.validate_path(str(other / "file.txt"), is_write=True)


def test_session_uploads_are_automatically_mounted_read_only(tmp_path, monkeypatch):
    uploads = tmp_path / "app-storage" / "session-1" / "uploads"
    uploads.mkdir(parents=True)
    attachment = uploads / "stored.bin"
    attachment.write_bytes(b"data")
    monkeypatch.setattr(
        "app.core.paths.session_uploads_dir",
        lambda _session_id: uploads,
    )

    sandbox = SandboxConfig(
        workspace=str(tmp_path / "coding-repo"),
        session_id="session-1",
        denied_roots=[],
        denied_patterns=[],
    )

    assert sandbox.validate_path(str(attachment)) == attachment.resolve()
    with pytest.raises(PermissionError, match="read-only"):
        sandbox.validate_path(str(attachment), is_write=True)


def test_write_claim_restricts_member_to_declared_subtree(tmp_path):
    sandbox = SandboxConfig(
        workspace=str(tmp_path / "ws"),
        denied_roots=[],
        denied_patterns=[],
        write_allowed_paths=["app/agent"],
    )

    assert (
        sandbox.validate_path("app/agent/core.py", is_write=True)
        == (tmp_path / "ws" / "app" / "agent" / "core.py").resolve()
    )
    with pytest.raises(PermissionError, match="active write claims"):
        sandbox.validate_path("web/src/app.tsx", is_write=True)


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
