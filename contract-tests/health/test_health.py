"""Health and auth contract: the first area every backend must satisfy."""

from __future__ import annotations

import httpx

from normalize import normalize

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}


def test_live_ok(client: httpx.Client) -> None:
    response = client.get("/api/health/live")
    assert response.status_code == 200


def test_ready_shape(client: httpx.Client, snapshot) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    snapshot.check("ready.json", normalize(response.json()))


def test_auth_required(backend) -> None:
    response = httpx.get(f"{backend.base_url}/api/agents", timeout=30.0)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_token_query_param(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/agents",
        params={"_token": backend.token},
        timeout=30.0,
    )
    assert response.status_code == 200
