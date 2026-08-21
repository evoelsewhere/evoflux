"""Tests for team route DB endpoints — list_sessions, get_session, delete_session, history.

Covers uncovered lines: 195-215, 226-245, 258-267, 296-340.
These tests use the real in-memory DB to exercise the SQL queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import col, select

from app.agent.agent_loop import Agent
from app.agent.providers.base import LLMProviderBase
from app.agent.mode.team.member import TeamLead, TeamMember
from app.agent.mode.team.team import AgentTeam
from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
    CodingWorkspace,
    SessionMessage,
)
from app.services import goal_service


class MockProvider(LLMProviderBase):
    model = "mock"

    def stream(self, messages, tools=None, **kwargs):
        from app.agent.schemas.chat import (
            ChatCompletionChunk,
            ChatCompletionChunkChoice,
            ChatCompletionDelta,
        )

        async def gen():
            yield ChatCompletionChunk(
                id="1",
                created=1000,
                model="mock",
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionDelta(content="OK"),
                        finish_reason="stop",
                    )
                ],
            )

        return gen()

    async def chat(self, messages, tools=None, **kwargs):
        from app.agent.schemas.chat import AssistantMessage

        return AssistantMessage(content="OK")


@pytest.fixture
def test_team():
    lead = TeamLead(
        Agent(name="lead", llm_provider=MockProvider(), system_prompt="Lead")
    )
    worker = TeamMember(
        Agent(name="worker", llm_provider=MockProvider(), system_prompt="Worker")
    )
    return AgentTeam(lead=lead, members={"worker": worker})


@pytest.fixture
def app_with_team(test_team):
    from app.api.app import create_app
    from app.services.team_manager import set_team

    app = create_app()
    set_team(test_team)
    yield app
    set_team(None)


async def _create_team_session(db, session_id, agent_name="lead", **kwargs):
    """Helper to create a top-level (team lead) session in DB."""
    session = ChatSession(
        id=session_id,
        agent_name=agent_name,
        **kwargs,
    )
    db.add(session)
    return session


async def _create_member_session(db, session_id, parent_id, agent_name="worker"):
    """Helper to create a team-member session (child of a lead) in DB."""
    session = ChatSession(
        id=session_id,
        parent_session_id=parent_id,
        agent_name=agent_name,
    )
    db.add(session)
    return session


async def _add_message(db, session_id, role="user", content="test", **kwargs):
    msg = SessionMessage(
        session_id=session_id,
        role=role,
        content=content,
        **kwargs,
    )
    db.add(msg)
    return msg


# ---------------------------------------------------------------------------
# GET /team/sessions — list with children (lines 163-215)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /team/sessions — cursor-paginated list with children
# ---------------------------------------------------------------------------


class TestListTeamSessionsWithData:
    @pytest.mark.asyncio
    async def test_list_sessions_returns_lead_session(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        child_id = uuid.uuid7()

        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _create_member_session(db, child_id, lead_id)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions")
        assert resp.status_code == 200
        data = resp.json()

        assert "data" in data
        assert "has_more" in data
        assert "next_cursor" in data
        # Me lead session is in the list; member session is not
        found = [s for s in data["data"] if s["id"] == str(lead_id)]
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_session_metadata_does_not_include_history(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(
                    db,
                    lead_id,
                    title="Metadata only",
                    permission_mode="ask",
                )
                await _add_message(db, lead_id, content="large history payload")

        response = TestClient(app_with_team).get(
            f"/api/team/sessions/{lead_id}/metadata"
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Metadata only"
        assert response.json()["permission_mode"] == "ask"
        assert "messages" not in response.json()

    @pytest.mark.asyncio
    async def test_list_sessions_marks_running_sessions(self, app_with_team):
        import app.core.db as _db
        from app.services import memory_stream_store

        running_id = uuid.uuid7()
        idle_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, running_id)
                await _create_team_session(db, idle_id)

        await memory_stream_store.init_turn(str(running_id))
        try:
            client = TestClient(app_with_team)
            resp = client.get("/api/team/sessions")
            assert resp.status_code == 200
            by_id = {s["id"]: s for s in resp.json()["data"]}

            assert by_id[str(running_id)]["running"] is True
            assert by_id[str(idle_id)]["running"] is False
        finally:
            await memory_stream_store.clear(str(running_id))

    @pytest.mark.asyncio
    async def test_list_sessions_filters_coding_workspace(self, app_with_team):
        import app.core.db as _db

        workspace_id = uuid.uuid7()
        other_workspace_id = uuid.uuid7()
        normal_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(
                    db, workspace_id, mode="coding", workspace="/repo/project"
                )
                await _create_team_session(
                    db, other_workspace_id, mode="coding", workspace="/repo/other"
                )
                await _create_team_session(db, normal_id, mode="work")

        client = TestClient(app_with_team)
        resp = client.get(
            "/api/team/sessions",
            params={"mode": "coding", "workspace": "/repo/project"},
        )
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["data"]]
        assert ids == [str(workspace_id)]

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, app_with_team):
        """No team_lead sessions → empty data list, has_more=False."""
        client = TestClient(app_with_team)
        # Me use a before= cursor that predates any real data
        resp = client.get("/api/team/sessions?before=2000-01-01T00:00:00Z")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_list_sessions_pagination(self, app_with_team):
        import app.core.db as _db

        # Me create 3 lead sessions
        ids = [uuid.uuid7() for _ in range(3)]
        async with _db.async_session_factory() as db:
            async with db.begin():
                for sid in ids:
                    await _create_team_session(db, sid)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) <= 2


class TestResolveTeamSession:
    def test_resolve_creates_normal_session(self, app_with_team):
        client = TestClient(app_with_team)

        resp = client.post("/api/team/sessions/resolve", json={"mode": "work"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["mode"] == "work"
        assert "workspace" not in data

    def test_resolve_accepts_legacy_forge_and_emits_work(self, app_with_team):
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "forge", "create": True},
        )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "work"

    @pytest.mark.asyncio
    async def test_resolve_reuses_latest_normal_session(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)

        client = TestClient(app_with_team)
        resp = client.post("/api/team/sessions/resolve", json={"mode": "work"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is False
        assert data["id"] == str(lead_id)

    @pytest.mark.asyncio
    async def test_resolve_can_force_create_normal_session(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)

        client = TestClient(app_with_team)
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["id"] != str(lead_id)

    def test_resolve_creates_coding_session(self, app_with_team, tmp_path):
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": str(tmp_path)},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["mode"] == "coding"
        assert data["workspace"] == str(tmp_path.resolve())

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert [repo["path"] for repo in tree.json()["repositories"]] == [
            str(tmp_path.resolve())
        ]

    @pytest.mark.asyncio
    async def test_resolve_project_owned_workspace_canonicalizes_to_project(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        repo = tmp_path / "repo"
        repo.mkdir()
        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Canonical owner", workspace_paths=[str(repo)]
            )
            await db.commit()
            project_id = project.id

        client = TestClient(app_with_team)
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == str(project_id)
        assert data["workspace"] == str(repo.resolve())

        project_sessions = client.get(
            "/api/team/sessions", params={"mode": "coding", "project_id": project_id}
        )
        assert project_sessions.status_code == 200
        assert [item["id"] for item in project_sessions.json()["data"]] == [data["id"]]

    @pytest.mark.asyncio
    async def test_resolve_workspace_shared_by_projects_requires_explicit_project(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        repo = tmp_path / "shared"
        repo.mkdir()
        async with _db.async_session_factory() as db:
            await create_project(db, name="First", workspace_paths=[str(repo)])
            await create_project(db, name="Second", workspace_paths=[str(repo)])
            await db.commit()

        client = TestClient(app_with_team)
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 409
        assert "multiple projects" in resp.json()["detail"]

        sessions = client.get(
            "/api/team/sessions", params={"mode": "coding", "workspace": str(repo)}
        )
        assert sessions.status_code == 200
        assert sessions.json()["data"] == []

    def test_resolve_requires_workspace_for_coding(self, app_with_team):
        client = TestClient(app_with_team)

        resp = client.post("/api/team/sessions/resolve", json={"mode": "coding"})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_resolve_with_tags_creates_persists_and_returns_tags(
        self, app_with_team
    ):
        import app.core.db as _db

        client = TestClient(app_with_team)
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "tags": ["webbridge"], "create": True},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["tags"] == ["webbridge"]

        async with _db.async_session_factory() as db:
            row = await db.get(ChatSession, uuid.UUID(data["id"]))
        assert row is not None
        assert row.tags == ["webbridge"]

    def test_resolve_same_tags_reuses_session(self, app_with_team):
        client = TestClient(app_with_team)

        first = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "tags": ["webbridge"]},
        ).json()
        second = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "tags": ["webbridge"]},
        ).json()

        assert first["created"] is True
        assert second["created"] is False
        assert second["id"] == first["id"]
        assert second["tags"] == ["webbridge"]

    def test_resolve_contains_tags_reuses_session_with_extra_capability(
        self, app_with_team
    ):
        client = TestClient(app_with_team)

        first = client.post(
            "/api/team/sessions/resolve",
            json={
                "mode": "work",
                "tags": ["code-review", "code-review:v1:workspace:42", "webbridge"],
            },
        ).json()
        second = client.post(
            "/api/team/sessions/resolve",
            json={
                "mode": "work",
                "tags": ["code-review", "code-review:v1:workspace:42"],
                "tag_match": "contains",
            },
        ).json()

        assert second["created"] is False
        assert second["id"] == first["id"]
        assert second["tags"] == [
            "code-review",
            "code-review:v1:workspace:42",
            "webbridge",
        ]

    def test_resolve_untagged_does_not_return_tagged_session(self, app_with_team):
        client = TestClient(app_with_team)

        tagged = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "tags": ["webbridge"]},
        ).json()
        untagged = client.post(
            "/api/team/sessions/resolve", json={"mode": "work"}
        ).json()

        assert untagged["created"] is True
        assert untagged["id"] != tagged["id"]
        assert untagged["tags"] == []

    def test_resolve_tagged_does_not_return_untagged_session(self, app_with_team):
        client = TestClient(app_with_team)

        untagged = client.post(
            "/api/team/sessions/resolve", json={"mode": "work"}
        ).json()
        tagged = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "tags": ["webbridge"]},
        ).json()

        assert tagged["created"] is True
        assert tagged["id"] != untagged["id"]
        assert tagged["tags"] == ["webbridge"]

    @pytest.mark.asyncio
    async def test_list_and_detail_sessions_include_tags(self, app_with_team):
        import app.core.db as _db

        tagged_id = uuid.uuid7()
        untagged_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, tagged_id, tags=["webbridge"])
                await _create_team_session(db, untagged_id)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions")
        assert resp.status_code == 200
        by_id = {s["id"]: s for s in resp.json()["data"]}
        assert by_id[str(tagged_id)]["tags"] == ["webbridge"]
        assert by_id[str(untagged_id)]["tags"] == []

        detail = client.get(f"/api/team/sessions/{tagged_id}")
        assert detail.status_code == 200
        assert detail.json()["tags"] == ["webbridge"]

    @pytest.mark.asyncio
    async def test_resolve_existing_worktree_session_keeps_registry_child(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        repo = tmp_path / "repo"
        worktree = tmp_path / "worktrees" / "task-a"
        repo.mkdir()
        worktree.mkdir(parents=True)
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(CodingWorkspace(path=str(repo), kind="repo", name="repo"))
                db.add(
                    CodingWorkspace(
                        path=str(worktree),
                        kind="worktree",
                        source_path=str(repo),
                        name="task-a",
                        managed=True,
                    )
                )

        client = TestClient(app_with_team)
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": str(worktree)},
        )
        assert resp.status_code == 200

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        repos = tree.json()["repositories"]
        assert len(repos) == 1 and repos[0]["workspace_id"]
        assert {k: v for k, v in repos[0].items() if k != "workspace_id"} == {
            "path": str(repo),
            "name": "repo",
            "worktrees": [{"path": str(worktree), "name": "task-a", "managed": True}],
            "project_id": None,
        }

    @pytest.mark.asyncio
    async def test_workspace_tree_ignores_hidden_and_deleted_worktrees(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        repo = tmp_path / "repo"
        hidden = tmp_path / "worktrees" / "hidden"
        deleted = tmp_path / "worktrees" / "deleted"
        repo.mkdir()
        hidden.mkdir(parents=True)
        deleted.mkdir(parents=True)
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(CodingWorkspace(path=str(repo), kind="repo", name="repo"))
                db.add(
                    CodingWorkspace(
                        path=str(hidden),
                        kind="worktree",
                        source_path=str(repo),
                        name="hidden",
                        managed=True,
                        hidden=True,
                    )
                )
                db.add(
                    CodingWorkspace(
                        path=str(deleted),
                        kind="worktree",
                        source_path=str(repo),
                        name="deleted",
                        managed=True,
                        deleted_at=datetime.now(timezone.utc),
                    )
                )

        client = TestClient(app_with_team)
        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        repos = tree.json()["repositories"]
        assert len(repos) == 1 and repos[0]["workspace_id"]
        assert {k: v for k, v in repos[0].items() if k != "workspace_id"} == {
            "path": str(repo),
            "name": "repo",
            "worktrees": [],
            "project_id": None,
        }

    @pytest.mark.asyncio
    async def test_workspace_tree_keeps_visible_worktree_under_hidden_source(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        repo = tmp_path / "repo"
        worktree = tmp_path / "worktrees" / "task-a"
        repo.mkdir()
        worktree.mkdir(parents=True)
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(
                    CodingWorkspace(
                        path=str(repo), kind="repo", name="repo", hidden=True
                    )
                )
                db.add(
                    CodingWorkspace(
                        path=str(worktree),
                        kind="worktree",
                        source_path=str(repo),
                        name="task-a",
                        managed=True,
                    )
                )

        client = TestClient(app_with_team)
        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        # The source repo itself is hidden, so it has no row in `rows` to
        # source a real workspace_id from — the synthesized fallback entry
        # leaves it None (see list_coding_workspace_tree).
        assert tree.json()["repositories"] == [
            {
                "workspace_id": None,
                "path": str(repo),
                "name": "repo",
                "worktrees": [
                    {"path": str(worktree), "name": "task-a", "managed": True}
                ],
                "project_id": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_workspace_tree_marks_project_membership_via_real_fk(
        self, app_with_team, tmp_path
    ):
        """project_id on a tree entry must come from the CodingProjectWorkspace
        FK, not be something the frontend has to reconstruct by matching
        paths against a separately-fetched /projects list."""
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        in_project = tmp_path / "in-project"
        standalone = tmp_path / "standalone"
        in_project.mkdir()
        standalone.mkdir()
        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Demo", workspace_paths=[str(in_project)]
            )
            await db.commit()
            project_id = project.id
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(
                    CodingWorkspace(
                        path=str(standalone), kind="repo", name="standalone"
                    )
                )

        client = TestClient(app_with_team)
        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        body = tree.json()
        by_path = {repo["path"]: repo for repo in body["repositories"]}
        assert by_path[str(in_project)]["project_id"] == str(project_id)
        assert by_path[str(standalone)]["project_id"] is None
        assert [p["id"] for p in body["projects"]] == [str(project_id)]

    @pytest.mark.asyncio
    async def test_workspace_tree_ignores_memberships_to_invisible_projects(
        self, app_with_team, tmp_path
    ):
        """A stale membership must not hide a reopened repository from both
        sidebar sections when its former project is no longer visible."""
        import app.core.db as _db

        hidden_repo = tmp_path / "hidden-owner-repo"
        deleted_repo = tmp_path / "deleted-owner-repo"
        hidden_repo.mkdir()
        deleted_repo.mkdir()
        async with _db.async_session_factory() as db:
            async with db.begin():
                hidden_project = CodingProject(name="Hidden", hidden=True)
                deleted_project = CodingProject(
                    name="Deleted", deleted_at=datetime.now(timezone.utc)
                )
                hidden_workspace = CodingWorkspace(
                    path=str(hidden_repo), kind="repo", name=hidden_repo.name
                )
                deleted_workspace = CodingWorkspace(
                    path=str(deleted_repo), kind="repo", name=deleted_repo.name
                )
                db.add(hidden_project)
                db.add(deleted_project)
                db.add(hidden_workspace)
                db.add(deleted_workspace)
                await db.flush()
                db.add(
                    CodingProjectWorkspace(
                        project_id=hidden_project.id,
                        workspace_id=hidden_workspace.id,
                    )
                )
                db.add(
                    CodingProjectWorkspace(
                        project_id=deleted_project.id,
                        workspace_id=deleted_workspace.id,
                    )
                )

        tree = TestClient(app_with_team).get("/api/team/workspace/tree")

        assert tree.status_code == 200
        body = tree.json()
        assert body["projects"] == []
        by_path = {repo["path"]: repo for repo in body["repositories"]}
        assert by_path[str(hidden_repo)]["project_id"] is None
        assert by_path[str(deleted_repo)]["project_id"] is None

    @pytest.mark.asyncio
    async def test_workspace_visibility_hides_all_workspace_sessions(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        workspace = str(tmp_path.resolve())
        first_id = uuid.uuid7()
        second_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(
                    db, first_id, mode="coding", workspace=workspace
                )
                await _create_team_session(
                    db, second_id, mode="coding", workspace=workspace
                )

        client = TestClient(app_with_team)
        resp = client.patch(
            "/api/team/workspace/visibility",
            json={"workspace": workspace, "hidden": True},
        )
        assert resp.status_code == 200
        assert resp.json() == {"workspace": workspace, "hidden": True}

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert tree.json()["repositories"] == []

    @pytest.mark.asyncio
    async def test_removed_workspace_can_be_reopened_as_standalone(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        repository = tmp_path / "reopen-repo"
        repository.mkdir()
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(
                    CodingWorkspace(
                        path=str(repository), kind="repo", name=repository.name
                    )
                )

        client = TestClient(app_with_team)
        removed = client.patch(
            "/api/team/workspace/visibility",
            json={"workspace": str(repository), "hidden": True},
        )
        assert removed.status_code == 200
        assert client.get("/api/team/workspace/tree").json()["repositories"] == []

        reopened = client.patch(
            "/api/team/workspace/visibility",
            json={"workspace": str(repository), "hidden": False},
        )

        assert reopened.status_code == 200
        tree = client.get("/api/team/workspace/tree").json()
        assert len(tree["repositories"]) == 1
        item = tree["repositories"][0]
        assert item["path"] == str(repository)
        assert item["name"] == repository.name
        assert item["worktrees"] == []
        assert item["project_id"] is None

    @pytest.mark.asyncio
    async def test_workspace_visibility_can_hide_missing_workspace(
        self, app_with_team, tmp_path
    ):
        import app.core.db as _db

        workspace = str((tmp_path / "missing-worktree").resolve())
        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(
                    db, lead_id, mode="coding", workspace=workspace
                )

        client = TestClient(app_with_team)
        resp = client.patch(
            "/api/team/workspace/visibility",
            json={"workspace": workspace, "hidden": True},
        )
        assert resp.status_code == 200
        assert resp.json() == {"workspace": workspace, "hidden": True}

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert tree.json()["repositories"] == []

    @pytest.mark.asyncio
    async def test_workspace_visibility_hides_owned_worktrees(
        self, app_with_team, tmp_path
    ):
        """Removing a repo must not leave a synthesized row for its worktrees."""
        import app.core.db as _db

        repo = tmp_path / "repo"
        worktree = tmp_path / "worktrees" / "task-a"
        repo.mkdir()
        worktree.mkdir(parents=True)
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(CodingWorkspace(path=str(repo), kind="repo", name="repo"))
                db.add(
                    CodingWorkspace(
                        path=str(worktree),
                        kind="worktree",
                        source_path=str(repo),
                        name="task-a",
                        managed=True,
                    )
                )

        client = TestClient(app_with_team)
        resp = client.patch(
            "/api/team/workspace/visibility",
            json={"workspace": str(repo), "hidden": True},
        )
        assert resp.status_code == 200

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert tree.json()["repositories"] == []


# ---------------------------------------------------------------------------
# DELETE /team/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestUpdateTeamSession:
    @pytest.mark.asyncio
    async def test_update_session_title(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, title="Old title")

        client = TestClient(app_with_team)
        resp = client.patch(
            f"/api/team/sessions/{lead_id}", json={"title": "New title"}
        )

        assert resp.status_code == 200
        assert resp.json()["title"] == "New title"

        async with _db.async_session_factory() as db:
            session = await db.get(ChatSession, lead_id)
            assert session is not None
            assert session.title == "New title"

    @pytest.mark.asyncio
    async def test_update_session_title_trims_whitespace(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, title="Old title")

        client = TestClient(app_with_team)
        resp = client.patch(
            f"/api/team/sessions/{lead_id}", json={"title": "  New title  "}
        )

        assert resp.status_code == 200
        assert resp.json()["title"] == "New title"

        async with _db.async_session_factory() as db:
            session = await db.get(ChatSession, lead_id)
            assert session is not None
            assert session.title == "New title"

    @pytest.mark.asyncio
    async def test_update_session_title_rejects_blank_title(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, title="Keep me")

        client = TestClient(app_with_team)
        resp = client.patch(f"/api/team/sessions/{lead_id}", json={"title": "   "})

        assert resp.status_code == 422
        assert resp.json()["detail"] == "Title cannot be empty."

        async with _db.async_session_factory() as db:
            session = await db.get(ChatSession, lead_id)
            assert session is not None
            assert session.title == "Keep me"

    @pytest.mark.asyncio
    async def test_update_session_title_does_not_update_member_sessions(
        self, app_with_team
    ):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, title="Lead")
                member = await _create_member_session(db, member_id, lead_id)
                member.title = "Member"

        client = TestClient(app_with_team)
        resp = client.patch(f"/api/team/sessions/{member_id}", json={"title": "Nope"})

        assert resp.status_code == 404

        async with _db.async_session_factory() as db:
            member = await db.get(ChatSession, member_id)
            assert member is not None
            assert member.title == "Member"

    def test_update_session_title_returns_404_for_missing_session(self, app_with_team):
        client = TestClient(app_with_team)

        resp = client.patch(f"/api/team/sessions/{uuid.uuid7()}", json={"title": "New"})

        assert resp.status_code == 404


class TestDuplicateTeamSession:
    @pytest.mark.asyncio
    async def test_duplicate_copies_chat_and_member_history(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(
                    db,
                    lead_id,
                    title="Investigate parser",
                    permission_mode="ask",
                    model="mock:model",
                    thinking_level="high",
                    tags=["review"],
                )
                await _create_member_session(
                    db, member_id, lead_id, agent_name="worker"
                )
                await _add_message(
                    db,
                    lead_id,
                    content="Find the bug",
                    extra={"nested": ["value"]},
                )
                await _add_message(
                    db,
                    member_id,
                    role="assistant",
                    content="Found it",
                )

        client = TestClient(app_with_team)
        resp = client.post(f"/api/team/sessions/{lead_id}/duplicate")

        assert resp.status_code == 201
        data = resp.json()
        copy_id = uuid.UUID(data["id"])
        assert copy_id != lead_id
        assert data["title"] == "Investigate parser (copy)"
        assert data["permission_mode"] == "ask"
        assert data["model"] == "mock:model"
        assert data["thinking_level"] == "high"
        assert data["tags"] == ["review"]
        assert data["running"] is False

        async with _db.async_session_factory() as db:
            child = (
                await db.exec(
                    select(ChatSession).where(
                        col(ChatSession.parent_session_id) == copy_id
                    )
                )
            ).one()
            assert child.agent_name == "worker"
            copied_messages = list(
                (
                    await db.exec(
                        select(SessionMessage)
                        .where(col(SessionMessage.session_id).in_([copy_id, child.id]))
                        .order_by(col(SessionMessage.created_at).asc())
                    )
                ).all()
            )
            assert [(message.role, message.content) for message in copied_messages] == [
                ("user", "Find the bug"),
                ("assistant", "Found it"),
            ]
            assert copied_messages[0].extra == {"nested": ["value"]}

    def test_duplicate_missing_session_returns_404(self, app_with_team):
        client = TestClient(app_with_team)

        resp = client.post(f"/api/team/sessions/{uuid.uuid7()}/duplicate")

        assert resp.status_code == 404


class TestDeleteTeamSessionWithData:
    @pytest.mark.asyncio
    async def test_delete_session_removes_session_and_messages(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(db, lead_id, role="user", content="delete me")

        client = TestClient(app_with_team)
        resp = client.delete(f"/api/team/sessions/{lead_id}")
        assert resp.status_code == 204

        # Me verify session is gone via history endpoint
        resp = client.get(f"/api/team/{lead_id}/history")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_coding_session_purges_app_workspace_dir(
        self, app_with_team, tmp_path, monkeypatch
    ):
        import app.core.db as _db
        from app.core.config import settings
        from app.core.paths import uploads_dir, workspace_dir

        monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path / "runs"))
        lead_id = uuid.uuid7()
        app_workspace = workspace_dir(str(lead_id))
        upload_root = uploads_dir(str(lead_id))
        upload_root.mkdir(parents=True)
        (upload_root / "attachment.txt").write_text("upload", encoding="utf-8")
        (app_workspace / "keep.txt").write_text("keep", encoding="utf-8")
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(
                    ChatSession(
                        id=lead_id,
                        agent_name="lead",
                        mode="coding",
                        workspace=str(tmp_path / "project"),
                    )
                )

        client = TestClient(app_with_team)
        resp = client.delete(f"/api/team/sessions/{lead_id}")

        assert resp.status_code == 204
        assert not app_workspace.exists()


# ---------------------------------------------------------------------------
# GET /team/{session_id}/history (lines 281-340)
# ---------------------------------------------------------------------------


class TestTeamHistoryWithData:
    @pytest.mark.asyncio
    async def test_history_returns_lead_and_members(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()

        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _create_member_session(
                    db, member_id, lead_id, agent_name="worker"
                )
                await _add_message(db, lead_id, role="user", content="lead msg")
                await _add_message(db, lead_id, role="assistant", content="lead reply")
                await _add_message(db, member_id, role="user", content="member input")
                await _add_message(
                    db, member_id, role="assistant", content="member reply"
                )

        client = TestClient(app_with_team)
        resp = client.get(f"/api/team/{lead_id}/history")
        assert resp.status_code == 200
        data = resp.json()

        # Me check lead messages
        assert "lead" in data
        assert len(data["lead"]["messages"]) >= 2

        # Me check members
        assert "members" in data
        assert len(data["members"]) >= 1
        member = data["members"][0]
        assert len(member["messages"]) >= 2
        assert member["name"] == "worker"

    @pytest.mark.asyncio
    async def test_history_paginates_one_global_lead_member_timeline(
        self, app_with_team
    ):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()
        base = datetime.now(timezone.utc) - timedelta(minutes=120)
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _create_member_session(
                    db, member_id, lead_id, agent_name="worker"
                )
                for index in range(520):
                    session_id = lead_id if index % 2 == 0 else member_id
                    await _add_message(
                        db,
                        session_id,
                        content=f"message-{index}",
                        created_at=base + timedelta(minutes=index),
                    )

        client = TestClient(app_with_team)
        first = client.get(f"/api/team/{lead_id}/history").json()
        first_messages = [
            *first["lead"]["messages"],
            *(message for member in first["members"] for message in member["messages"]),
        ]
        assert len(first_messages) == 500
        assert first["has_more"] is True
        second = client.get(
            f"/api/team/{lead_id}/history",
            params={"before": first["next_cursor"]},
        ).json()
        second_messages = [
            *second["lead"]["messages"],
            *(
                message
                for member in second["members"]
                for message in member["messages"]
            ),
        ]
        assert len(second_messages) == 20
        assert second["has_more"] is False
        contents = {
            message["content"] for message in [*first_messages, *second_messages]
        }
        assert contents == {f"message-{index}" for index in range(520)}

    @pytest.mark.asyncio
    async def test_history_cursor_keeps_rows_with_identical_timestamps(
        self, app_with_team
    ):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()
        timestamp = datetime.now(timezone.utc)
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _create_member_session(db, member_id, lead_id)
                for index in range(520):
                    await _add_message(
                        db,
                        lead_id if index % 2 == 0 else member_id,
                        content=f"tie-{index}",
                        created_at=timestamp,
                    )

        client = TestClient(app_with_team)
        first = client.get(f"/api/team/{lead_id}/history").json()
        second = client.get(
            f"/api/team/{lead_id}/history",
            params={"before": first["next_cursor"]},
        ).json()
        messages = [
            *first["lead"]["messages"],
            *(message for member in first["members"] for message in member["messages"]),
            *second["lead"]["messages"],
            *(
                message
                for member in second["members"]
                for message in member["messages"]
            ),
        ]
        assert len(messages) == 520
        assert {message["content"] for message in messages} == {
            f"tie-{index}" for index in range(520)
        }

    @pytest.mark.asyncio
    async def test_history_does_not_split_assistant_tool_cycle(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        base = datetime.now(timezone.utc) - timedelta(minutes=120)
        call_id = "call-page-boundary"
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(
                    db,
                    lead_id,
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ],
                    created_at=base,
                )
                await _add_message(
                    db,
                    lead_id,
                    role="tool",
                    content="result",
                    tool_call_id=call_id,
                    created_at=base + timedelta(seconds=1),
                )
                # The normal 500-row window would begin at the tool result and
                # strand its assistant call on the older page.
                for index in range(499):
                    await _add_message(
                        db,
                        lead_id,
                        content=f"later-{index}",
                        created_at=base + timedelta(seconds=index + 2),
                    )

        data = TestClient(app_with_team).get(f"/api/team/{lead_id}/history").json()

        messages = data["lead"]["messages"]
        assert len(messages) == 501
        assert [message["role"] for message in messages[:2]] == [
            "assistant",
            "tool",
        ]
        assert messages[0]["tool_calls"][0]["id"] == call_id
        assert messages[1]["tool_call_id"] == call_id
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_history_includes_summary_messages(self, app_with_team):
        """Summary rows (``is_summary=True``) must be returned by the history
        endpoint so the frontend can render the inline "Session compacted"
        divider — both at stream time and on subsequent page reloads.
        """
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(db, lead_id, role="user", content="visible")
                await _add_message(
                    db,
                    lead_id,
                    role="user",
                    content="compacted summary body",
                    is_summary=True,
                )

        client = TestClient(app_with_team)
        resp = client.get(f"/api/team/{lead_id}/history")
        data = resp.json()

        msgs = data["lead"]["messages"]
        contents = [m["content"] for m in msgs]
        assert "visible" in contents
        assert "compacted summary body" in contents
        summary_msg = next(m for m in msgs if m["content"] == "compacted summary body")
        assert summary_msg["is_summary"] is True

    @pytest.mark.asyncio
    async def test_history_excludes_reasoning_for_continuation_rows(
        self, app_with_team
    ):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(
                    db,
                    lead_id,
                    role="assistant",
                    content="continued answer",
                    reasoning_content="hidden thinking",
                    extra={"is_continuation": True},
                )

        client = TestClient(app_with_team)
        resp = client.get(f"/api/team/{lead_id}/history")
        data = resp.json()

        msg = data["lead"]["messages"][0]
        assert msg["content"] == "continued answer"
        assert "reasoning_content" not in msg
        assert msg["extra"] == {"is_continuation": True}

    @pytest.mark.asyncio
    async def test_history_excludes_hidden_from_user_rows(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(db, lead_id, role="user", content="visible")
                await _add_message(
                    db,
                    lead_id,
                    role="user",
                    content="hidden directive",
                    extra={"hidden_from_user": True},
                )

        client = TestClient(app_with_team)
        resp = client.get(f"/api/team/{lead_id}/history")
        data = resp.json()

        contents = [m["content"] for m in data["lead"]["messages"]]
        assert contents == ["visible"]

    @pytest.mark.asyncio
    async def test_history_no_sub_sessions_returns_empty_members(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _add_message(db, lead_id, role="user", content="solo")

        client = TestClient(app_with_team)
        resp = client.get(f"/api/team/{lead_id}/history")
        data = resp.json()

        assert data["members"] == []

    @pytest.mark.asyncio
    async def test_history_includes_durable_goal(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            await _create_team_session(db, lead_id)
            await db.commit()
            await goal_service.replace_goal(
                db,
                lead_id,
                "Implement and verify Goal mode",
                token_budget=50_000,
            )
            await goal_service.add_usage(db, lead_id, 1_250)
            await db.commit()

        client = TestClient(app_with_team)
        response = client.get(f"/api/team/{lead_id}/history")

        assert response.status_code == 200
        goal = response.json()["goal"]
        assert goal["objective"] == "Implement and verify Goal mode"
        assert goal["status"] == "active"
        assert goal["token_budget"] == 50_000
        assert goal["tokens_used"] == 1_250

    @pytest.mark.asyncio
    async def test_get_session_goal_returns_null_or_snapshot(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            await _create_team_session(db, lead_id)
            await db.commit()

        client = TestClient(app_with_team)
        empty = client.get(f"/api/team/{lead_id}/goal")
        assert empty.status_code == 200
        assert empty.json() is None

        async with _db.async_session_factory() as db:
            await goal_service.replace_goal(db, lead_id, "Finish")
            await db.commit()

        populated = client.get(f"/api/team/{lead_id}/goal")
        assert populated.status_code == 200
        assert populated.json()["objective"] == "Finish"


# ---------------------------------------------------------------------------
# GET /team/sessions — cursor pagination behaviour
# ---------------------------------------------------------------------------


class TestListTeamSessionsCursorPagination:
    """Verify cursor-based pagination semantics for GET /team/sessions."""

    @pytest.mark.asyncio
    async def test_response_shape(self, app_with_team):
        """Response always contains data, has_more, next_cursor."""
        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "has_more" in data
        assert "next_cursor" in data
        # Me legacy fields must NOT be present
        assert "total" not in data
        assert "offset" not in data

    @pytest.mark.asyncio
    async def test_first_page_no_cursor(self, app_with_team):
        """First page (no before=) returns newest sessions."""
        import app.core.db as _db

        ids = [uuid.uuid7() for _ in range(3)]
        async with _db.async_session_factory() as db:
            async with db.begin():
                for sid in ids:
                    await _create_team_session(db, sid)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) >= 1
        # Me sessions are newest-first (UUIDv7 monotonically increases)
        created_times = [s["created_at"] for s in data["data"] if s["created_at"]]
        assert created_times == sorted(created_times, reverse=True)

    @pytest.mark.asyncio
    async def test_has_more_false_when_all_fit(self, app_with_team):
        """has_more=False when result count < limit."""
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)

        client = TestClient(app_with_team)
        # Me limit=100 — far more than 1 session
        resp = client.get("/api/team/sessions?limit=100")
        data = resp.json()
        # has_more must be False when fewer rows than limit were returned
        assert len(data["data"]) < 100
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_has_more_true_and_cursor_set(self, app_with_team):
        """has_more=True and next_cursor is set when more rows exist."""
        import app.core.db as _db

        ids = [uuid.uuid7() for _ in range(5)]
        async with _db.async_session_factory() as db:
            async with db.begin():
                for sid in ids:
                    await _create_team_session(db, sid)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?limit=2")
        data = resp.json()
        # Me only valid when there are at least 3 sessions total
        if len(data["data"]) == 2 and data["has_more"]:
            assert data["next_cursor"] is not None

    @pytest.mark.asyncio
    async def test_cursor_advances_to_next_page(self, app_with_team):
        """Passing next_cursor as before= fetches the next page without overlap."""
        import app.core.db as _db

        # Me create 4 sessions so pagination is deterministic within this test
        ids = [uuid.uuid7() for _ in range(4)]
        async with _db.async_session_factory() as db:
            async with db.begin():
                for sid in ids:
                    await _create_team_session(db, sid)

        client = TestClient(app_with_team)

        # Page 1 — limit=2
        resp1 = client.get("/api/team/sessions?limit=2")
        assert resp1.status_code == 200
        page1 = resp1.json()
        ids_page1 = {s["id"] for s in page1["data"]}

        if not page1["has_more"]:
            pytest.skip("Not enough sessions for multi-page test")

        cursor = page1["next_cursor"]
        assert cursor is not None

        # Page 2 — use cursor
        resp2 = client.get(f"/api/team/sessions?limit=2&before={cursor}")
        assert resp2.status_code == 200
        page2 = resp2.json()
        ids_page2 = {s["id"] for s in page2["data"]}

        # Me no overlap between pages
        assert ids_page1.isdisjoint(ids_page2)

    @pytest.mark.asyncio
    async def test_invalid_before_returns_422(self, app_with_team):
        """Malformed before= cursor returns 422."""
        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?before=not-a-date")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_before_far_past_returns_empty(self, app_with_team):
        """before= in the distant past returns no sessions."""
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?before=2000-01-01T00:00:00Z")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_default_limit_is_20(self, app_with_team):
        """Default limit is 20."""
        import app.core.db as _db

        ids = [uuid.uuid7() for _ in range(25)]
        async with _db.async_session_factory() as db:
            async with db.begin():
                for sid in ids:
                    await _create_team_session(db, sid)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions")
        assert resp.status_code == 200
        data = resp.json()
        # Default page size is 20 — must not return more than 20
        assert len(data["data"]) <= 20

    @pytest.mark.asyncio
    async def test_limit_exceeding_max_rejected(self, app_with_team):
        """limit > 100 is rejected (422)."""
        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions?limit=101")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_member_sessions_excluded_from_list(self, app_with_team):
        """Member sessions (parent_session_id set) do not appear in the top-level list."""
        import app.core.db as _db

        lead_id = uuid.uuid7()
        member_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                await _create_member_session(db, member_id, lead_id)

        client = TestClient(app_with_team)
        resp = client.get("/api/team/sessions")
        data = resp.json()

        top_level_ids = {s["id"] for s in data["data"]}
        assert str(lead_id) in top_level_ids
        assert str(member_id) not in top_level_ids
