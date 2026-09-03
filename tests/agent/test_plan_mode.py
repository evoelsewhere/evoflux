"""Tests for plan mode — service revise loop and exit_plan_mode tool messages."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.agent_loop import Agent
from app.agent.plan import (
    PlanModeService,
    get_service_for_session,
    reset_plan_mode_service,
    set_plan_mode_service,
)
from app.agent.schemas.agent import RunConfig
from app.agent.schemas.chat import HumanMessage, ToolMessage
from app.agent.tools.builtin.plan import _exit_plan_mode
from app.agent.tools.registry import Tool
from tests.agent.test_agent_run import MockProvider, make_text_chunk, make_tool_chunk


@pytest.fixture
def service():
    svc = PlanModeService(session_id="plan-sess", stream_session_id="plan-sess")
    token = set_plan_mode_service(svc)
    yield svc
    reset_plan_mode_service(token, "plan-sess")


async def _pending_id(svc: PlanModeService) -> str:
    """Wait until the service has one pending request and return its id."""
    for _ in range(100):
        if svc._pending:
            return next(iter(svc._pending))
        await asyncio.sleep(0.005)
    raise AssertionError("no pending plan request appeared")


# ── PlanModeService ───────────────────────────────────────────────────────────


async def test_empty_plan_and_steps_auto_approves(service: PlanModeService):
    service.enter()
    decision, feedback = await service.request_approval("")
    assert (decision, feedback) == ("approved", "")
    assert service.active is False


async def test_plan_without_steps_still_requests_approval(service: PlanModeService):
    service.enter()
    task = asyncio.create_task(service.request_approval("# The plan"))
    req_id = await _pending_id(service)

    assert service.reply(req_id, "approved") is True
    assert await task == ("approved", "")


async def test_revise_keeps_plan_mode_and_steps(service: PlanModeService):
    service.enter()
    service.record_step("edit", {"path": "a.py"}, "edit a.py")
    task = asyncio.create_task(service.request_approval("# Plan v1"))
    req_id = await _pending_id(service)

    assert service.reply(req_id, "revise", "use pathlib instead") is True
    decision, feedback = await task

    assert decision == "revise"
    assert feedback == "use pathlib instead"
    assert service.active is True  # still in plan mode
    assert service.step_count == 1  # recorded steps kept for the next round


async def test_approved_clears_plan_mode_and_steps(service: PlanModeService):
    service.enter()
    service.record_step("write", {"path": "b.py"}, "write b.py")
    task = asyncio.create_task(service.request_approval("# Plan"))
    req_id = await _pending_id(service)

    service.reply(req_id, "approved")
    decision, _ = await task

    assert decision == "approved"
    assert service.active is False
    assert service.step_count == 0
    assert service.approved_step_count == 1
    assert service.approved_manifest_hash is not None


async def test_approved_calls_must_match_and_execute_in_order(
    service: PlanModeService,
):
    service.enter()
    service.record_step("edit", {"path": "a.py", "old_string": "a"}, "edit a.py")
    service.record_step("shell", {"command": "pytest"}, "run tests")
    task = asyncio.create_task(service.request_approval("# Plan"))
    req_id = await _pending_id(service)
    service.reply(req_id, "approved")
    await task

    mismatch = service.authorize_approved_call(
        "edit", {"path": "b.py", "old_string": "a"}
    )
    assert mismatch is not None
    assert mismatch[0] is False
    assert service.approved_step_count == 2

    first = service.authorize_approved_call("edit", {"old_string": "a", "path": "a.py"})
    assert first is not None
    assert first[0] is True
    assert service.approved_step_count == 1

    second = service.authorize_approved_call("shell", {"command": "pytest"})
    assert second is not None
    assert second[0] is True
    assert service.approved_step_count == 0

    extra = service.authorize_approved_call("shell", {"command": "rm -rf build"})
    assert extra is not None
    assert extra[0] is False
    assert "exhausted" in extra[1]


async def test_reply_unknown_request_returns_false(service: PlanModeService):
    assert service.reply("nope", "approved") is False


async def test_cancelled_wait_cleans_up_pending(service: PlanModeService):
    service.enter()
    service.record_step("rm", {"path": "c.py"}, "rm c.py")
    task = asyncio.create_task(service.request_approval("# Plan"))
    req_id = await _pending_id(service)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert req_id not in service._pending


async def test_service_registered_for_http_lookup(service: PlanModeService):
    assert get_service_for_session("plan-sess") is service


# ── exit_plan_mode tool ───────────────────────────────────────────────────────


async def _run_tool(service: PlanModeService, state, plan: str = "# Plan"):
    task = asyncio.create_task(_exit_plan_mode(plan, _state=state))
    req_id = await _pending_id(service)
    return task, req_id


async def test_tool_approved_message_and_metadata(service: PlanModeService):
    state = SimpleNamespace(metadata={"_plan_mode": True})
    service.enter()
    service.record_step("edit", {}, "edit x")
    task, req_id = await _run_tool(service, state)

    service.reply(req_id, "approved")
    msg = await task

    assert "Plan approved" in msg
    assert "1 exact step(s)" in msg
    assert "manifest" in msg
    assert state.metadata["_plan_mode"] is False


async def test_tool_revise_message_carries_feedback_and_stays_in_plan_mode(
    service: PlanModeService,
):
    state = SimpleNamespace(metadata={"_plan_mode": True})
    service.enter()
    task, req_id = await _run_tool(service, state)

    service.reply(req_id, "revise", "split step 2 into two commits")
    msg = await task

    assert "split step 2 into two commits" in msg
    assert "still in plan mode" in msg
    assert state.metadata["_plan_mode"] is True


async def test_tool_rejected_message_includes_optional_feedback(
    service: PlanModeService,
):
    state = SimpleNamespace(metadata={"_plan_mode": True})
    service.enter()
    task, req_id = await _run_tool(service, state)

    service.reply(req_id, "rejected", "wrong direction entirely")
    msg = await task

    assert "Plan rejected" in msg
    assert "wrong direction entirely" in msg
    assert state.metadata["_plan_mode"] is False


# ── End-to-end interception through Agent.run() (BUG-007) ─────────────────


async def test_plan_mode_intercepts_destructive_tool_end_to_end(
    service: PlanModeService,
):
    """With `_plan_mode` active in state.metadata, a real Agent.run() turn
    must record a destructive tool call instead of executing it — the tool
    body must never run and the model must see the `[PLAN]` sentinel, not
    real execution output.

    This is the exact scenario from BUG-007: plan mode silently executed
    edits/shell commands for real because `run_metadata["_plan_mode"]` was
    mutated after `RunConfig` had already copied the dict, so the tool
    executor's `s.metadata.get("_plan_mode")` check was always False.
    """
    side_effects: list[tuple[str, str]] = []

    def write(path: str, content: str) -> str:
        """Write a file — must never actually run while plan mode is active."""
        side_effects.append((path, content))
        return f"REAL WRITE: wrote {len(content)} bytes to {path}"

    provider = MockProvider(
        [
            [make_tool_chunk("write", "call_1", '{"path": "a.txt", "content": "hi"}')],
            [make_text_chunk("Recorded the plan step.")],
        ]
    )
    agent = Agent(name="bot", llm_provider=provider, tools=[Tool(write, name="write")])
    service.enter()
    config = RunConfig(session_id="plan-sess", metadata={"_plan_mode": True})

    msgs = await agent.run([HumanMessage(content="write a.txt")], config=config)

    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    content = tool_msgs[0].content
    assert content is not None
    assert content.startswith("[PLAN] Step 1 recorded: write")
    assert "REAL WRITE" not in content
    assert side_effects == []  # the tool body was never actually invoked
    assert service.step_count == 1


async def test_plan_mode_inactive_executes_tool_for_real(service: PlanModeService):
    """Control case: without `_plan_mode` set, the same tool call executes
    normally — proving the interception in the test above is specific to
    plan mode, not an artifact of the test setup."""
    side_effects: list[tuple[str, str]] = []

    def write(path: str, content: str) -> str:
        """Write a file."""
        side_effects.append((path, content))
        return f"REAL WRITE: wrote {len(content)} bytes to {path}"

    provider = MockProvider(
        [
            [make_tool_chunk("write", "call_1", '{"path": "a.txt", "content": "hi"}')],
            [make_text_chunk("Done.")],
        ]
    )
    agent = Agent(name="bot", llm_provider=provider, tools=[Tool(write, name="write")])
    config = RunConfig(session_id="plan-sess")

    msgs = await agent.run([HumanMessage(content="write a.txt")], config=config)

    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert "REAL WRITE" in (tool_msgs[0].content or "")
    assert side_effects == [("a.txt", "hi")]
