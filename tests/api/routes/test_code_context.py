"""HTTP contract tests for the dependency-free code-context runtime."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.code_context import router
from app.api.routes.team.projects import _graph_node_id, router as project_router
from app.core.config import settings
from app.services.code_index.project import RepositoryIndexRegistry


@pytest.fixture
def code_context_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, Path]:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "payments.py").write_text(
        "def settle_payment():\n    return 'payment accepted'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    registry = RepositoryIndexRegistry()
    monkeypatch.setattr(
        "app.api.routes.code_context.repository_indexes",
        registry,
    )
    monkeypatch.setattr(
        "app.services.code_index.service.repository_indexes",
        registry,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/code-context")
    return TestClient(app), repository


def test_status_index_and_query_share_repository_target(
    code_context_client: tuple[TestClient, Path],
) -> None:
    client, repository = code_context_client
    params = {"workspace": str(repository)}

    assert (
        client.get("/api/code-context/status", params=params).json()["indexed"] is False
    )

    indexed = client.post(
        "/api/code-context/index",
        params=params,
        json={"full": False},
    )
    assert indexed.status_code == 200
    assert indexed.json()["files"] == 1
    assert indexed.json()["graph_languages"] == ["python"]
    assert indexed.json()["index_error"] is None

    response = client.post(
        "/api/code-context/query",
        params=params,
        json={
            "action": "search",
            "query": "payment accepted",
            "refresh": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hits"][0]["file_path"] == "payments.py"
    assert body["hits"][0]["repository_path"] == str(repository)
    assert body["strategy"] == "code-index-vector-fts5-cross-repo"

    graph = client.get("/api/code-context/graph-data", params=params)
    assert graph.status_code == 200
    graph_body = graph.json()
    assert graph_body["repos"][0]["path"] == str(repository)
    assert graph_body["nodes"]
    assert graph_body["total_node_count"] >= len(graph_body["nodes"])


def test_graph_action_rejects_prose_at_http_boundary(
    code_context_client: tuple[TestClient, Path],
) -> None:
    client, repository = code_context_client
    response = client.post(
        "/api/code-context/query",
        params={"workspace": str(repository)},
        json={"action": "callers", "query": "who calls settle payment"},
    )

    assert response.status_code == 422
    assert "one exact symbol" in response.json()["detail"]


def test_graph_openapi_retains_object_response_schema(
    code_context_client: tuple[TestClient, Path],
) -> None:
    client, _repository = code_context_client

    schema = client.get("/openapi.json").json()["paths"][
        "/api/code-context/graph-data"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert "additionalProperties" in schema

    project_app = FastAPI()
    project_app.include_router(project_router, prefix="/api/team")
    project_schema = project_app.openapi()["paths"][
        "/api/team/projects/{project_id}/code-context/graph-data"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert project_schema["type"] == "object"
    assert "additionalProperties" in project_schema


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ("include_patterns: not-a-list\n", "include_patterns must be a list"),
        ("language_overrides: invalid\n", "language_overrides must be a list"),
        ("max_file_size: invalid\n", "max_file_size must be a positive integer"),
    ],
)
def test_index_reports_invalid_repository_settings_as_validation_error(
    code_context_client: tuple[TestClient, Path],
    contents: str,
    expected: str,
) -> None:
    client, repository = code_context_client
    settings_directory = repository / ".code-index"
    settings_directory.mkdir()
    (settings_directory / "settings.yml").write_text(contents, encoding="utf-8")

    response = client.post(
        "/api/code-context/index",
        params={"workspace": str(repository)},
        json={"full": False},
    )

    assert response.status_code == 422
    assert expected in response.json()["detail"]


def test_project_graph_namespaces_repository_local_symbol_ids() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")
    assert _graph_node_id(first, "same-local-id") != _graph_node_id(
        second, "same-local-id"
    )
