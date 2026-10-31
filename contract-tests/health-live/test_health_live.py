"""``GET /api/health/live`` contract (unit ``health-live``).

Liveness never touches the database and needs no credentials. ``/ready`` and
``/diagnostics`` belong to ``health-diagnostics`` and are not covered here.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

LIVE = "/api/health/live"


def test_live_success_body(client: httpx.Client) -> None:
    response = client.get(LIVE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"status", "version"}
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]


def test_live_needs_no_credentials(backend) -> None:
    response = httpx.get(f"{backend.base_url}{LIVE}", timeout=30.0)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_live_ignores_wrong_credentials(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}{LIVE}",
        headers={"Authorization": "Bearer not-the-token"},
        params={"_token": "also-wrong"},
        timeout=30.0,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_live_version_is_stable(client: httpx.Client) -> None:
    assert client.get(LIVE).json() == client.get(LIVE).json()


def test_live_has_no_parameters(client: httpx.Client) -> None:
    """No validation can fail: unknown query parameters are ignored."""
    plain = client.get(LIVE)
    with_query = client.get(LIVE, params={"verbose": "1", "days": "not-a-number"})
    assert with_query.status_code == 200
    assert with_query.json() == plain.json()


def test_live_rejects_other_methods(client: httpx.Client) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, LIVE)
        assert response.status_code == 405, method
        assert response.json() == {"detail": "Method Not Allowed"}, method
        assert "GET" in response.headers["allow"], method


def test_live_sub_path_is_not_the_probe(client: httpx.Client) -> None:
    """``/api/health/live/x`` is a plain 404, not a probe answer."""
    response = client.get(f"{LIVE}/x")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_live_concurrent_requests(client: httpx.Client) -> None:
    """Many simultaneous probes all answer; there is no state to corrupt."""
    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(lambda _: client.get(LIVE), range(64)))
    assert {r.status_code for r in responses} == {200}
    assert len({r.text for r in responses}) == 1
