"""Authentication in front of every memory-search route."""

from __future__ import annotations

import httpx
import pytest

from memory_helpers import ROUTES, UNAUTHORIZED_BODY

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
    backend, wiki
) -> None:
    with _anonymous(backend, "not-the-token") as http:
        invalid = http.put("/api/wiki/file", json={"path": 1})
        write = http.put("/api/wiki/file", json={"path": "topics/x.md", "content": "x"})
        delete = http.delete("/api/wiki/file?path=USER.md")
        no_query = http.get("/api/wiki/file")
    for response in (invalid, write, delete, no_query):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
    assert not (wiki / "topics" / "x.md").exists()
    assert (wiki / "USER.md").is_file()


def test_token_in_the_query_string_is_not_accepted(backend) -> None:
    with _anonymous(backend, None) as http:
        response = http.get(f"/api/wiki/tree?token={backend.token}")
    assert response.status_code == 401
