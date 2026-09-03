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
from app.agent.sandbox_config import DEFAULT_DENIED_PATTERNS


def _make(tmp_path: Path, patterns: list[str]) -> SandboxConfig:
    return SandboxConfig(
        workspace=str(tmp_path / "ws"),
        memory=str(tmp_path / "mem"),
        denied_roots=[],
        denied_patterns=patterns,
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


# ============================================================================
# BUG-004: default denylist widened beyond the exact ".env" family.
#
# The pre-fix default (["**/.env", "**/.env.*"]) let an agent trivially
# bypass the secret-file guard by renaming to an equivalent filename
# (e.g. "env.local", "secrets.json") — see
# report_bugs/bugs/BUG-004-sandbox-env-denylist-bypass.md. These cases are
# the exact examples verified as bypassing the old default in that report.
# ============================================================================


@pytest.mark.parametrize(
    "relative_path",
    [
        "env.local",
        "secrets.json",
        "credentials.yaml",
        ".aws/credentials",
        "id_rsa",
    ],
)
def test_default_patterns_block_previously_bypassable_secret_files(
    tmp_path: Path, relative_path: str
) -> None:
    """Filenames confirmed bypassing the old narrow default must now be denied."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    sandbox = _make(tmp_path, list(DEFAULT_DENIED_PATTERNS))
    with pytest.raises(PermissionError, match="denied sandbox root"):
        sandbox.validate_path(str(target))


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env",
        ".env.production",
    ],
)
def test_default_patterns_still_block_original_env_family(
    tmp_path: Path, relative_path: str
) -> None:
    """Widening the denylist must not regress the pre-existing .env coverage."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / relative_path
    target.touch()

    sandbox = _make(tmp_path, list(DEFAULT_DENIED_PATTERNS))
    with pytest.raises(PermissionError, match="denied sandbox root"):
        sandbox.validate_path(str(target))


def test_default_patterns_allow_unrelated_files(tmp_path: Path) -> None:
    """The widened default must not deny ordinary, unrelated files."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "main.py"
    target.touch()

    sandbox = _make(tmp_path, list(DEFAULT_DENIED_PATTERNS))
    assert sandbox.validate_path(str(target)) == target.resolve()
