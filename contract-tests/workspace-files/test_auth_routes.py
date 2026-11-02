"""Every route of the unit needs the access key, before any validation."""

from __future__ import annotations

import httpx
import pytest

from ws_helpers import ROUTES, UNAUTHORIZED_BODY


@pytest.mark.parametrize(
    ("method", "path", "query", "body"),
    ROUTES,
    ids=[f"{m} {p}" for m, p, _, _ in ROUTES],
)
def test_route_requires_the_access_key(backend, method, path, query, body) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        response = anonymous.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": "Bearer wrong"},
        timeout=30.0,
    ) as wrong:
        response = wrong.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY


def test_upload_route_needs_the_key_before_the_multipart_body(backend) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        response = anonymous.post(
            "/api/team/11111111-1111-1111-1111-111111111111/files/upload"
        )
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
