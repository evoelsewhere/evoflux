"""Security policy tests for native shell-process containment."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Literal

import pytest

from app.agent.process_sandbox import (
    _glob_to_regex,
    _linked_worktree_git_roots,
    _macos_profile,
    _writable_roots,
    native_process_sandbox_backend,
    sandboxed_process_argv,
)
from app.agent.sandbox import SandboxConfig


def _sandbox(
    tmp_path: Path,
    *,
    isolation: Literal["required", "best_effort"],
) -> SandboxConfig:
    return SandboxConfig(
        workspace=str(tmp_path / "workspace"),
        denied_roots=[],
        denied_patterns=[],
        native_process_isolation=isolation,
    )


def test_backend_detection_reports_seatbelt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.agent.process_sandbox.sys.platform", "darwin")
    monkeypatch.setattr(
        "app.agent.process_sandbox.shutil.which",
        lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None,
    )

    assert native_process_sandbox_backend() == "seatbelt"


def test_required_isolation_fails_closed_without_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, isolation="required")
    monkeypatch.setattr("app.agent.process_sandbox.sys.platform", "win32")
    monkeypatch.setattr("app.agent.process_sandbox.shutil.which", lambda _name: None)

    with pytest.raises(PermissionError, match="Native process isolation is required"):
        sandboxed_process_argv(
            "cmd.exe",
            ["/c", "echo ok"],
            sandbox=sandbox,
            cwd=sandbox.workspace_root,
        )


def test_best_effort_keeps_application_sandbox_without_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, isolation="best_effort")
    monkeypatch.setattr("app.agent.process_sandbox.sys.platform", "win32")
    monkeypatch.setattr("app.agent.process_sandbox.shutil.which", lambda _name: None)

    assert sandboxed_process_argv(
        "cmd.exe",
        ["/c", "echo ok"],
        sandbox=sandbox,
        cwd=sandbox.workspace_root,
    ) == ("cmd.exe", ["/c", "echo ok"])


def test_best_effort_skips_native_process_sandbox_even_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, isolation="best_effort")
    monkeypatch.setattr("app.agent.process_sandbox.sys.platform", "darwin")
    monkeypatch.setattr(
        "app.agent.process_sandbox.shutil.which",
        lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None,
    )

    assert sandboxed_process_argv(
        "/bin/sh",
        ["-c", "uv run ruff check ."],
        sandbox=sandbox,
        cwd=sandbox.workspace_root,
    ) == ("/bin/sh", ["-c", "uv run ruff check ."])


def test_macos_profile_allows_the_null_device_for_shell_and_git(
    tmp_path: Path,
) -> None:
    """Commands may redirect output to /dev/null inside the Seatbelt sandbox."""
    profile = _macos_profile(_sandbox(tmp_path, isolation="best_effort"))

    assert '(allow file-write* (literal "/dev/null"))' in profile


def test_macos_profile_excludes_denied_roots_and_globs_from_reads(
    tmp_path: Path,
) -> None:
    denied = tmp_path / "private"
    sandbox = SandboxConfig(
        workspace=str(tmp_path / "workspace"),
        denied_roots=[denied],
        denied_patterns=["**/.env", "**/.env.*"],
        native_process_isolation="required",
    )

    profile = _macos_profile(sandbox)

    assert f'(require-not (subpath "{denied.resolve()}"))' in profile
    assert _glob_to_regex("**/.env") in profile
    assert "(allow file-read*)" not in profile


def test_linked_worktree_common_git_dir_is_writable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    workspace = tmp_path / "task-worktree"
    common = source / ".git"
    git_dir = common / "worktrees" / workspace.name
    git_dir.mkdir(parents=True)
    workspace.mkdir()
    marker = workspace / ".git"
    marker.write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    (git_dir / "gitdir").write_text(str(marker), encoding="utf-8")
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    sandbox = SandboxConfig(
        workspace=str(workspace),
        denied_roots=[],
        denied_patterns=[],
        native_process_isolation="required",
    )

    assert _linked_worktree_git_roots(workspace) == [common.resolve()]
    assert common.resolve() in _writable_roots(sandbox)


def test_linked_worktree_rejects_untrusted_gitdir_without_backlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external" / ".git" / "worktrees" / "other"
    workspace.mkdir()
    external.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {external}\n", encoding="utf-8")
    (external / "commondir").write_text("../..\n", encoding="utf-8")

    assert _linked_worktree_git_roots(workspace) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_macos_required_blocks_indirect_read_from_denied_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    denied = tmp_path / "denied"
    workspace.mkdir()
    denied.mkdir()
    secret = denied / "secret.txt"
    secret.write_text("synthetic-secret", encoding="utf-8")
    sandbox = SandboxConfig(
        workspace=str(workspace),
        denied_roots=[denied],
        denied_patterns=[],
        native_process_isolation="required",
    )
    executable, args = sandboxed_process_argv(
        sys.executable,
        ["-c", f"print(open({str(secret)!r}).read())"],
        sandbox=sandbox,
        cwd=workspace,
    )

    completed = subprocess.run(
        [executable, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "synthetic-secret" not in completed.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_macos_required_blocks_indirect_read_matching_denied_glob(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = workspace / ".env"
    secret.write_text("SYNTHETIC_SECRET=value", encoding="utf-8")
    sandbox = SandboxConfig(
        workspace=str(workspace),
        denied_roots=[],
        denied_patterns=["**/.env"],
        native_process_isolation="required",
    )
    executable, args = sandboxed_process_argv(
        sys.executable,
        ["-c", f"print(open({str(secret)!r}).read())"],
        sandbox=sandbox,
        cwd=workspace,
    )

    completed = subprocess.run(
        [executable, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "SYNTHETIC_SECRET" not in completed.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_macos_required_blocks_indirect_write_matching_denied_glob(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = workspace / ".env"
    secret.write_text("ORIGINAL=value", encoding="utf-8")
    sandbox = SandboxConfig(
        workspace=str(workspace),
        denied_roots=[],
        denied_patterns=["**/.env"],
        native_process_isolation="required",
    )
    executable, args = sandboxed_process_argv(
        sys.executable,
        ["-c", f"open({str(secret)!r}, 'w').write('REPLACED=value')"],
        sandbox=sandbox,
        cwd=workspace,
    )

    completed = subprocess.run(
        [executable, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert secret.read_text(encoding="utf-8") == "ORIGINAL=value"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_macos_required_blocks_indirect_write_to_read_only_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    read_only = tmp_path / "read-only"
    workspace.mkdir()
    read_only.mkdir()
    target = read_only / "source.txt"
    target.write_text("original", encoding="utf-8")
    sandbox = SandboxConfig(
        workspace=str(workspace),
        extra_workspace_paths=[str(read_only)],
        read_only_paths=[str(read_only)],
        denied_roots=[],
        denied_patterns=[],
        native_process_isolation="required",
    )
    executable, args = sandboxed_process_argv(
        sys.executable,
        ["-c", f"open({str(target)!r}, 'w').write('replaced')"],
        sandbox=sandbox,
        cwd=workspace,
    )

    completed = subprocess.run(
        [executable, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_macos_required_allows_commit_in_linked_worktree(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is unavailable")
    source = tmp_path / "source"
    workspace = tmp_path / "task-worktree"
    subprocess.run([git, "init", "-q", str(source)], check=True)
    subprocess.run(
        [
            git,
            "-C",
            str(source),
            "-c",
            "user.name=Sandbox Audit",
            "-c",
            "user.email=sandbox@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        check=True,
    )
    subprocess.run(
        [git, "-C", str(source), "worktree", "add", "-q", "-b", "task", str(workspace)],
        check=True,
    )
    sandbox = SandboxConfig(
        workspace=str(workspace),
        denied_roots=[],
        denied_patterns=[],
        native_process_isolation="required",
    )
    executable, args = sandboxed_process_argv(
        git,
        [
            "-c",
            "user.name=Sandbox Audit",
            "-c",
            "user.email=sandbox@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "sandbox-probe",
        ],
        sandbox=sandbox,
        cwd=workspace,
    )
    env = {**os.environ, "TMPDIR": "/private/tmp"}

    completed = subprocess.run(
        [executable, *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
