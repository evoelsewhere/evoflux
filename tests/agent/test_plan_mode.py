"""Tests for plan mode — service revise loop and exit_plan_mode tool messages."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.plan import (
    PlanModeService,
    get_service_for_session,
    reset_plan_mode_service,
    set_plan_mode_service,
)
from app.agent.tools.builtin.plan import _exit_plan_mode


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


# ---------------------------------------------------------------------------
# Run wiring
# ---------------------------------------------------------------------------


def test_run_config_copies_the_metadata_dict_it_is_handed():
    """Pin the pydantic behaviour that silently disabled plan mode.

    ``RunConfig`` validation copies the dict, so anything written to the
    caller's dict afterwards lands somewhere the run never reads. The team
    member used to build its ``RunConfig`` before setting ``_plan_mode``, so
    the flag never arrived: the tool executor intercepted nothing, and because
    the permission service treated "plan" as auto-allow, the mode quietly
    became the most permissive one instead of the most cautious.
    """
    from app.agent.schemas.agent import RunConfig

    metadata: dict[str, object] = {"team_mode": "work"}
    config = RunConfig(session_id=None, metadata=metadata)
    metadata["_plan_mode"] = True

    assert config.metadata is not metadata
    assert config.metadata.get("_plan_mode") is None


def test_member_builds_run_config_after_writing_plan_metadata():
    """Guard the ordering, since the failure mode is silent.

    Nothing raises when the two are the wrong way round — plan mode just stops
    planning — so the only cheap protection is asserting the order in source.
    """
    import inspect

    from app.agent.mode.team import member as member_module

    source = inspect.getsource(member_module.TeamMember._handle_messages)
    plan_flag = source.index('run_metadata["_plan_mode"] = True')
    build = source.index("config = RunConfig(")
    assert plan_flag < build, (
        "RunConfig must be built after the last write to run_metadata; "
        "pydantic copies the dict, so later writes are lost."
    )


def test_plan_intercepted_tools_is_the_list_both_layers_gate_on():
    """One list, two readers.

    The tool executor decides what to record; the permission service decides
    what still needs approval because it will really run. If those drift, a
    tool is either recorded and asked about, or neither.
    """
    from app.agent.agent_loop.tool_executor import _PLAN_INTERCEPTED
    from app.agent.plan import PLAN_INTERCEPTED_TOOLS

    assert _PLAN_INTERCEPTED is PLAN_INTERCEPTED_TOOLS
    assert "shell" in PLAN_INTERCEPTED_TOOLS
    assert "browser_use" not in PLAN_INTERCEPTED_TOOLS
