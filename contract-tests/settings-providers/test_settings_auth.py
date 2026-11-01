"""Authentication in front of every ``/api/settings`` and ``/api/auth`` route."""

from __future__ import annotations

import httpx
import pytest
import yaml

from settings_helpers import ROUTES, UNAUTHORIZED_BODY

IDS = [f"{method} {path}" for method, path, _ in ROUTES]


def _anonymous(backend, token: str | None) -> httpx.Client:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return httpx.Client(base_url=backend.base_url, headers=headers, timeout=30.0)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=IDS)
def test_missing_token_is_401(backend, method, path, body) -> None:
    with _anonymous(backend, None) as http:
        response = http.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=IDS)
def test_wrong_token_is_401(backend, method, path, body) -> None:
    with _anonymous(backend, "not-the-token") as http:
        response = http.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_auth_runs_before_validation_and_before_the_provider_lookup(backend) -> None:
    with _anonymous(backend, None) as http:
        invalid = http.put("/api/settings/sandbox", json={"max_execution_seconds": 1})
        unknown = http.put("/api/settings/providers/nope", json={"api_key": 5})
        no_body = http.put("/api/settings/team-spawn")
    for response in (invalid, unknown, no_body):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY


def test_a_rejected_write_changes_nothing(backend, config_dir) -> None:
    before = (config_dir / "settings.yaml").read_text(encoding="utf-8")
    with _anonymous(backend, "not-the-token") as http:
        http.put("/api/settings/follow-up", json={"delivery": "steer"})
        http.put("/api/settings/sandbox", json={"denied_patterns": ["x"]})
        http.put("/api/settings/providers/anthropic", json={"api_key": "k"})
        http.put("/api/settings/providers/anthropic/visible-models", json={"models": ["m"]})
        http.delete("/api/settings/providers/anthropic")
        http.post("/api/settings/seed", json={})
    assert (config_dir / "settings.yaml").read_text(encoding="utf-8") == before
    assert yaml.safe_load(before).get("follow_up", {}).get("delivery") != "steer"
    assert not (config_dir / "sandbox.yaml").exists()
    assert not (config_dir / ".env").exists()


def test_the_token_is_accepted_only_as_a_bearer_header(backend) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as http:
        in_query = http.get("/api/auth/check", params={"token": backend.token})
        basic = http.get(
            "/api/auth/check", headers={"Authorization": f"Basic {backend.token}"}
        )
        bearer = http.get(
            "/api/auth/check", headers={"Authorization": f"Bearer {backend.token}"}
        )
    assert in_query.status_code == 401
    assert basic.status_code == 401
    assert bearer.status_code == 200
