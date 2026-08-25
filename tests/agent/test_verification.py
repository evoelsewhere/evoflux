"""Tests for machine-bound coding completion contracts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.agent import verification as verification_module
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.verification import CompletionVerificationHook, VerificationEvidence


@pytest.fixture
def sandbox(tmp_path: Path):
    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        yield tmp_path
    finally:
        _sandbox_ctx.reset(token)


def _tool_call(name: str, args: dict):
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def test_pytest_verification_uses_current_interpreter_module(monkeypatch):
    monkeypatch.setattr(
        verification_module.importlib.util, "find_spec", lambda _: object()
    )
    monkeypatch.setattr(verification_module.sys, "executable", "/runtime/python")

    assert verification_module._pytest_command_prefix() == [
        "/runtime/python",
        "-m",
        "pytest",
    ]


def test_artifact_hash_changes_when_repository_revision_changes(sandbox: Path):
    target = sandbox / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")

    first = verification_module._artifact_hash(
        sandbox,
        ("module.py",),
        repository_revision="revision-one",
    )
    second = verification_module._artifact_hash(
        sandbox,
        ("module.py",),
        repository_revision="revision-two",
    )

    assert first != second


def test_artifact_hash_changes_when_accepted_commands_change(sandbox: Path):
    target = sandbox / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")

    first = verification_module._artifact_hash(
        sandbox,
        ("module.py",),
        planned_commands=("python -m compileall module.py",),
    )
    second = verification_module._artifact_hash(
        sandbox,
        ("module.py",),
        planned_commands=("python -m compileall other.py",),
    )

    assert first != second


async def test_accepted_planned_command_runs_as_machine_evidence(sandbox: Path):
    target = sandbox / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")

    evidence = await verification_module._run_required_checks(
        sandbox,
        ("module.py",),
        "a" * 64,
        planned_commands=("python -m compileall module.py",),
    )

    planned = [item for item in evidence if item.source == "planned"]
    assert len(planned) == 1
    assert planned[0].passed is True
    assert planned[0].spec_command == "python -m compileall module.py"
    assert planned[0].command[:3] == [
        verification_module.sys.executable,
        "-m",
        "compileall",
    ]


async def test_easd_scope_violation_blocks_completion(sandbox: Path):
    (sandbox / "outside.py").write_text("value = 1\n", encoding="utf-8")
    hook = CompletionVerificationHook()
    state = SimpleNamespace(
        metadata={
            "_verification_changed_files": {"outside.py"},
            "_easd_impact_targets": [{"repository": "repo", "path": "app/allowed.py"}],
        }
    )
    ctx = SimpleNamespace(session_id="verification-test")

    feedback = await hook.before_completion(ctx, state, SimpleNamespace())

    assert feedback is not None
    assert "EASD scope violation" in feedback
    assert "outside.py" in feedback


def test_easd_scope_identity_distinguishes_same_path_in_two_repositories(
    tmp_path: Path,
):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    sandbox = SimpleNamespace(allowed_workspace_roots=[backend, frontend])

    paths, targets = verification_module._scope_changes(
        sandbox,
        (str(frontend / "app/shared.py"),),
        [
            {"repository": "Backend", "path": str(backend)},
            {"repository": "Frontend", "path": str(frontend)},
        ],
    )

    assert paths == ("app/shared.py",)
    assert targets == ({"repository": "Frontend", "path": "app/shared.py"},)
    assert verification_module._outside_impact_targets(
        targets,
        [{"repository": "Backend", "path": "app/shared.py"}],
    ) == ["Frontend:app/shared.py"]


def test_changed_files_are_grouped_by_authorized_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    monkeypatch.setattr(
        verification_module,
        "get_sandbox",
        lambda: SimpleNamespace(allowed_workspace_roots=[backend, frontend]),
    )

    grouped = verification_module._changed_files_by_repository(
        backend,
        (
            "app/service.py",
            str(frontend / "src/App.tsx"),
        ),
    )

    assert grouped == {
        backend.resolve(): [Path("app/service.py")],
        frontend.resolve(): [Path("src/App.tsx")],
    }


async def test_easd_detects_changes_not_made_by_file_tools(sandbox: Path):
    subprocess.run(["git", "init", "-q", str(sandbox)], check=True)
    baseline = sandbox / "baseline.py"
    baseline.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(sandbox), "add", "baseline.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(sandbox),
            "-c",
            "user.name=EvoFlux Test",
            "-c",
            "user.email=test@evoflux.local",
            "commit",
            "-q",
            "-m",
            "baseline",
        ],
        check=True,
    )
    hook = CompletionVerificationHook()
    state = SimpleNamespace(
        metadata={
            "_easd_run_id": "run-1",
            "_easd_impact_targets": [{"repository": "repo", "path": "app/allowed.py"}],
        }
    )
    ctx = SimpleNamespace(session_id="verification-test")
    await hook.before_agent(ctx, state)

    (sandbox / "outside.py").write_text("value = 2\n", encoding="utf-8")
    feedback = await hook.before_completion(ctx, state, SimpleNamespace())

    assert feedback is not None
    assert "EASD scope violation" in feedback
    assert "outside.py" in feedback


async def test_changed_file_requires_and_persists_passing_evidence(
    sandbox: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = sandbox / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")
    hook = CompletionVerificationHook()
    state = SimpleNamespace(metadata={})
    ctx = SimpleNamespace(session_id="verification-test")
    await hook.before_agent(ctx, state)

    async def handler(_ctx, _state, _tool_call):
        target.write_text("value = 2\n", encoding="utf-8")
        return "Edit applied successfully"

    await hook.wrap_tool_call(
        ctx,
        state,
        _tool_call(
            "edit",
            {"path": "module.py", "old_string": "1", "new_string": "2"},
        ),
        handler,
    )

    async def passing_checks(
        workspace, changed_files, artifact_hash, rigor, planned_commands
    ):
        assert planned_commands == ()
        return [
            VerificationEvidence(
                command_id="cmd-1",
                command=["ruff", "check", "module.py"],
                cwd=str(workspace),
                exit_code=0,
                revision="abc123",
                artifact_hash=artifact_hash,
                output="All checks passed!",
            )
        ]

    monkeypatch.setattr(verification_module, "_run_required_checks", passing_checks)
    assert await hook.before_completion(ctx, state, SimpleNamespace()) is None

    contract = state.metadata["completion_contract"]
    assert contract["passed"] is True
    assert contract["evidence"][0]["command_id"] == "cmd-1"
    assert contract["evidence"][0]["revision"] == "abc123"


async def test_easd_verify_runs_accepted_commands_without_file_mutation(
    sandbox: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    hook = CompletionVerificationHook()
    state = SimpleNamespace(
        metadata={
            "_easd_phase": "verifying",
            "_easd_verification_commands": ["python -m compileall module.py"],
        }
    )
    ctx = SimpleNamespace(session_id="verification-test")

    async def passing_checks(
        workspace, changed_files, artifact_hash, rigor, planned_commands
    ):
        assert changed_files == ()
        assert planned_commands == ("python -m compileall module.py",)
        return [
            VerificationEvidence(
                command_id="cmd-verify",
                command=["python", "-m", "compileall", "module.py"],
                cwd=str(workspace),
                exit_code=0,
                revision="verify-revision",
                artifact_hash=artifact_hash,
                output="verified",
                source="planned",
                spec_command="python -m compileall module.py",
            )
        ]

    monkeypatch.setattr(verification_module, "_run_required_checks", passing_checks)

    assert await hook.before_completion(ctx, state, SimpleNamespace()) is None
    contract = state.metadata["completion_contract"]
    assert contract["changed_files"] == []
    assert contract["passed"] is True
    assert contract["evidence"][0]["source"] == "planned"


async def test_failed_contract_blocks_completion_and_final_handoff(
    sandbox: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (sandbox / "broken.py").write_text("broken =\n", encoding="utf-8")
    hook = CompletionVerificationHook()
    state = SimpleNamespace(metadata={"_verification_changed_files": {"broken.py"}})
    ctx = SimpleNamespace(session_id="verification-test")

    async def failing_checks(
        workspace, changed_files, artifact_hash, rigor, planned_commands
    ):
        assert planned_commands == ()
        return [
            VerificationEvidence(
                command_id="cmd-fail",
                command=["ruff", "check", "broken.py"],
                cwd=str(workspace),
                exit_code=1,
                revision="abc123",
                artifact_hash=artifact_hash,
                output="syntax error",
            )
        ]

    monkeypatch.setattr(verification_module, "_run_required_checks", failing_checks)
    feedback = await hook.before_completion(ctx, state, SimpleNamespace())
    assert feedback is not None
    assert "syntax error" in feedback

    handler_called = False

    async def handoff_handler(_ctx, _state, _tool_call):
        nonlocal handler_called
        handler_called = True
        return "Handoff delivered"

    blocked = await hook.wrap_tool_call(
        ctx,
        state,
        _tool_call("team_handoff", {"status": "final"}),
        handoff_handler,
    )
    assert blocked.startswith("HANDOFF BLOCKED")
    assert handler_called is False
