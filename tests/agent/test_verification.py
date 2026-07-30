"""Tests for machine-bound coding completion contracts."""

from __future__ import annotations

import json
from pathlib import Path
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

    async def passing_checks(workspace, changed_files, artifact_hash, rigor):
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


async def test_failed_contract_blocks_completion_and_final_handoff(
    sandbox: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (sandbox / "broken.py").write_text("broken =\n", encoding="utf-8")
    hook = CompletionVerificationHook()
    state = SimpleNamespace(metadata={"_verification_changed_files": {"broken.py"}})
    ctx = SimpleNamespace(session_id="verification-test")

    async def failing_checks(workspace, changed_files, artifact_hash, rigor):
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
