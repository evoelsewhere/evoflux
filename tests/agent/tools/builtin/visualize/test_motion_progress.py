from __future__ import annotations

import pytest

from app.agent.state import AgentState
from app.agent.tools.builtin.visualize.motion_progress import motion_progress


def motion_state() -> AgentState:
    state = AgentState(messages=[], system_prompt="")
    state.metadata.update({"session_id": "session-1", "run_id": "run-1"})
    return state


@pytest.mark.asyncio
async def test_tool_owns_job_id_and_monotonic_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memory_stream_store

    pushed = []

    async def push_event(session_id, envelope):
        pushed.append((session_id, envelope.data))

    monkeypatch.setattr(memory_stream_store, "push_event", push_event)
    state = motion_state()
    args = {
        "artifact_id": "rainfall-story",
        "artifact_revision": 1,
        "phase": "storyboard",
        "status": "running",
        "beat": {"id": "collect", "index": 0, "total": 4, "title": "Collect"},
    }

    first = await motion_progress(
        **args, _state=state, session_id="session-1", agent_name="lead"
    )
    second = await motion_progress(
        **{**args, "phase": "composing"},
        _state=state,
        session_id="session-1",
        agent_name="lead",
    )

    assert first["success"] and second["success"]
    assert pushed[0][0] == "session-1"
    assert pushed[0][1]["job_id"] == pushed[1][1]["job_id"]
    assert [item[1]["sequence"] for item in pushed] == [1, 2]
    properties = motion_progress.definition["function"]["parameters"]["properties"]
    assert "job_id" not in properties
    assert "sequence" not in properties
    assert "frames" not in properties


@pytest.mark.asyncio
async def test_tool_rejects_session_mismatch_and_revision_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memory_stream_store

    async def push_event(*args, **kwargs):
        raise AssertionError("invalid lifecycle update must not be published")

    monkeypatch.setattr(memory_stream_store, "push_event", push_event)
    state = motion_state()
    args = {
        "artifact_id": "rainfall-story",
        "artifact_revision": 1,
        "phase": "storyboard",
        "status": "running",
    }
    mismatch = await motion_progress(**args, _state=state, session_id="other-session")
    assert mismatch["success"] is False

    async def noop_push(*args, **kwargs):
        return None

    monkeypatch.setattr(memory_stream_store, "push_event", noop_push)
    await motion_progress(**args, _state=state, session_id="session-1")
    regression = await motion_progress(
        **{**args, "artifact_revision": 0}, _state=state, session_id="session-1"
    )
    assert regression["success"] is False
