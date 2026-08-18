from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.services.change_set_service import clear_change_sets

pytestmark = pytest.mark.usefixtures("setup_db")


@pytest.fixture
def client():
    from app.api.app import create_app
    from app.services.team_manager import set_team

    app = create_app()
    set_team(None)
    yield TestClient(app)
    set_team(None)


@pytest.fixture(autouse=True)
def _clear_change_set_store():
    clear_change_sets()
    yield
    clear_change_sets()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_create_preview_apply_and_reject_files(client, tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")

    response = client.post(
        "/api/team/workspace/change-sets",
        params={"workspace": str(tmp_path)},
        json={
            "origin": "ai",
            "title": "Update values",
            "files": [
                {
                    "path": "first.py",
                    "base_hash": _sha("first = 1\n"),
                    "document_version": 2,
                    "proposed_content": "first = 2\n",
                },
                {
                    "path": "second.py",
                    "base_hash": _sha("second = 1\n"),
                    "proposed_content": "second = 2\n",
                },
            ],
        },
    )

    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "pending"
    assert "+first = 2" in record["files"][0]["diff"]
    assert "proposed_content" not in record["files"][0]
    content_response = client.get(
        f"/api/team/workspace/change-sets/{record['id']}/files/first.py",
        params={"workspace": str(tmp_path)},
    )
    assert content_response.status_code == 200
    assert content_response.json()["original_content"] == "first = 1\n"
    assert content_response.json()["proposed_content"] == "first = 2\n"

    applied = client.post(
        f"/api/team/workspace/change-sets/{record['id']}/apply",
        params={"workspace": str(tmp_path)},
        json={"paths": ["first.py"]},
    )
    rejected = client.post(
        f"/api/team/workspace/change-sets/{record['id']}/reject",
        params={"workspace": str(tmp_path)},
        json={"paths": ["second.py"]},
    )

    assert applied.status_code == 200
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "partial"
    assert first.read_text(encoding="utf-8") == "first = 2\n"
    assert second.read_text(encoding="utf-8") == "second = 1\n"


def test_stale_apply_returns_conflict_without_partial_write(client, tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")
    created = client.post(
        "/api/team/workspace/change-sets",
        params={"workspace": str(tmp_path)},
        json={
            "origin": "lsp",
            "title": "Rename",
            "files": [
                {"path": "first.py", "proposed_content": "first = 2\n"},
                {"path": "second.py", "proposed_content": "second = 2\n"},
            ],
        },
    ).json()
    second.write_text("second = 3\n", encoding="utf-8")

    response = client.post(
        f"/api/team/workspace/change-sets/{created['id']}/apply",
        params={"workspace": str(tmp_path)},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stale_change_set",
        "paths": ["second.py"],
    }
    assert first.read_text(encoding="utf-8") == "first = 1\n"


def test_create_from_lsp_workspace_edit(client, tmp_path):
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")

    response = client.post(
        "/api/team/workspace/change-sets",
        params={"workspace": str(tmp_path)},
        json={
            "origin": "lsp",
            "title": "Rename value",
            "workspace_edit": {
                "documentChanges": [
                    {
                        "textDocument": {"uri": source.as_uri(), "version": 5},
                        "edits": [
                            {
                                "range": {
                                    "start": {"line": 0, "character": 0},
                                    "end": {"line": 0, "character": 5},
                                },
                                "newText": "renamed",
                            }
                        ],
                    }
                ]
            },
        },
    )

    assert response.status_code == 201
    file = response.json()["files"][0]
    assert file["document_version"] == 5
    assert "+renamed = 1" in file["diff"]
