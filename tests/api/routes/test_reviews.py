from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_create_connection_keeps_token_out_of_api_response(
    tmp_path,
    monkeypatch,
):
    from app.api.app import create_app

    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app())

    response = client.post(
        "/api/team/reviews/connections",
        json={
            "name": "GitHub",
            "provider": "github",
            "domain": "github.com",
            "scope": "server",
            "workspace_id": None,
            "token": "github-secret",
            "verify_ssl": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["domain"] == "https://github.com"
    assert payload["base_url"] == "https://api.github.com"
    assert payload["token_url"] == "https://github.com/settings/tokens/new"
    assert payload["host"] == "github.com"
    assert payload["has_token"] is True
    assert "token" not in payload
    assert "github-secret" not in response.text
    assert "github-secret" in (tmp_path / ".env").read_text()

    changed_domain = client.put(
        f"/api/team/reviews/connections/{payload['id']}",
        json={"domain": "github.example.com"},
    )
    assert changed_domain.status_code == 422
    assert "new access token" in changed_domain.json()["detail"]

    listed = client.get("/api/team/reviews/connections")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "github-secret" not in listed.text


def test_create_connection_rejects_invalid_domain(tmp_path, monkeypatch):
    from app.api.app import create_app

    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    response = TestClient(create_app()).post(
        "/api/team/reviews/connections",
        json={
            "name": "Unsafe",
            "provider": "gitlab",
            "domain": "https://oauth2:secret@gitlab.example.com",
            "scope": "server",
            "token": "gitlab-secret",
            "verify_ssl": True,
        },
    )

    assert response.status_code == 422
    assert "without credentials" in response.json()["detail"]
    assert "secret" not in response.text


def test_repository_connection_requires_workspace(tmp_path, monkeypatch):
    from app.api.app import create_app

    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app())

    response = client.post(
        "/api/team/reviews/connections",
        json={
            "name": "Repo key",
            "provider": "gitlab",
            "base_url": "https://gitlab.example.com/api/v4",
            "scope": "repository",
            "workspace_id": None,
            "token": "gitlab-secret",
            "verify_ssl": True,
        },
    )

    assert response.status_code == 422
    assert "require a workspace" in response.json()["detail"]


def test_review_scope_rejects_workspace_and_project():
    from app.api.app import create_app

    client = TestClient(create_app())
    response = client.get(
        "/api/team/reviews",
        params={"workspace": "/repo", "project_id": str(uuid4())},
    )

    assert response.status_code == 422
    assert "workspace or project" in response.json()["detail"]


@pytest.mark.asyncio
async def test_project_scope_returns_only_project_repositories(tmp_path):
    from app.api.app import create_app
    from app.core import db as db_module
    from app.models.chat import (
        CodingProject,
        CodingProjectWorkspace,
        CodingWorkspace,
    )

    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    standalone_path = tmp_path / "standalone"
    first_path.mkdir()
    second_path.mkdir()
    standalone_path.mkdir()
    project = CodingProject(name="Product")
    first = CodingWorkspace(path=str(first_path), kind="repo", name="first")
    second = CodingWorkspace(path=str(second_path), kind="repo", name="second")
    standalone = CodingWorkspace(
        path=str(standalone_path),
        kind="repo",
        name="standalone",
    )
    async with db_module.async_session_factory() as db:
        async with db.begin():
            db.add(project)
            db.add(first)
            db.add(second)
            db.add(standalone)
            await db.flush()
            db.add(
                CodingProjectWorkspace(
                    project_id=project.id,
                    workspace_id=first.id,
                )
            )
            db.add(
                CodingProjectWorkspace(
                    project_id=project.id,
                    workspace_id=second.id,
                )
            )

    response = TestClient(create_app()).get(
        "/api/team/reviews",
        params={"project_id": str(project.id)},
    )

    assert response.status_code == 200
    assert {
        repository["workspace_id"]
        for repository in response.json()["repositories"]
    } == {str(first.id), str(second.id)}


@pytest.mark.asyncio
async def test_worktree_scope_resolves_to_source_repository(tmp_path):
    from app.api.app import create_app
    from app.core import db as db_module
    from app.models.chat import CodingWorkspace

    repo_path = tmp_path / "repo"
    worktree_path = tmp_path / "worktree"
    repo_path.mkdir()
    worktree_path.mkdir()
    repository = CodingWorkspace(path=str(repo_path), kind="repo", name="repo")
    worktree = CodingWorkspace(
        path=str(worktree_path),
        kind="worktree",
        source_path=str(repo_path),
        name="feature",
    )
    async with db_module.async_session_factory() as db:
        async with db.begin():
            db.add(repository)
            db.add(worktree)

    response = TestClient(create_app()).get(
        "/api/team/reviews",
        params={"workspace": str(worktree_path)},
    )

    assert response.status_code == 200
    assert [
        item["workspace_id"] for item in response.json()["repositories"]
    ] == [str(repository.id)]


@pytest.mark.asyncio
async def test_review_action_api_uses_saved_connection(monkeypatch, tmp_path):
    from app.api.app import create_app
    from app.api.routes.team import reviews as routes
    from app.core import db as db_module
    from app.models.chat import CodingWorkspace, GitServerConnection
    from app.services.code_review_service import RepositoryTarget

    workspace_path = tmp_path / "repo"
    workspace_path.mkdir()
    workspace = CodingWorkspace(
        path=str(workspace_path),
        kind="repo",
        name="repo",
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="TEST_REVIEW_ACTION_TOKEN",
    )
    async with db_module.async_session_factory() as db:
        async with db.begin():
            db.add(workspace)
            db.add(connection)

    async def fake_inspect(workspace_id, path, name):
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=path,
            name=name,
            remote_url="git@github.com:acme/repo.git",
            host="github.com",
            repository="acme/repo",
            detected_provider="github",
        )

    seen = {}

    async def fake_comment(
        target,
        selected_connection,
        number,
        body,
        *,
        idempotency_key=None,
    ):
        seen.update(
            repository=target.repository,
            connection=selected_connection.name,
            number=number,
            body=body,
            idempotency_key=idempotency_key,
        )
        return {"action": "comment", "id": 7}

    monkeypatch.setattr(routes, "inspect_repository", fake_inspect)
    monkeypatch.setattr(routes, "add_code_review_comment", fake_comment)
    response = TestClient(create_app()).post(
        f"/api/team/reviews/{workspace.id}/12/actions",
        json={
            "action": "comment",
            "body": "Looks good",
            "idempotency_key": "call-12",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "comment"
    assert seen == {
        "repository": "acme/repo",
        "connection": "GitHub",
        "number": 12,
        "body": "Looks good",
        "idempotency_key": "call-12",
    }
