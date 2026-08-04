"""Sidebar session folders: CRUD, drag-and-drop moves, and folder-scoped resolve."""

from __future__ import annotations

import uuid

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
