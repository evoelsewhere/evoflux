"""``/api/auth``: the access-key check and the OAuth login/callback routes.

The login success path needs a provider's OAuth server (device code, browser
redirect), so it is covered only by the Python unit tests
(``tests/api/test_auth_routes.py``); here the routes are tested up to the
provider lookup, which is all they do without one.
"""

from __future__ import annotations


def test_check_is_a_protected_noop(client) -> None:
    response = client.get("/api/auth/check")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["content-type"].startswith("application/json")


def test_check_only_allows_get(client) -> None:
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        response = client.request(method, "/api/auth/check")
        assert response.status_code == 405, method
        assert response.json() == {"detail": "Method Not Allowed"}


def test_login_unknown_provider_lists_the_known_ones(client) -> None:
    response = client.get("/api/auth/nope/login")
    assert response.status_code == 404
    assert response.json() == {
        "detail": "Unknown OAuth provider 'nope'. Known: ['codex', 'copilot', 'xiaomi']."
    }


def test_login_provider_ids_are_case_sensitive(client) -> None:
    response = client.get("/api/auth/Codex/login")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("Unknown OAuth provider 'Codex'.")


def test_callback_unknown_provider_is_404(client) -> None:
    response = client.post("/api/auth/nope/callback", json={"code": "abc"})
    assert response.status_code == 404
    assert response.json() == {"detail": "OAuth callback unsupported for 'nope'"}


def test_callback_for_a_builtin_oauth_provider_is_unsupported(client) -> None:
    # Only provider plugins implement a callback; codex and copilot use the
    # device-code login above.
    response = client.post("/api/auth/codex/callback", json={"code": "abc"})
    assert response.status_code == 404
    assert response.json() == {"detail": "OAuth callback unsupported for 'codex'"}


def test_callback_body_validation(client, snapshot) -> None:
    missing = client.post("/api/auth/nope/callback", json={})
    extra = client.post("/api/auth/nope/callback", json={"code": "c", "x": 1})
    wrong_type = client.post("/api/auth/nope/callback", json={"code": 5})
    no_body = client.post("/api/auth/nope/callback")
    assert [r.status_code for r in (missing, extra, wrong_type, no_body)] == [422] * 4
    snapshot.check(
        "auth_callback_422.json",
        {
            "missing": missing.json(),
            "extra": extra.json(),
            "wrong_type": wrong_type.json(),
            "no_body": no_body.json(),
        },
    )


def test_validation_precedes_the_provider_lookup(client) -> None:
    # An unknown provider with a bad body is a 422, not a 404.
    response = client.post("/api/auth/nope/callback", json={"code": 5})
    assert response.status_code == 422


def test_the_auth_prefix_itself_is_not_a_route(client) -> None:
    for path in ("/api/auth", "/api/auth/", "/api/auth/codex"):
        response = client.get(path)
        assert response.status_code in (404, 307), path
    assert client.get("/api/auth/codex").status_code == 404
