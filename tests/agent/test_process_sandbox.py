"""Security policy tests for native shell-process containment."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from app.agent.process_sandbox import (
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
