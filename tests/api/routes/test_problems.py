from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.problems_service import ProblemInput, clear_problems, publish_problems

pytestmark = pytest.mark.usefixtures("setup_db")


@pytest.fixture(autouse=True)
def _clear():
    clear_problems()
    yield
    clear_problems()


@pytest.fixture
def client():
    from app.api.app import create_app

    return TestClient(create_app())


def test_lists_counts_and_dismisses_problem(client, tmp_path, monkeypatch):
    from app.api.routes.team import problems as problem_routes

    monkeypatch.setattr(problem_routes, "list_effective_installations", lambda: [])
    publish_problems(
        tmp_path,
        source="security",
        scope="security:review",
        problems=[
            ProblemInput(
                message="Unsafe callback URL",
                severity="error",
                path="app.py",
                code="SSRF",
            )
        ],
    )

    response = client.get(
        "/api/team/workspace/problems", params={"workspace": str(tmp_path)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["error"] == 1
    problem_id = body["problems"][0]["id"]
    dismissed = client.post(
        f"/api/team/workspace/problems/{problem_id}/dismiss",
        params={"workspace": str(tmp_path)},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"


def test_plugin_diagnostics_are_unified(client, tmp_path, monkeypatch):
    from app.api.routes.team import problems as problem_routes

    installation = SimpleNamespace(
        id="a" * 32,
        name="example-plugin",
        root=str(tmp_path / "plugin"),
    )
    diagnostic = SimpleNamespace(
        severity="error",
        code="invalid-manifest",
        message="Manifest is invalid",
        scope="package",
    )
    inspection = SimpleNamespace(
        diagnostics=[diagnostic],
        skills=[],
        mcp_servers=[],
    )
    monkeypatch.setattr(
        problem_routes, "list_effective_installations", lambda: [installation]
    )
    monkeypatch.setattr(
        problem_routes, "inspect_plugin", lambda *_args, **_kwargs: inspection
    )
    monkeypatch.setattr(problem_routes, "plugin_data_root", lambda _id: tmp_path)

    response = client.get(
        "/api/team/workspace/problems", params={"workspace": str(tmp_path)}
    )

    assert response.status_code == 200
    problem = response.json()["problems"][0]
    assert problem["source"] == "plugin"
    assert problem["code"] == "invalid-manifest"
    assert problem["provenance"]["plugin"] == "example-plugin"
