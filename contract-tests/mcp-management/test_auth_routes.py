"""Authentication in front of every ``/api/mcp`` route."""

from __future__ import annotations

import httpx
import pytest

from mcp_helpers import ROUTES, UNAUTHORIZED_BODY, stdio_body

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


def test_auth_runs_before_validation_and_a_rejected_write_changes_nothing(
    backend, config_dir, mcp_json
) -> None:
    seeded = mcp_json.read_bytes()
    with _anonymous(backend, "not-the-token") as http:
        invalid = http.post("/api/mcp/servers", json={"name": 1})
        no_body = http.put("/api/mcp/servers/x")
        write = http.post(
            "/api/mcp/servers", json={"name": "x", "server": stdio_body()}
        )
    for response in (invalid, no_body, write):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
    assert mcp_json.read_bytes() == seeded
    assert not (config_dir / ".env").exists()
