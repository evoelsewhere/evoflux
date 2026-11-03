"""Tab bindings: the durable link between a paired browser tab and a session."""

from __future__ import annotations

import re

import httpx

from wb_helpers import INVALID_PAIRING, T

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _assigned(client, pairing, make_session, title="Bound") -> str:
    sid = make_session(title=title)
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    return sid


def test_empty_state(paired) -> None:
    response = paired.get(f"{T}/bindings")
    assert response.status_code == 200
    assert response.json() == []


def test_bind_normalises_the_origin_and_lists_the_binding(
    client, pairing, paired, make_session
) -> None:
    sid = _assigned(client, pairing, make_session)
    response = paired.put(
        f"{T}/bindings/7",
        json={
            "session_id": sid,
            "origin": "HTTPS://Example.COM:8443/some/path?q=1#frag",
            "page_instance_id": "page-1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert list(body) == [
        "tab_id",
        "session_id",
        "origin",
        "page_instance_id",
        "expires_at",
    ]
    assert body["tab_id"] == 7
    assert body["session_id"] == sid
    assert body["origin"] == "https://example.com:8443"
    assert body["page_instance_id"] == "page-1"
    assert ISO_RE.match(body["expires_at"])
    assert paired.get(f"{T}/bindings").json() == [body]


def test_bind_accepts_the_tab_scope_instead_of_an_origin(
    client, pairing, paired, make_session
) -> None:
    sid = _assigned(client, pairing, make_session)
    ok = paired.put(f"{T}/bindings/9", json={"session_id": sid, "origin": "tab:9"})
    assert ok.status_code == 200
    assert ok.json()["origin"] == "tab:9"
    assert ok.json()["page_instance_id"] is None


def test_bind_refuses_an_unusable_scope(client, pairing, paired, make_session) -> None:
    sid = _assigned(client, pairing, make_session)
    expected = {
        "detail": {
            "code": "invalid_tab_scope",
            "message": "Binding requires an HTTP origin or the matching tab scope.",
        }
    }
    for origin in [
        "",
        "tab:8",
        "ftp://example.com",
        "example.com",
        "javascript:alert(1)",
    ]:
        response = paired.put(
            f"{T}/bindings/9", json={"session_id": sid, "origin": origin}
        )
        assert response.status_code == 422, origin
        assert response.json() == expected
    assert paired.get(f"{T}/bindings").json() == []


def test_bind_requires_an_assigned_session(
    client, pairing, paired, make_session
) -> None:
    unassigned = make_session()
    response = paired.put(
        f"{T}/bindings/1",
        json={"session_id": unassigned, "origin": "https://example.com"},
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "session_not_pairing_assigned",
            "message": "Assign this WebBridge session to the paired browser before sharing browser context.",
        }
    }
    missing = paired.put(
        f"{T}/bindings/1",
        json={
            "session_id": "44444444-4444-4444-4444-444444444444",
            "origin": "https://example.com",
        },
    )
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": {"code": "session_not_found", "message": "Target session not found."}
    }


def test_bind_validation(paired) -> None:
    sid = "44444444-4444-4444-4444-444444444444"
    for body in [
        {},
        {"session_id": "nope"},
        {"session_id": sid, "extra": 1},
        {"session_id": sid, "origin": "x" * 2049},
        {"session_id": sid, "page_instance_id": "x" * 129},
    ]:
        assert paired.put(f"{T}/bindings/1", json=body).status_code == 422, body
    negative = paired.put(
        f"{T}/bindings/-1", json={"session_id": sid, "origin": "tab:-1"}
    )
    assert negative.status_code == 404


def test_a_session_keeps_one_tab_and_a_tab_moves_to_the_latest_session(
    client, pairing, paired, make_session
) -> None:
    first = _assigned(client, pairing, make_session, "first")
    second = _assigned(client, pairing, make_session, "second")
    body = {"origin": "https://example.com"}
    assert (
        paired.put(f"{T}/bindings/1", json={"session_id": first, **body}).status_code
        == 200
    )
    # the same session on another tab moves the binding
    assert (
        paired.put(f"{T}/bindings/2", json={"session_id": first, **body}).status_code
        == 200
    )
    assert [b["tab_id"] for b in paired.get(f"{T}/bindings").json()] == [2]
    # a second session on that tab displaces the first one
    assert (
        paired.put(f"{T}/bindings/2", json={"session_id": second, **body}).status_code
        == 200
    )
    bindings = paired.get(f"{T}/bindings").json()
    assert [(b["tab_id"], b["session_id"]) for b in bindings] == [(2, second)]


def test_unbind_is_idempotent(client, pairing, paired, make_session) -> None:
    sid = _assigned(client, pairing, make_session)
    assert (
        paired.put(
            f"{T}/bindings/3", json={"session_id": sid, "origin": "https://example.com"}
        ).status_code
        == 200
    )
    first = paired.delete(f"{T}/bindings/3")
    assert first.status_code == 204
    assert first.content == b""
    assert paired.get(f"{T}/bindings").json() == []
    assert paired.delete(f"{T}/bindings/3").status_code == 204
    assert paired.delete(f"{T}/bindings/999").status_code == 204


def test_bindings_are_private_to_their_pairing(
    backend, client, pairing, paired, make_session, insert_pairing
) -> None:
    sid = _assigned(client, pairing, make_session)
    assert (
        paired.put(
            f"{T}/bindings/3", json={"session_id": sid, "origin": "https://example.com"}
        ).status_code
        == 200
    )
    other = insert_pairing(
        ["bindings:write", "sessions:create"], credential="other-credential"
    )
    with httpx.Client(
        base_url=backend.base_url, headers=other.bearer, timeout=30.0
    ) as http:
        assert http.get(f"{T}/bindings").json() == []
        assert http.delete(f"{T}/bindings/3").status_code == 204
    assert len(paired.get(f"{T}/bindings").json()) == 1


def test_create_and_bind_a_session(client, pairing, paired) -> None:
    created = paired.post(
        f"{T}/bindings/12/sessions",
        json={
            "title": "  New  ",
            "origin": "https://Example.com/x",
            "page_instance_id": "p",
        },
        headers={"Idempotency-Key": "key-1"},
    )
    assert created.status_code == 201
    body = created.json()
    assert list(body) == ["session", "binding"]
    assert list(body["session"]) == [
        "id",
        "title",
        "mode",
        "running",
        "model",
        "thinking_level",
    ]
    assert body["session"]["title"] == "New"
    assert body["session"]["mode"] == "work"
    assert body["session"]["running"] is False
    assert body["binding"]["tab_id"] == 12
    assert body["binding"]["origin"] == "https://example.com"
    assert body["binding"]["session_id"] == body["session"]["id"]
    # the same idempotency key reuses the session
    again = paired.post(
        f"{T}/bindings/12/sessions",
        json={"title": "Ignored", "origin": "https://example.com"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert again.status_code == 201
    assert again.json()["session"]["id"] == body["session"]["id"]
    assert again.json()["session"]["title"] == "New"
    other = paired.post(
        f"{T}/bindings/12/sessions",
        json={"title": "Other", "origin": "https://example.com"},
        headers={"Idempotency-Key": "key-2"},
    )
    assert other.json()["session"]["id"] != body["session"]["id"]
    # the new session is listed for the pairing and the binding moved to it
    assert [s["title"] for s in paired.get(f"{T}/sessions").json()].count("Other") == 1
    assert [b["session_id"] for b in paired.get(f"{T}/bindings").json()] == [
        other.json()["session"]["id"]
    ]


def test_create_and_bind_errors(
    client, pairing, paired, insert_pairing, backend
) -> None:
    key = {"Idempotency-Key": "k"}
    good = {"title": "T", "origin": "https://example.com"}
    scope_error = {
        "detail": {
            "code": "invalid_tab_scope",
            "message": "Binding requires an HTTP origin or the matching tab scope.",
        }
    }
    missing_key = paired.post(f"{T}/bindings/1/sessions", json=good)
    assert missing_key.status_code == 422
    assert missing_key.json()["detail"]["code"] == "invalid_idempotency_key"
    long_key = paired.post(
        f"{T}/bindings/1/sessions", json=good, headers={"Idempotency-Key": "k" * 129}
    )
    assert long_key.status_code == 422
    bad_scope = paired.post(
        f"{T}/bindings/1/sessions", json={"title": "T", "origin": ""}, headers=key
    )
    assert bad_scope.status_code == 422
    assert bad_scope.json() == scope_error
    # scope is checked before the idempotency key
    both = paired.post(f"{T}/bindings/1/sessions", json={"title": "T", "origin": ""})
    assert both.json() == scope_error
    for body in [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 256},
        {"title": "T", "bogus": 1},
    ]:
        assert (
            paired.post(f"{T}/bindings/1/sessions", json=body, headers=key).status_code
            == 422
        ), body
    only_create = insert_pairing(["sessions:create"], credential="create-only")
    with httpx.Client(
        base_url=backend.base_url, headers=only_create.bearer, timeout=30.0
    ) as http:
        refused = http.post(f"{T}/bindings/1/sessions", json=good, headers=key)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Pairing lacks binding scope."}
    no_create = insert_pairing(["bindings:write"], credential="bind-only")
    with httpx.Client(
        base_url=backend.base_url, headers=no_create.bearer, timeout=30.0
    ) as http:
        unpaired = http.post(f"{T}/bindings/1/sessions", json=good, headers=key)
    assert unpaired.status_code == 401
    assert unpaired.json() == INVALID_PAIRING
