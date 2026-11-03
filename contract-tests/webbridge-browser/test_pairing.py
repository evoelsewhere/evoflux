"""Native bootstrap, pairings, scopes, relay tickets and session assignment."""

from __future__ import annotations

import re
import sqlite3

import httpx
import pytest
from websockets.sync.client import connect

from wb_helpers import ALL_SCOPES, EXTENSION_ORIGIN, INVALID_PAIRING, T

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REFUSED = {
    "detail": {
        "code": "native_pairing_refused",
        "message": "Native WebBridge discovery was not authorized.",
    }
}
MISSING = "33333333-3333-3333-3333-333333333333"


def _discovery(client: httpx.Client) -> str:
    response = client.get(f"{T}/native-discovery")
    assert response.status_code == 200
    assert list(response.json()) == ["discovery_token"]
    return response.json()["discovery_token"]


def _native(
    backend, body: dict, origin: str | None = EXTENSION_ORIGIN
) -> httpx.Response:
    headers = {"Origin": origin} if origin is not None else {}
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        return anonymous.post(f"{T}/pairing/native", headers=headers, json=body)


def _row(client: httpx.Client, pairing_id: str) -> dict:
    return next(
        p for p in client.get(f"{T}/pairings").json() if p["pairing_id"] == pairing_id
    )


def test_native_discovery_token_is_stable_for_the_process(backend, client) -> None:
    first = _discovery(client)
    assert len(first) >= 32
    assert _discovery(client) == first


def test_native_pairing_issues_a_credential_with_every_default_scope(
    backend, client
) -> None:
    response = _native(
        backend,
        {
            "label": "  My Chrome  ",
            "browser": "chrome",
            "version": "126",
            "discovery_token": _discovery(client),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert list(body) == ["pairing_id", "credential", "scopes"]
    assert UUID_RE.match(body["pairing_id"])
    assert len(body["credential"]) == 43
    assert body["scopes"] == ALL_SCOPES
    listed = client.get(f"{T}/pairings").json()
    assert len(listed) == 1
    row = listed[0]
    assert list(row) == [
        "pairing_id",
        "label",
        "browser",
        "version",
        "scopes",
        "created_at",
        "last_seen_at",
    ]
    assert row["pairing_id"] == body["pairing_id"]
    assert row["label"] == "My Chrome"
    assert (row["browser"], row["version"]) == ("chrome", "126")
    assert row["scopes"] == ALL_SCOPES


def test_native_pairing_defaults(backend, client) -> None:
    response = _native(backend, {"discovery_token": _discovery(client)})
    assert response.status_code == 201
    row = client.get(f"{T}/pairings").json()[0]
    assert (row["label"], row["browser"], row["version"]) == (
        "Local Chrome / Edge",
        "unknown",
        "unknown",
    )


def test_native_pairing_refusals_are_all_403(backend, client) -> None:
    good = {"discovery_token": _discovery(client)}
    for body, origin in [
        (good, None),
        (good, "https://example.com"),
        (good, "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        (good, "chrome-extension://"),
        ({"discovery_token": "x" * 43}, EXTENSION_ORIGIN),
    ]:
        response = _native(backend, body, origin)
        assert response.status_code == 403, (body, origin)
        assert response.json() == REFUSED
    assert client.get(f"{T}/pairings").json() == []


@pytest.mark.parametrize(
    "extra",
    [
        {"discovery_token": "short"},
        {"discovery_token": "x" * 257},
        {"label": "   "},
        {"label": ""},
        {"label": "x" * 121},
        {"browser": "x" * 41},
        {"version": "x" * 41},
        {"unexpected": 1},
    ],
)
def test_native_pairing_validation_runs_before_the_authorization_check(
    backend, client, extra
) -> None:
    """The origin below is wrong, yet the body error wins."""
    body = {"discovery_token": _discovery(client), **extra}
    response = _native(backend, body, origin=None)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_pairings_are_listed_most_recently_seen_first(backend, client) -> None:
    token = _discovery(client)
    ids = [
        _native(backend, {"label": f"P{i}", "discovery_token": token}).json()[
            "pairing_id"
        ]
        for i in range(3)
    ]
    assert [p["pairing_id"] for p in client.get(f"{T}/pairings").json()] == ids[::-1]


def test_relay_ticket_shape(backend, client, pairing, paired) -> None:
    first = paired.post(f"{T}/relay-ticket")
    assert first.status_code == 201
    assert list(first.json()) == ["ticket", "expires_in"]
    assert first.json()["expires_in"] == 30
    assert len(first.json()["ticket"]) == 43
    second = paired.post(f"{T}/relay-ticket")
    assert second.json()["ticket"] != first.json()["ticket"]
    assert paired.get(f"{T}/relay-ticket").status_code == 405
    assert paired.get(f"{T}/relay-ticket").json() == {"detail": "Method Not Allowed"}


def test_a_pairing_without_the_scope_is_treated_as_unpaired(
    backend, client, insert_pairing
) -> None:
    restricted = insert_pairing(["sessions:list"])
    with httpx.Client(
        base_url=backend.base_url, headers=restricted.bearer, timeout=30.0
    ) as http:
        assert http.get(f"{T}/sessions").status_code == 200
        assert http.get(f"{T}/appearance").status_code == 200  # needs sessions:list
        for method, path in [
            ("POST", "/relay-ticket"),
            ("GET", "/bindings"),
        ]:
            response = http.request(method, f"{T}{path}")
            assert response.status_code == 401, path
            assert response.json() == INVALID_PAIRING


def test_historical_scope_sets_are_upgraded_on_a_write_request_only(
    backend, client, insert_pairing
) -> None:
    p0 = [
        "bindings:write",
        "interactions:write",
        "relay",
        "session-stream:read",
        "sessions:list",
    ]
    old = insert_pairing(p0)
    with httpx.Client(
        base_url=backend.base_url, headers=old.bearer, timeout=30.0
    ) as http:
        # A GET authorises against the upgraded set without persisting it.
        assert http.get(f"{T}/appearance").status_code == 200
        assert _row(client, old.id)["scopes"] == p0
        assert http.post(f"{T}/relay-ticket").status_code == 201
        assert _row(client, old.id)["scopes"] == ALL_SCOPES
        created = http.post(
            f"{T}/sessions", json={"title": "x"}, headers={"Idempotency-Key": "u1"}
        )
        assert created.status_code == 201


def test_a_get_does_not_refresh_last_seen_but_a_post_does(
    backend, client, pairing, paired
) -> None:
    before = _row(client, pairing.id)["last_seen_at"]
    assert paired.get(f"{T}/sessions").status_code == 200
    assert _row(client, pairing.id)["last_seen_at"] == before
    assert paired.post(f"{T}/relay-ticket").status_code == 201
    assert _row(client, pairing.id)["last_seen_at"] > before


def test_delete_pairing_revokes_the_credential_and_clears_its_data(
    backend, client, pairing, paired, make_session, db_path
) -> None:
    sid = make_session()
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    bound = paired.put(
        f"{T}/bindings/4", json={"session_id": sid, "origin": "https://example.com"}
    )
    assert bound.status_code == 200
    ticket = paired.post(f"{T}/relay-ticket").json()["ticket"]
    deleted = client.delete(f"{T}/pairings/{pairing.id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"{T}/pairings").json() == []
    for method, path in [
        ("GET", "/sessions"),
        ("POST", "/relay-ticket"),
        ("GET", "/bindings"),
    ]:
        response = paired.request(method, f"{T}{path}")
        assert response.status_code == 401
        assert response.json() == INVALID_PAIRING
    again = client.delete(f"{T}/pairings/{pairing.id}")
    assert again.status_code == 404
    assert again.json() == {"detail": "Pairing not found."}
    with sqlite3.connect(db_path, timeout=30) as db:
        assert (
            db.execute("SELECT count(*) FROM webbridge_tab_bindings").fetchone()[0] == 0
        )
        row = db.execute(
            "SELECT tags FROM chat_sessions WHERE id = ?", (sid.replace("-", ""),)
        ).fetchone()
        assert row is not None
        assert row[0] in (None, "null", "[]")
        assert (
            db.execute("SELECT revoked_at FROM webbridge_pairings").fetchone()[0]
            is not None
        )
    # the ticket issued before the revocation is dead
    url = backend.base_url.replace("http://", "ws://") + f"{T}/relay?_ticket={ticket}"
    with pytest.raises(Exception) as caught:  # noqa: PT011
        with connect(url, open_timeout=30):
            pass
    assert caught.value.response.status_code == 403


def test_delete_unknown_pairing_is_404_and_a_bad_id_is_422(backend, client) -> None:
    missing = client.delete(f"{T}/pairings/{MISSING}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Pairing not found."}
    assert client.delete(f"{T}/pairings/not-a-uuid").status_code == 422


def test_assign_session_to_pairing(
    backend, client, pairing, paired, make_session
) -> None:
    sid = make_session(title="Mine")
    assigned = client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}")
    assert assigned.status_code == 200
    assert assigned.json() == {
        "id": sid,
        "title": "Mine",
        "mode": "work",
        "running": False,
        "model": None,
        "thinking_level": None,
    }
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    assert paired.get(f"{T}/sessions").json() == [assigned.json()]


def test_assign_session_error_precedence(
    backend, client, pairing, make_session
) -> None:
    sid = make_session()
    missing_pairing = client.put(f"{T}/pairings/{MISSING}/sessions/{sid}")
    assert missing_pairing.status_code == 404
    assert missing_pairing.json() == {"detail": "Pairing not found."}
    missing_session = client.put(
        f"{T}/pairings/{pairing.id}/sessions/44444444-4444-4444-4444-444444444444"
    )
    assert missing_session.status_code == 404
    assert missing_session.json() == {
        "detail": {"code": "session_not_found", "message": "Target session not found."}
    }
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/nope").status_code == 422
    assert client.delete(f"{T}/pairings/{pairing.id}").status_code == 204
    revoked = client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}")
    assert revoked.status_code == 404
    assert revoked.json() == {"detail": "Pairing not found."}


def test_assign_session_is_refused_while_webbridge_is_disabled(
    backend, client, pairing, make_session
) -> None:
    sid = make_session()
    current = client.get("/api/settings/webbridge").json()
    off = client.put("/api/settings/webbridge", json={**current, "enabled": False})
    assert off.status_code == 200
    response = client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}")
    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "webbridge_disabled",
            "message": "WebBridge is turned off in EvoFlux Settings.",
        }
    }
    missing = client.put(
        f"{T}/pairings/{pairing.id}/sessions/44444444-4444-4444-4444-444444444444"
    )
    assert missing.status_code == 404
