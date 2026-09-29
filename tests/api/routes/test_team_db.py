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


async def _project_owning(db, *workspaces, name="Project"):
    """A live Coding project with *workspaces* (repo rows) as its members."""
    project = CodingProject(name=name)
    db.add(project)
    for workspace in workspaces:
        db.add(workspace)
    await db.flush()
    for workspace in workspaces:
        db.add(CodingProjectWorkspace(project_id=project.id, workspace_id=workspace.id))
    return project


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

    @pytest.mark.asyncio
    async def test_resolve_creates_coding_session(self, app_with_team, tmp_path):
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Owner", workspace_paths=[str(tmp_path)]
            )
            await db.commit()
            project_id = project.id
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
        assert data["project_id"] == str(project_id)

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert [
            (repo["path"], repo["project_id"]) for repo in tree.json()["repositories"]
        ] == [(str(tmp_path.resolve()), str(project_id))]

    @pytest.mark.asyncio
    async def test_resolve_workspace_in_no_project_is_refused(
        self, app_with_team, tmp_path
    ):
        """Coding is project-only: a bare folder no project owns opens nothing
        and leaves neither a session nor a registry row behind."""
        import app.core.db as _db

        repo = tmp_path / "loose"
        repo.mkdir()
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": str(repo), "create": True},
        )

        assert resp.status_code == 422
        assert "belong to a project" in resp.json()["detail"]
        async with _db.async_session_factory() as db:
            sessions = (
                await db.exec(select(ChatSession).where(ChatSession.mode == "coding"))
            ).all()
            registered = (await db.exec(select(CodingWorkspace))).all()
        assert sessions == []
        assert registered == []
        assert client.get("/api/team/workspace/tree").json()["repositories"] == []

    @pytest.mark.asyncio
    async def test_resolve_deleted_project_says_it_was_deleted(
        self, app_with_team, tmp_path
    ):
        """A link to a deleted project is not one with no repositories left."""
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        repo = tmp_path / "repo"
        repo.mkdir()
        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Soon gone", workspace_paths=[str(repo)]
            )
            await db.commit()
            project_id = project.id
        client = TestClient(app_with_team)
        assert client.delete(f"/api/team/projects/{project_id}").status_code == 204

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "project_id": str(project_id)},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "This project was deleted."

    @pytest.mark.asyncio
    async def test_resolve_project_with_a_foreign_workspace_is_refused(
        self, app_with_team, tmp_path
    ):
        """A workspace named with a project must be one of its repositories."""
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        member = tmp_path / "member"
        stranger = tmp_path / "stranger"
        member.mkdir()
        stranger.mkdir()
        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Owner", workspace_paths=[str(member)]
            )
            await db.commit()
            project_id = project.id
        client = TestClient(app_with_team)

        refused = client.post(
            "/api/team/sessions/resolve",
            json={
                "mode": "coding",
                "project_id": str(project_id),
                "workspace": str(stranger),
            },
        )
        accepted = client.post(
            "/api/team/sessions/resolve",
            json={
                "mode": "coding",
                "project_id": str(project_id),
                "workspace": str(member),
            },
        )

        assert refused.status_code == 422
        assert "not a repository of this project" in refused.json()["detail"]
        assert accepted.status_code == 200
        assert accepted.json()["project_id"] == str(project_id)

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
                project = await _project_owning(
                    db, CodingWorkspace(path=str(repo), kind="repo", name="repo")
                )
                project_id = project.id
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
        # A worktree inherits its source repo's project.
        assert resp.json()["project_id"] == str(project_id)

        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        repos = tree.json()["repositories"]
        assert len(repos) == 1 and repos[0]["workspace_id"]
        assert {k: v for k, v in repos[0].items() if k != "workspace_id"} == {
            "path": str(repo),
            "name": "repo",
            "worktrees": [{"path": str(worktree), "name": "task-a", "managed": True}],
            "project_id": str(project_id),
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
                project = await _project_owning(
                    db, CodingWorkspace(path=str(repo), kind="repo", name="repo")
                )
                project_id = project.id
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
            "project_id": str(project_id),
        }

    @pytest.mark.asyncio
    async def test_workspace_tree_omits_repos_and_worktrees_in_no_project(
        self, app_with_team, tmp_path
    ):
        """Coding opens repos only through a project: a repo in none — and a
        worktree whose source repo is hidden or in none — is not listed, and
        no entry is synthesized for such a source."""
        import app.core.db as _db

        loose = tmp_path / "loose"
        loose_worktree = tmp_path / "worktrees" / "loose-task"
        hidden_repo = tmp_path / "hidden-repo"
        hidden_worktree = tmp_path / "worktrees" / "hidden-task"
        for path in (loose, loose_worktree, hidden_repo, hidden_worktree):
            path.mkdir(parents=True)
        async with _db.async_session_factory() as db:
            async with db.begin():
                db.add(CodingWorkspace(path=str(loose), kind="repo", name="loose"))
                db.add(
                    CodingWorkspace(
                        path=str(loose_worktree),
                        kind="worktree",
                        source_path=str(loose),
                        name="loose-task",
                        managed=True,
                    )
                )
                db.add(
                    CodingWorkspace(
                        path=str(hidden_repo),
                        kind="repo",
                        name="hidden-repo",
                        hidden=True,
                    )
                )
                db.add(
                    CodingWorkspace(
                        path=str(hidden_worktree),
                        kind="worktree",
                        source_path=str(hidden_repo),
                        name="hidden-task",
                        managed=True,
                    )
                )

        client = TestClient(app_with_team)
        tree = client.get("/api/team/workspace/tree")
        assert tree.status_code == 200
        assert tree.json()["repositories"] == []

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
        # A registered repo in no project is not part of the Coding tree.
        assert str(standalone) not in by_path
        assert [p["id"] for p in body["projects"]] == [str(project_id)]

    @pytest.mark.asyncio
    async def test_workspace_tree_ignores_memberships_to_invisible_projects(
        self, app_with_team, tmp_path
    ):
        """Only live Coding projects own tree placement: a repository whose
        only project is hidden or soft-deleted is not listed at all."""
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
        assert body["repositories"] == []

    def test_workspace_visibility_endpoint_is_gone(self, app_with_team, tmp_path):
        """Standalone workspaces no longer exist, so neither does their
        hide/reopen endpoint."""
        resp = TestClient(app_with_team).patch(
            "/api/team/workspace/visibility",
            json={"workspace": str(tmp_path), "hidden": True},
        )
        assert resp.status_code in (404, 405)


class TestChatBindsNewCodingSessionToProject:
    """A Coding chat started from a draft is created by its first message.

    The sidebar looks the draft up with ``existing_only``, which finds no
    session, so ``POST /team/chat`` is the call that brings the session into
    being. Coding is project-only: that session belongs to the project owning
    the repository, and a folder no project owns is refused before anything
    is created or registered.
    """

    @pytest.fixture
    def dispatched(self, app_with_team, test_team, monkeypatch):
        from unittest.mock import AsyncMock

        async def fake_coding_team(*_args, **_kwargs):
            return test_team

        monkeypatch.setattr(
            "app.api.routes.team.chat.team_manager.get_or_start_coding_team",
            fake_coding_team,
        )
        dispatch = AsyncMock(return_value=(str(uuid.uuid7()), 0))
        monkeypatch.setattr(
            "app.api.routes.team.chat.agent_service.dispatch_user_message", dispatch
        )
        return dispatch

    @staticmethod
    async def _project_with(*repos):
        import app.core.db as _db
        from app.services.coding_project_service import create_project

        async with _db.async_session_factory() as db:
            project = await create_project(
                db, name="Owner", workspace_paths=[str(repo) for repo in repos]
            )
            await db.commit()
            return project.id

    @pytest.mark.asyncio
    async def test_first_message_creates_the_session_under_the_owning_project(
        self, app_with_team, dispatched, tmp_path
    ):
        repo = tmp_path / "cloned-repo"
        repo.mkdir()
        project_id = await self._project_with(repo)
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/chat",
            data={"message": "hello", "mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 202, resp.text
        assert dispatched.await_args.kwargs["project_id"] == project_id
        tree = client.get("/api/team/workspace/tree")
        assert [(r["path"], r["project_id"]) for r in tree.json()["repositories"]] == [
            (str(repo.resolve()), str(project_id))
        ]

    @pytest.mark.asyncio
    async def test_explicit_project_must_own_the_workspace(
        self, app_with_team, dispatched, tmp_path
    ):
        member = tmp_path / "member"
        outsider = tmp_path / "outsider"
        member.mkdir()
        outsider.mkdir()
        project_id = await self._project_with(member)
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/chat",
            data={
                "message": "hello",
                "mode": "coding",
                "workspace": str(outsider),
                "project_id": str(project_id),
            },
        )

        assert resp.status_code == 422, resp.text
        assert "not a repository of this project" in resp.json()["detail"]
        dispatched.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejected_message_creates_nothing(
        self, app_with_team, dispatched, tmp_path
    ):
        """A request that never creates a session dispatches nothing."""
        repo = tmp_path / "untouched"
        repo.mkdir()
        await self._project_with(repo)
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/chat",
            data={"message": "/loop go", "mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 410, resp.text
        dispatched.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_first_message_on_a_folder_in_no_project_is_refused(
        self, app_with_team, dispatched, tmp_path
    ):
        """No standalone workspace: nothing is dispatched or registered."""
        import app.core.db as _db

        repo = tmp_path / "loose"
        repo.mkdir()
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/chat",
            data={"message": "hello", "mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 422, resp.text
        assert "belong to a project" in resp.json()["detail"]
        dispatched.assert_not_awaited()
        async with _db.async_session_factory() as db:
            assert (await db.exec(select(CodingWorkspace))).all() == []
        assert client.get("/api/team/workspace/tree").json()["repositories"] == []

    @pytest.mark.asyncio
    async def test_first_message_on_a_repo_shared_by_projects_conflicts(
        self, app_with_team, dispatched, tmp_path
    ):
        repo = tmp_path / "shared"
        repo.mkdir()
        await self._project_with(repo)
        await self._project_with(repo)
        client = TestClient(app_with_team)

        resp = client.post(
            "/api/team/chat",
            data={"message": "hello", "mode": "coding", "workspace": str(repo)},
        )

        assert resp.status_code == 409, resp.text
        assert "multiple projects" in resp.json()["detail"]
        dispatched.assert_not_awaited()


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
        page = client.get(f"/api/team/{lead_id}/history").json()
        pages = 0
        messages = []
        while True:
            pages += 1
            messages.extend(page["lead"]["messages"])
            messages.extend(
                message for member in page["members"] for message in member["messages"]
            )
            if not page["has_more"]:
                break
            page = client.get(
                f"/api/team/{lead_id}/history",
                params={"before": page["next_cursor"]},
            ).json()

        assert pages > 2
        assert len(messages) == 520
        contents = {message["content"] for message in messages}
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
        page = client.get(f"/api/team/{lead_id}/history").json()
        messages = []
        while True:
            messages.extend(page["lead"]["messages"])
            messages.extend(
                message for member in page["members"] for message in member["messages"]
            )
            if not page["has_more"]:
                break
            page = client.get(
                f"/api/team/{lead_id}/history",
                params={"before": page["next_cursor"]},
            ).json()
        assert len(messages) == 520
        assert {message["content"] for message in messages} == {
            f"tie-{index}" for index in range(520)
        }

    @pytest.mark.asyncio
    async def test_history_page_is_bounded_by_payload_weight(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id)
                for index in range(80):
                    await _add_message(
                        db,
                        lead_id,
                        role="tool",
                        content=f"tool-{index}:" + ("x" * 12_000),
                    )

        response = TestClient(app_with_team).get(f"/api/team/{lead_id}/history")
        data = response.json()

        assert response.status_code == 200
        assert len(response.content) < 400_000
        assert len(data["lead"]["messages"]) < 80
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

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
                    role="user",
                    content="run the tool",
                    created_at=base - timedelta(seconds=1),
                )
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
                # The normal 160-row window would begin at the tool result and
                # strand its assistant call on the older page.
                for index in range(159):
                    await _add_message(
                        db,
                        lead_id,
                        content=f"later-{index}",
                        created_at=base + timedelta(seconds=index + 2),
                    )

        data = TestClient(app_with_team).get(f"/api/team/{lead_id}/history").json()

        messages = data["lead"]["messages"]
        assert len(messages) == 162
        assert [message["role"] for message in messages[:3]] == [
            "user",
            "assistant",
            "tool",
        ]
        assert messages[1]["tool_calls"][0]["id"] == call_id
        assert messages[2]["tool_call_id"] == call_id
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


class TestPermissionModeEndpoint:
    """PATCH /team/sessions/{id}/permission-mode — previously untested.

    The gap mattered: the route is the only way a persisted session changes
    its guard rails, and a client that fails to reach it leaves the badge
    claiming a protection the run is not applying.
    """

    @pytest.mark.asyncio
    async def test_patch_persists_the_new_mode(self, app_with_team):
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, permission_mode="auto")

        client = TestClient(app_with_team)
        response = client.patch(
            f"/api/team/sessions/{lead_id}/permission-mode",
            json={"mode": "ask"},
        )

        assert response.status_code == 200
        metadata = client.get(f"/api/team/sessions/{lead_id}/metadata").json()
        assert metadata["permission_mode"] == "ask"

    @pytest.mark.asyncio
    async def test_patch_refuses_a_mode_the_server_does_not_have(self, app_with_team):
        """422, not a silent downgrade to the permissive default."""
        import app.core.db as _db

        lead_id = uuid.uuid7()
        async with _db.async_session_factory() as db:
            async with db.begin():
                await _create_team_session(db, lead_id, permission_mode="ask")

        client = TestClient(app_with_team)
        response = client.patch(
            f"/api/team/sessions/{lead_id}/permission-mode",
            json={"mode": "yolo"},
        )

        assert response.status_code == 422
        metadata = client.get(f"/api/team/sessions/{lead_id}/metadata").json()
        assert metadata["permission_mode"] == "ask"

    @pytest.mark.asyncio
    async def test_patch_on_a_missing_session_is_404(self, app_with_team):
        response = TestClient(app_with_team).patch(
            f"/api/team/sessions/{uuid.uuid7()}/permission-mode",
            json={"mode": "ask"},
        )

        assert response.status_code == 404


class TestPermissionModeOnSessionCreation:
    """The mode picked before the first message must survive into the row.

    A new chat is a draft until the first send, so there is no row to PATCH.
    The pick used to be dropped on the floor: the row took the column default,
    the badge kept showing what the user chose, and a session set to "Ask
    permissions" ran its first turn approving everything.
    """

    def test_validator_accepts_every_mode_the_picker_offers(self):
        from app.api.routes.team.chat import (
            _VALID_PERMISSION_MODES,
            _validated_permission_mode,
        )

        for mode in _VALID_PERMISSION_MODES:
            assert _validated_permission_mode(mode) == mode

    def test_validator_defaults_when_the_client_sends_nothing(self):
        from app.api.routes.team.chat import (
            DEFAULT_PERMISSION_MODE,
            _validated_permission_mode,
        )
        from app.models.chat import ChatSession

        assert _validated_permission_mode(None) == DEFAULT_PERMISSION_MODE
        # And the default agrees with the column, so an older client that
        # omits the field lands where the database would have put it anyway.
        assert ChatSession().permission_mode == DEFAULT_PERMISSION_MODE

    def test_validator_rejects_an_unknown_mode(self):
        from fastapi import HTTPException

        from app.api.routes.team.chat import _validated_permission_mode

        with pytest.raises(HTTPException) as excinfo:
            _validated_permission_mode("yolo")
        assert excinfo.value.status_code == 422

    def test_chat_form_carries_the_mode(self):
        import inspect

        from app.api.schemas.chat import ChatForm

        assert ChatForm(message="hi", permission_mode="ask").permission_mode == "ask"
        assert ChatForm(message="hi").permission_mode is None
        # The multipart form is the wire the client actually uses, so the
        # field has to be declared there too, not only on the model.
        assert "permission_mode" in inspect.signature(ChatForm.as_form).parameters
