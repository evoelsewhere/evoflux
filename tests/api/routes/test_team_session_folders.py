"""Sidebar session folders: CRUD, drag-and-drop moves, and folder-scoped resolve."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.models.chat import ChatSession


@pytest.fixture
def client():
    from app.api.app import create_app

    return TestClient(create_app())


async def _create_session(session_id, *, mode: str = "work", **kwargs) -> None:
    import app.core.db as _db

    async with _db.async_session_factory() as db:
        async with db.begin():
            db.add(ChatSession(id=session_id, mode=mode, **kwargs))


async def _session_row(session_id) -> ChatSession | None:
    import app.core.db as _db

    async with _db.async_session_factory() as db:
        return await db.get(ChatSession, session_id)


def _create_folder(client: TestClient, name: str = "Q3 launch", **body) -> dict:
    resp = client.post("/api/team/session-folders", json={"name": name, **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stub_team(monkeypatch):
    """A team whose provider is never reached, bound as the session's team."""
    from app.agent.agent_loop import Agent
    from app.agent.mode.team.member import TeamLead
    from app.agent.mode.team.team import AgentTeam
    from app.agent.providers.base import LLMProviderBase

    class _SilentProvider(LLMProviderBase):
        model = "mock"

        def stream(self, messages, tools=None, **kwargs):
            raise AssertionError("the team never runs in these tests")

        async def chat(self, messages, tools=None, **kwargs):
            raise AssertionError("the team never runs in these tests")

    team = AgentTeam(
        lead=TeamLead(
            Agent(name="lead", llm_provider=_SilentProvider(), system_prompt="Lead")
        )
    )

    async def fake_team(_session_id: str, **_kwargs):
        return team

    monkeypatch.setattr(
        "app.api.routes.team.chat.team_manager.get_or_start_team_for_session",
        fake_team,
    )
    return team


def _patch_dispatch(monkeypatch) -> AsyncMock:
    """Stub the team and its ingress so a chat POST reaches only the route."""
    _stub_team(monkeypatch)
    dispatch = AsyncMock(return_value=(str(uuid.uuid7()), 0))
    monkeypatch.setattr(
        "app.api.routes.team.chat.agent_service.dispatch_user_message", dispatch
    )
    return dispatch


class TestFolderCrud:
    def test_create_folder_defaults_to_work_mode_with_sharing_on(self, client):
        folder = _create_folder(client)

        assert folder["name"] == "Q3 launch"
        assert folder["mode"] == "work"
        assert folder["share_context"] is True
        assert folder["session_count"] == 0
        assert folder["sessions"] == []

    def test_create_folder_rejects_blank_name(self, client):
        assert (
            client.post("/api/team/session-folders", json={"name": "   "}).status_code
            == 422
        )

    def test_list_folders_is_scoped_by_mode_and_ordered(self, client):
        first = _create_folder(client, "First")
        second = _create_folder(client, "Second")
        _create_folder(client, "Coding one", mode="coding")

        work = client.get("/api/team/session-folders")
        assert work.status_code == 200
        assert [f["id"] for f in work.json()["folders"]] == [first["id"], second["id"]]

        coding = client.get("/api/team/session-folders", params={"mode": "coding"})
        assert [f["name"] for f in coding.json()["folders"]] == ["Coding one"]

    def test_rename_and_toggle_sharing(self, client):
        folder = _create_folder(client)

        resp = client.patch(
            f"/api/team/session-folders/{folder['id']}",
            json={"name": "Renamed", "share_context": False},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"
        assert resp.json()["share_context"] is False

    def test_update_unknown_folder_is_404(self, client):
        resp = client.patch(
            f"/api/team/session-folders/{uuid.uuid7()}", json={"name": "x"}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_folder_unfiles_sessions_instead_of_deleting_them(
        self, client
    ):
        folder = _create_folder(client)
        session_id = uuid.uuid7()
        await _create_session(session_id)
        assert (
            client.patch(
                f"/api/team/sessions/{session_id}/folder",
                json={"folder_id": folder["id"]},
            ).status_code
            == 200
        )

        assert (
            client.delete(f"/api/team/session-folders/{folder['id']}").status_code
            == 204
        )

        survivor = await _session_row(session_id)
        assert survivor is not None
        assert survivor.folder_id is None
        assert client.get("/api/team/session-folders").json()["folders"] == []


class TestSessionAssignment:
    @pytest.mark.asyncio
    async def test_move_session_into_folder_then_back_out(self, client):
        folder = _create_folder(client)
        session_id = uuid.uuid7()
        await _create_session(session_id)

        moved = client.patch(
            f"/api/team/sessions/{session_id}/folder",
            json={"folder_id": folder["id"]},
        )
        assert moved.status_code == 200
        assert moved.json()["folder_id"] == folder["id"]

        listed = client.get("/api/team/session-folders").json()["folders"][0]
        assert listed["session_count"] == 1
        assert [s["id"] for s in listed["sessions"]] == [str(session_id)]

        unfiled = client.patch(
            f"/api/team/sessions/{session_id}/folder", json={"folder_id": None}
        )
        assert unfiled.status_code == 200
        assert unfiled.json().get("folder_id") is None
        assert (
            client.get("/api/team/session-folders").json()["folders"][0]["sessions"]
            == []
        )

    @pytest.mark.asyncio
    async def test_move_rejects_folder_from_another_mode(self, client):
        coding_folder = _create_folder(client, "Coding", mode="coding")
        session_id = uuid.uuid7()
        await _create_session(session_id, mode="work")

        resp = client.patch(
            f"/api/team/sessions/{session_id}/folder",
            json={"folder_id": coding_folder["id"]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_move_to_unknown_folder_is_404(self, client):
        session_id = uuid.uuid7()
        await _create_session(session_id)

        resp = client.patch(
            f"/api/team/sessions/{session_id}/folder",
            json={"folder_id": str(uuid.uuid7())},
        )
        assert resp.status_code == 404

    def test_move_unknown_session_is_404(self, client):
        folder = _create_folder(client)
        resp = client.patch(
            f"/api/team/sessions/{uuid.uuid7()}/folder",
            json={"folder_id": folder["id"]},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_large_folder_can_page_through_every_session(self, client):
        folder = _create_folder(client)
        session_ids = [uuid.uuid7() for _ in range(45)]
        for session_id in session_ids:
            await _create_session(session_id, folder_id=uuid.UUID(folder["id"]))

        listed = client.get("/api/team/session-folders").json()["folders"][0]
        assert listed["session_count"] == 45
        assert len(listed["sessions"]) == 40
        assert listed["has_more"] is True
        assert listed["next_cursor"]

        older = client.get(
            f"/api/team/session-folders/{folder['id']}/sessions",
            params={"before": listed["next_cursor"]},
        )
        assert older.status_code == 200, older.text
        assert len(older.json()["data"]) == 5
        assert older.json()["has_more"] is False

    def test_folder_page_validates_folder_and_cursor(self, client):
        missing = client.get(f"/api/team/session-folders/{uuid.uuid7()}/sessions")
        assert missing.status_code == 404

        folder = _create_folder(client)
        invalid = client.get(
            f"/api/team/session-folders/{folder['id']}/sessions",
            params={"before": "not-a-date"},
        )
        assert invalid.status_code == 422


class TestResolveInFolder:
    def test_new_chat_in_folder_is_filed_on_creation(self, client):
        folder = _create_folder(client)

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True, "folder_id": folder["id"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] is True
        assert resp.json()["folder_id"] == folder["id"]

    def test_resolve_reuse_is_scoped_to_the_folder(self, client):
        folder = _create_folder(client)
        unfiled = client.post(
            "/api/team/sessions/resolve", json={"mode": "work", "create": True}
        ).json()

        in_folder = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "folder_id": folder["id"]},
        ).json()
        assert in_folder["created"] is True
        assert in_folder["id"] != unfiled["id"]

        again = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "folder_id": folder["id"]},
        ).json()
        assert again["created"] is False
        assert again["id"] == in_folder["id"]

    def test_resolve_with_unknown_folder_is_404(self, client):
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True, "folder_id": str(uuid.uuid7())},
        )
        assert resp.status_code == 404

    def test_resolve_rejects_folder_from_another_mode(self, client):
        coding_folder = _create_folder(client, "Coding", mode="coding")
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True, "folder_id": coding_folder["id"]},
        )
        assert resp.status_code == 422


class TestDraftChatPlacement:
    """A new chat is a draft until its first message; the folder rides along.

    Nothing is created while the user is still deciding, so the two halves are
    tested apart: ``existing_only`` looks without writing, and POST /team/chat
    carries the folder into the session that message brings into being.
    """

    def test_existing_only_returns_null_instead_of_creating(self, client):
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "existing_only": True},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() is None
        listed = client.get("/api/team/sessions").json()
        assert listed["data"] == []

    def test_existing_only_returns_the_session_already_in_the_folder(self, client):
        folder = _create_folder(client)
        created = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True, "folder_id": folder["id"]},
        ).json()

        found = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "existing_only": True, "folder_id": folder["id"]},
        ).json()

        assert found["id"] == created["id"]
        assert found["created"] is False

    def test_existing_only_is_folder_scoped(self, client):
        folder = _create_folder(client)
        client.post("/api/team/sessions/resolve", json={"mode": "work", "create": True})

        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "existing_only": True, "folder_id": folder["id"]},
        )

        assert resp.json() is None

    def test_existing_only_and_create_are_mutually_exclusive(self, client):
        resp = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "work", "create": True, "existing_only": True},
        )
        assert resp.status_code == 422

    def test_chat_files_the_session_it_creates_into_the_folder(
        self, client, monkeypatch
    ):
        folder = _create_folder(client)
        dispatched = _patch_dispatch(monkeypatch)

        resp = client.post(
            "/api/team/chat",
            data={"message": "first words", "folder_id": folder["id"]},
        )

        assert resp.status_code == 202, resp.text
        assert str(dispatched.await_args.kwargs["folder_id"]) == folder["id"]

    def test_chat_ignores_a_folder_for_a_session_that_already_exists(
        self, client, monkeypatch
    ):
        import asyncio

        folder = _create_folder(client)
        session_id = uuid.uuid7()
        asyncio.run(_create_session(session_id, agent_name="lead"))
        dispatched = _patch_dispatch(monkeypatch)

        resp = client.post(
            "/api/team/chat",
            data={
                "message": "more words",
                "session_id": str(session_id),
                "folder_id": folder["id"],
            },
        )

        assert resp.status_code == 202, resp.text
        assert dispatched.await_args.kwargs["folder_id"] is None

    def test_chat_rejects_an_unknown_folder(self, client, monkeypatch):
        _patch_dispatch(monkeypatch)

        resp = client.post(
            "/api/team/chat",
            data={"message": "hello", "folder_id": str(uuid.uuid7())},
        )

        assert resp.status_code == 404

    def test_chat_rejects_a_folder_from_another_mode(self, client, monkeypatch):
        coding_folder = _create_folder(client, "Coding", mode="coding")
        _patch_dispatch(monkeypatch)

        resp = client.post(
            "/api/team/chat",
            data={"message": "hello", "folder_id": coding_folder["id"]},
        )

        assert resp.status_code == 422

    def test_prepare_user_session_files_the_new_row_in_the_folder(
        self, client, monkeypatch
    ):
        """The end of the road: the row the first message creates lands filed.

        The route only forwards the folder; ``prepare_user_session`` is what
        writes it, so this covers the half a stubbed dispatch cannot.
        """
        import asyncio

        folder = _create_folder(client)
        session_id = uuid.uuid7()
        team = _stub_team(monkeypatch)

        asyncio.run(
            team.prepare_user_session(
                content="first words",
                session_id=str(session_id),
                mode="work",
                folder_id=uuid.UUID(folder["id"]),
            )
        )

        row = asyncio.run(_session_row(session_id))
        assert row is not None
        assert str(row.folder_id) == folder["id"]
        assert row.title == "first words"
