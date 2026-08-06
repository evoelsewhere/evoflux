"""Tests for user-defined glob deny-patterns in :class:`SandboxConfig`.

Patterns are matched with :func:`fnmatch.fnmatchcase` against the
resolved absolute path string, so ``**/.env`` blocks ``.env`` files
anywhere, including granted roots. Paths outside granted roots are denied
independently of pattern matching.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig


def _make(tmp_path: Path, patterns: list[str]) -> SandboxConfig:
    return SandboxConfig(
        workspace=str(tmp_path / "ws"),
        memory=str(tmp_path / "mem"),
        denied_roots=[],
        denied_patterns=patterns,
        native_process_isolation="required",
    )


def test_pattern_blocks_matching_path(tmp_path: Path) -> None:
    target = tmp_path / "secrets" / "key.txt"
    target.parent.mkdir(parents=True)
    target.touch()

    sandbox = _make(tmp_path, ["**/secrets/**"])
    with pytest.raises(PermissionError, match="denied sandbox root"):
        sandbox.validate_path(str(target))


def test_pattern_does_not_block_non_matching_path(tmp_path: Path) -> None:
    target = tmp_path / "public" / "file.txt"
    target.parent.mkdir(parents=True)
    target.touch()

    sandbox = _make(tmp_path, ["**/secrets/**"])
    with pytest.raises(PermissionError, match="outside the allowed sandbox roots"):
        sandbox.validate_path(str(target))


def test_dotfile_glob_blocks_env_anywhere(tmp_path: Path) -> None:
    """The seed pattern ``**/.env`` must block ``.env`` files anywhere."""
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.touch()

    sandbox = _make(tmp_path, ["**/.env"])
    with pytest.raises(PermissionError):
        sandbox.validate_path(str(env_file))


def test_pattern_still_blocks_workspace_paths(tmp_path: Path) -> None:
    """Sensitive patterns remain enforced inside otherwise granted roots."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    inside = workspace / ".env"
    inside.touch()

    sandbox = _make(tmp_path, ["**/.env"])
    with pytest.raises(PermissionError, match="denied sandbox root"):
        sandbox.validate_path(str(inside))


def test_empty_patterns_means_no_extra_denials(tmp_path: Path) -> None:
    target = tmp_path / "ws" / "anything.txt"
    target.parent.mkdir()
    target.touch()
    sandbox = _make(tmp_path, [])
    assert sandbox.validate_path(str(target)) == target.resolve()
