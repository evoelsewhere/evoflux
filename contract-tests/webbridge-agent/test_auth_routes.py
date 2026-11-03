"""Every pairing-scoped route: credential, scope, session assignment and the enabled switch."""

from __future__ import annotations

import httpx
import pytest

from wa_helpers import INVALID_PAIRING, T

SID = "11111111-1111-1111-1111-111111111111"
MID = "22222222-2222-2222-2222-222222222222"
S = f"{T}/sessions/{SID}"
MESSAGE = {
    "content": "hi",
    "tab_id": 5,
    "origin": "https://example.com",
    "user_gesture": True,
}

# (method, path, json body, scope the route requires)
ROUTES: list[tuple[str, str, object, str]] = [
    ("GET", f"{T}/sessions", None, "sessions:list"),
    ("POST", f"{T}/sessions", {"title": "t"}, "sessions:create"),
    ("GET", f"{T}/models", None, "sessions:list"),
    ("PATCH", f"{S}/model", {}, "session:messages:write"),
    ("POST", f"{S}/commands", {"command": "continue"}, "session:messages:write"),
    ("GET", f"{S}/queued-messages", None, "session-stream:read"),
    ("PATCH", f"{S}/queued-messages/{MID}", {"content": "x"}, "session:messages:write"),
    ("DELETE", f"{S}/queued-messages/{MID}", None, "session:messages:write"),
    ("POST", f"{S}/permissions/r1/reply", {"reply": "once"}, "handoff:reply"),
    ("GET", f"{S}/composer-catalog", None, "session-stream:read"),
    ("POST", f"{S}/composer/commands/stop/render", {}, "session-stream:read"),
    ("POST", f"{S}/composer/snippets/x/render", None, "session-stream:read"),
    ("GET", f"{S}/history", None, "session-stream:read"),
    ("GET", f"{S}/messages/{MID}/attachments/0", None, "session-stream:read"),
    ("DELETE", f"{S}/messages/{MID}/attachments/0", None, "session:messages:write"),
    ("GET", f"{S}/media/a.png", None, "session-stream:read"),
    ("POST", f"{S}/messages", MESSAGE, "session:messages:write"),
    ("POST", f"{S}/interrupt", None, "session:messages:write"),
    ("GET", f"{S}/stream", None, "session-stream:read"),
    ("GET", f"{S}/questions/pending", None, "session-stream:read"),
    (
        "POST",
        f"{S}/questions/r1/reply",
        {"request_session_id": SID, "answers": ["a"]},
        "handoff:reply",
    ),
    (
        "POST",
        f"{T}/interactions",
        {"kind": "page.note", "delivery": "draft"},
        "interactions:write",
    ),
]
# These two take an Idempotency-Key header before they look at the session.
IDS = [f"{m} {p.removeprefix(T)}" for m, p, _, _ in ROUTES]


@pytest.mark.parametrize(("method", "path", "body", "scope"), ROUTES, ids=IDS)
def test_route_refuses_without_a_pairing_credential(
    backend, method, path, body, scope
) -> None:
    """These paths skip the access-key middleware; the access key itself is not accepted."""
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Bearer {backend.token}"},
    ):
        with httpx.Client(
            base_url=backend.base_url, headers=headers, timeout=30.0
        ) as caller:
            response = caller.request(method, path, json=body)
        assert response.status_code == 401, (method, path)
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == INVALID_PAIRING


@pytest.mark.parametrize(("method", "path", "body", "scope"), ROUTES, ids=IDS)
def test_route_needs_its_scope(
    backend, insert_pairing, method, path, body, scope
) -> None:
    """A pairing that holds every scope except the required one is treated as unpaired."""
    from wa_helpers import ALL_SCOPES

    granted = [s for s in ALL_SCOPES if s != scope]
    # A historical set is silently upgraded, so keep this one off the known sets.
    granted = [s for s in granted if s != "teach:drafts:write"] + ["custom:scope"]
    pairing = insert_pairing(granted, credential=f"cred-{scope}")
    with httpx.Client(
        base_url=backend.base_url, headers=pairing.bearer, timeout=30.0
    ) as caller:
        response = caller.request(
            method, path, json=body, headers={"Idempotency-Key": "k"}
        )
    assert response.status_code == 401, (method, path)
    assert response.json() == INVALID_PAIRING


SESSION_ROUTES = [r for r in ROUTES if "/sessions/" in r[1]]


@pytest.mark.parametrize(
    ("method", "path", "body", "scope"),
    SESSION_ROUTES,
    ids=[f"{m} {p.removeprefix(T)}" for m, p, _, _ in SESSION_ROUTES],
)
def test_session_routes_check_the_session_before_the_body(
    backend, pairing, paired, make_session, method, path, body, scope
) -> None:
    """Unknown session 404, unassigned session 403 (both with the same envelope shape)."""
    unknown = paired.request(method, path, json=body, headers={"Idempotency-Key": "k"})
    assert unknown.status_code == 404
    assert unknown.json() == {
        "detail": {"code": "session_not_found", "message": "Target session not found."}
    }
    real = make_session()
    unassigned_path = path.replace(SID, real)
    unassigned = paired.request(
        method, unassigned_path, json=body, headers={"Idempotency-Key": "k"}
    )
    assert unassigned.status_code == 403
    assert unassigned.json() == {
        "detail": {
            "code": "session_not_pairing_assigned",
            "message": "Assign this WebBridge session to the paired browser before sharing browser context.",
        }
    }


def test_a_session_assigned_to_another_pairing_is_refused(
    backend, client, pairing, paired, make_session, insert_pairing
) -> None:
    sid = make_session()
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    other = insert_pairing(
        [s for s in ["sessions:list", "session-stream:read", "custom:scope"]],
        credential="other",
    )
    with httpx.Client(
        base_url=backend.base_url, headers=other.bearer, timeout=30.0
    ) as http:
        refused = http.get(f"{T}/sessions/{sid}/history")
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "session_not_pairing_assigned"
        assert http.get(f"{T}/sessions").json() == []


def test_disabled_webbridge_refuses_session_routes_but_not_the_listing(
    client, pairing, paired, panel
) -> None:
    current = client.get("/api/settings/webbridge").json()
    assert (
        client.put(
            "/api/settings/webbridge", json={**current, "enabled": False}
        ).status_code
        == 200
    )
    refused = paired.get(f"{T}/sessions/{panel}/history")
    assert refused.status_code == 403
    assert refused.json() == {
        "detail": {
            "code": "webbridge_disabled",
            "message": "WebBridge is turned off in EvoFlux Settings.",
        }
    }
    # session lookup comes first, then the switch
    missing = paired.get(f"{T}/sessions/{SID}/history")
    assert missing.status_code == 404
    assert paired.get(f"{T}/sessions").status_code == 200


def test_a_revoked_pairing_loses_every_route(client, pairing, paired, panel) -> None:
    assert client.delete(f"{T}/pairings/{pairing.id}").status_code == 204
    for method, path in [
        ("GET", f"{T}/sessions/{panel}/history"),
        ("GET", f"{T}/sessions"),
        ("POST", f"{T}/interrupt"),
    ]:
        response = paired.request(method, path)
        assert response.status_code in (401, 404, 405)
    assert paired.get(f"{T}/sessions/{panel}/history").json() == INVALID_PAIRING
