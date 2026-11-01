"""HTTP (Streamable HTTP) servers and the OAuth connect flow, against a local fixture.

The fixture server (``http_server.py``) is on 127.0.0.1; no test reaches the
internet. A browser is never opened: the fixture never answers 401 to an OAuth
client, so the interactive redirect handler is not reached. (Connecting an OAuth
server that does answer 401 would call ``webbrowser.open``, so no test does.)
"""

from __future__ import annotations

import json

import pytest

from http_server import FakeHttpMcp
from mcp_helpers import create, lf, read_json, stdio_body

MASK = "********"


def http_server(url, **fields):
    return {"transport": "http", "url": url, **fields}


@pytest.fixture
def protected():
    server = FakeHttpMcp(require_token="good")
    try:
        yield server
    finally:
        server.close()


def test_a_reachable_server_is_ready_and_receives_the_mcp_handshake(
    client, http_mcp
) -> None:
    body = create(client, "web", http_server(http_mcp.url)).json()
    assert body["state"] == "ready"
    assert body["tool_names"] == ["mcp_web_ping"]
    sequence = [(r["method"], r.get("rpc")) for r in http_mcp.requests]
    assert ("POST", "initialize") in sequence
    assert ("POST", "notifications/initialized") in sequence
    assert ("POST", "tools/list") in sequence
    assert {r["path"] for r in http_mcp.requests} == {"/mcp"}


def test_delete_closes_the_http_session(client, http_mcp) -> None:
    create(client, "web", http_server(http_mcp.url))
    client.delete("/api/mcp/servers/web")
    assert ("DELETE", "/mcp") in [(r["method"], r["path"]) for r in http_mcp.requests]


def test_a_bare_401_without_oauth_config_is_an_error_state(client, protected) -> None:
    """The SDK turns a 401 with no ``WWW-Authenticate`` into a generic MCP error."""
    body = create(client, "web", http_server(protected.url)).json()
    assert body["state"] == "error"
    assert body["error"] == "ExceptionGroup (ExceptionGroup (MCPError: Server returned an error response))"
    assert body["tool_names"] == []
    assert body["started_at"] is None


def test_a_header_that_satisfies_the_server_makes_it_ready(client, protected) -> None:
    body = create(
        client, "web", http_server(protected.url, headers={"Authorization": "Bearer good"})
    ).json()
    assert body["state"] == "ready"


MISSING = (
    "ExceptionGroup (UnsupportedProtocol: Request URL is missing an "
    "'http://' or 'https://' protocol.)"
)


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("file:///etc/passwd", MISSING),
        ("not a url", MISSING),
        (
            "ftp://127.0.0.1/x",
            "ExceptionGroup (UnsupportedProtocol: Request URL has an unsupported "
            "protocol 'ftp://'.)",
        ),
    ],
)
def test_urls_are_not_validated_and_a_bad_one_is_an_error_state(
    client, mcp_json, url, error
) -> None:
    """Finding U1: any non-empty string is saved; the failure shows up in ``state``."""
    response = create(client, "web", http_server(url))
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "error"
    assert body["error"] == error
    assert read_json(mcp_json)["servers"]["web"]["url"] == url


def test_a_closed_port_is_an_error_state(client) -> None:
    body = create(client, "web", http_server("http://127.0.0.1:9/mcp")).json()
    assert body["state"] == "error"
    assert body["error"].startswith("ExceptionGroup (ConnectError:")


def test_the_slack_host_needs_oauth_config_before_any_connection(client) -> None:
    body = create(client, "slack", http_server("https://mcp.slack.com/mcp")).json()
    assert body["state"] == "auth_required"
    assert body["error"] == (
        "MCP server 'slack' requires OAuth. Enable OAuth, add the OAuth app client ID "
        "and secret in Settings, then Connect OAuth."
    )


def test_oauth_without_cached_tokens_never_connects_until_connect_is_called(
    client, http_mcp
) -> None:
    body = create(
        client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"})
    ).json()
    assert body["state"] == "auth_required"
    assert body["error"] == "MCP server 'web' needs OAuth. Use Settings -> MCP -> Connect OAuth."
    assert http_mcp.requests == []


def test_cached_oauth_tokens_are_sent_as_a_bearer_token(
    client, http_mcp, cache_dir
) -> None:
    folder = cache_dir / "mcp-oauth"
    folder.mkdir(parents=True)
    (folder / "web.json").write_text(
        json.dumps({"tokens": {"access_token": "tok123", "token_type": "Bearer"}}),
        encoding="utf-8",
    )
    body = create(
        client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"})
    ).json()
    assert body["state"] == "ready"
    posts = [r for r in http_mcp.requests if r["method"] == "POST"]
    assert {r["headers"]["Authorization"] for r in posts} == {"Bearer tok123"}


def test_a_cache_file_without_tokens_does_not_count(client, http_mcp, cache_dir) -> None:
    folder = cache_dir / "mcp-oauth"
    folder.mkdir(parents=True)
    (folder / "web.json").write_text(json.dumps({"client_info": {}}), encoding="utf-8")
    body = create(
        client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"})
    ).json()
    assert body["state"] == "auth_required"


# ── POST /api/mcp/servers/{name}/oauth/connect ───────────────────────────────


def test_connect_unknown_server_is_404(client) -> None:
    response = client.post("/api/mcp/servers/zz/oauth/connect")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'zz' not found."}


def test_connect_on_a_stdio_server_is_400(client) -> None:
    create(client, "alpha", stdio_body())
    response = client.post("/api/mcp/servers/alpha/oauth/connect")
    assert response.status_code == 400
    assert response.json() == {"detail": "MCP server 'alpha' is not configured for OAuth."}


def test_connect_on_an_http_server_without_oauth_is_400(client, http_mcp) -> None:
    create(client, "web", http_server(http_mcp.url))
    response = client.post("/api/mcp/servers/web/oauth/connect")
    assert response.status_code == 400
    assert response.json() == {"detail": "MCP server 'web' is not configured for OAuth."}


def test_connect_without_a_client_id_or_registration_is_409(client, http_mcp) -> None:
    create(client, "web", http_server(http_mcp.url, oauth={}))
    response = client.post("/api/mcp/servers/web/oauth/connect")
    assert response.status_code == 409
    assert response.json() == {
        "detail": "MCP server 'web' requires OAuth app credentials. Add the OAuth app "
        "client ID/secret in Settings, then Connect OAuth."
    }
    # Python asks the configured server's own origin whether it registers clients.
    assert ("GET", "/.well-known/oauth-authorization-server") in [
        (r["method"], r["path"]) for r in http_mcp.requests
    ]


def test_connect_succeeds_when_the_server_advertises_dynamic_registration(client) -> None:
    server = FakeHttpMcp(well_known={"registration_endpoint": "http://127.0.0.1:1/register"})
    try:
        create(client, "web", http_server(server.url, oauth={}))
        response = client.post("/api/mcp/servers/web/oauth/connect")
    finally:
        server.close()
    assert response.status_code == 200
    assert response.json()["state"] == "ready"


def test_connect_with_a_client_id_connects_and_returns_the_status(
    client, http_mcp, mcp_json, scrub, snapshot
) -> None:
    create(client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"}))
    before = mcp_json.read_bytes()
    response = client.post("/api/mcp/servers/web/oauth/connect")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["tool_names"] == ["mcp_web_ping"]
    assert body["config"]["oauth"] == {"client_id": MASK, "client_secret": None}
    body["config"]["url"] = "<url>"
    from mcp_helpers import norm

    snapshot.check("oauth_connect_response.json", norm(body, scrub))
    # The file is re-saved from the same config: same bytes.
    assert lf(mcp_json.read_bytes()) == lf(before)
    # Without OAuth challenge the fixture saw no GET to the well-known document.
    assert "/.well-known/oauth-authorization-server" not in [r.get("path") for r in http_mcp.requests]


def test_connect_deletes_the_cached_oauth_file_first(client, http_mcp, cache_dir) -> None:
    create(client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"}))
    folder = cache_dir / "mcp-oauth"
    folder.mkdir(parents=True, exist_ok=True)
    cached = folder / "web.json"
    cached.write_text(
        json.dumps({"tokens": {"access_token": "old", "token_type": "Bearer"}}),
        encoding="utf-8",
    )
    response = client.post("/api/mcp/servers/web/oauth/connect")
    assert response.status_code == 200
    assert not cached.exists()
    posts = [r for r in http_mcp.requests if r["method"] == "POST"]
    assert all("Authorization" not in r["headers"] for r in posts)


def test_cache_files_are_keyed_by_the_server_name_and_survive_delete(
    client, http_mcp, cache_dir
) -> None:
    """Finding O1: deleting a server never removes ``<cache>/mcp-oauth/<name>.json``."""
    folder = cache_dir / "mcp-oauth"
    folder.mkdir(parents=True)
    cached = folder / "web.json"
    cached.write_text(
        json.dumps({"tokens": {"access_token": "old", "token_type": "Bearer"}}),
        encoding="utf-8",
    )
    create(client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"}))
    client.delete("/api/mcp/servers/web")
    assert cached.exists()
    # A new server with the same name inherits the old tokens.
    create(client, "web", http_server(http_mcp.url, oauth={"client_id": "cid"}))
    posts = [r for r in http_mcp.requests if r["method"] == "POST"]
    assert posts[-1]["headers"]["Authorization"] == "Bearer old"
