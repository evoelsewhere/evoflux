"""Route tests for the suggested-task chips.

The isolated (worktree) branch is not exercised here: it delegates to
``POST /workspace/worktrees``, which has its own coverage and needs a real git
repository on disk.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_loop import Agent
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam
from app.agent.providers.base import LLMProviderBase
from app.models.chat import ChatSession
from app.services import suggested_task_service as svc

PROMPT = (
    "In app/services/example.py the retry loop swallows the final exception. "
    "Reproduce with `pytest tests/services/test_example.py -q`, then surface "
    "the error instead of returning None."
)


class MockProvider(LLMProviderBase):
    model = "mock"

    def stream(self, messages, tools=None, **kwargs):
        async def gen():
            return
            yield

        return gen()

    async def chat(self, messages, tools=None, **kwargs):
        from app.agent.schemas.chat import AssistantMessage

        return AssistantMessage(content="OK")


@pytest.fixture
def app_with_team():
    from app.api.app import create_app
    from app.services.team_manager import set_team

    lead = TeamLead(
        Agent(name="lead", llm_provider=MockProvider(), system_prompt="Lead")
    )
    app = create_app()
    set_team(AgentTeam(lead=lead))
    yield app
    set_team(None)


async def _seed(tmp_path, *, title="Fix swallowed retry exception"):
    """Create a coding session with one pending suggestion; return both ids."""
    import app.core.db as _db

    workspace = tmp_path / "repo"
    workspace.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid7()
    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(
                ChatSession(
                    id=session_id,
                    agent_name="lead",
                    mode="coding",
                    workspace=str(workspace),
                )
            )
        async with db.begin():
            task, _ = await svc.create(
                db,
                session_id,
                title=title,
                tldr="Noticed while reading the retry helper.",
                prompt=PROMPT,
            )
            task_id = task.id
    return session_id, task_id, str(workspace)


@pytest.mark.asyncio
async def test_list_returns_pending_chips(app_with_team, tmp_path):
    session_id, task_id, _ = await _seed(tmp_path)

    response = TestClient(app_with_team).get(
        f"/api/team/sessions/{session_id}/suggested-tasks"
    )

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert [t["id"] for t in tasks] == [str(task_id)]
    assert tasks[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_start_creates_a_top_level_session_and_returns_the_prompt(
    app_with_team, tmp_path
):
    import app.core.db as _db

    session_id, task_id, workspace = await _seed(tmp_path)

    response = TestClient(app_with_team).post(
        f"/api/team/suggested-tasks/{task_id}/start", json={"isolated": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"] == workspace
    assert body["worktree_path"] is None
    # The client posts this itself; the route must not have sent it.
    assert body["prompt"] == PROMPT
    assert body["task"]["status"] == "started"

    async with _db.async_session_factory() as db:
        spawned = await db.get(ChatSession, uuid.UUID(body["session_id"]))
        assert spawned is not None
        # Its own sidebar entry, not a child of the session that suggested it.
        assert spawned.parent_session_id is None
        assert spawned.mode == "coding"
        assert spawned.workspace == workspace
        task = await svc.get(db, task_id)
        assert task is not None
        assert task.spawned_session_id == spawned.id

    assert session_id is not None


@pytest.mark.asyncio
async def test_start_twice_conflicts(app_with_team, tmp_path):
    _session_id, task_id, _ = await _seed(tmp_path)
    client = TestClient(app_with_team)

    first = client.post(
        f"/api/team/suggested-tasks/{task_id}/start", json={"isolated": False}
    )
    second = client.post(
        f"/api/team/suggested-tasks/{task_id}/start", json={"isolated": False}
    )

    assert first.status_code == 200
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_dismiss_removes_the_chip_from_the_list(app_with_team, tmp_path):
    session_id, task_id, _ = await _seed(tmp_path)
    client = TestClient(app_with_team)

    dismissed = client.post(
        f"/api/team/suggested-tasks/{task_id}/dismiss", json={"reason": "not worth it"}
    )
    listed = client.get(f"/api/team/sessions/{session_id}/suggested-tasks")
    with_resolved = client.get(
        f"/api/team/sessions/{session_id}/suggested-tasks?include_resolved=true"
    )

    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert listed.json()["tasks"] == []
    assert [t["id"] for t in with_resolved.json()["tasks"]] == [str(task_id)]


@pytest.mark.asyncio
async def test_dismiss_after_start_conflicts(app_with_team, tmp_path):
    _session_id, task_id, _ = await _seed(tmp_path)
    client = TestClient(app_with_team)

    client.post(f"/api/team/suggested-tasks/{task_id}/start", json={"isolated": False})
    response = client.post(f"/api/team/suggested-tasks/{task_id}/dismiss", json={})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_unknown_task_is_404(app_with_team):
    response = TestClient(app_with_team).post(
        f"/api/team/suggested-tasks/{uuid.uuid7()}/start", json={"isolated": False}
    )

    assert response.status_code == 404
