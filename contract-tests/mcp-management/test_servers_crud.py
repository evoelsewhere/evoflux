"""``/api/mcp/servers``: create, read, update, delete and the saved ``mcp.json``."""

from __future__ import annotations

import pytest

from mcp_helpers import (
    create,
    expected_mcp_json,
    lf,
    norm,
    read_json,
    stdio_body,
    stdio_config,
    wait_state,
)

STATUS_KEYS = {
    "name", "transport", "enabled", "state", "error", "tool_names", "started_at",
    "config", "source", "plugin_installation_id", "plugin_name",
    "plugin_server_name",
}  # fmt: skip


def test_fresh_install_has_an_empty_seeded_mcp_json_and_no_servers(
    client, mcp_json
) -> None:
    assert read_json(mcp_json) == {"servers": {}}
    response = client.get("/api/mcp/servers")
    assert response.status_code == 200
    assert response.json() == {"servers": []}


def test_create_stdio_returns_201_with_live_status_and_the_saved_config(
    client, mcp_json, scrub, snapshot
) -> None:
    response = create(client, "alpha", stdio_body(capabilities=["browser", "x"]))
    assert response.status_code == 201
    body = response.json()
    assert set(body) == STATUS_KEYS
    assert body["state"] == "ready"
    assert body["tool_names"] == ["mcp_alpha_echo"]
    assert body["source"] == "global"
    assert body["error"] is None
    snapshot.check("create_stdio_response.json", norm(body, scrub))
    assert lf(mcp_json.read_bytes()) == expected_mcp_json(
        {"alpha": stdio_config(capabilities=["browser", "x"])}
    )


def test_create_http_returns_status_with_masked_headers(
    client, mcp_json, http_mcp, scrub, snapshot
) -> None:
    server = {
        "transport": "http",
        "url": http_mcp.url,
        "headers": {"Authorization": "Bearer abc", "X-A": "lit"},
        "capabilities": ["browser"],
    }
    response = create(client, "web", server)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "ready"
    assert body["tool_names"] == ["mcp_web_ping"]
    assert body["config"]["headers"] == {"Authorization": "********", "X-A": "********"}
    assert body["config"]["oauth"] is None
    body["config"]["url"] = "<url>"
    snapshot.check("create_http_response.json", norm(body, scrub))
    # Header values are stored in mcp.json verbatim: only the response masks them.
    stored = read_json(mcp_json)["servers"]["web"]
    assert stored["headers"] == {"Authorization": "Bearer abc", "X-A": "lit"}
    assert lf(mcp_json.read_bytes()) == expected_mcp_json(
        {
            "web": {
                "capabilities": ["browser"],
                "enabled": True,
                "headers": {"Authorization": "Bearer abc", "X-A": "lit"},
                "oauth": None,
                "transport": "http",
                "url": http_mcp.url,
            }
        }
    )


def test_get_and_list_return_the_same_status_in_creation_order(client) -> None:
    for name in ("zeta", "alpha", "mid"):
        assert create(client, name, stdio_body()).status_code == 201
    listing = client.get("/api/mcp/servers").json()
    assert list(listing) == ["servers"]
    assert [s["name"] for s in listing["servers"]] == ["zeta", "alpha", "mid"]
    for server in listing["servers"]:
        single = client.get(f"/api/mcp/servers/{server['name']}")
        assert single.status_code == 200
        assert single.json() == server


def test_get_unknown_server_is_404(client) -> None:
    response = client.get("/api/mcp/servers/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'nope' not found."}


@pytest.mark.parametrize("name", ["1bad", "a b", "-x", "_x", "a.b", "a/b", "é"])
def test_invalid_server_name_is_422_and_nothing_is_saved(
    client, mcp_json, name
) -> None:
    before = mcp_json.read_bytes()
    response = create(client, name, stdio_body())
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Invalid MCP server name {name!r}: must match "
        "^[a-zA-Z][a-zA-Z0-9_-]*$ "
        "(letters, digits, underscore, hyphen; starting with a letter)."
    }
    assert mcp_json.read_bytes() == before


@pytest.mark.parametrize("name", ["a", "A1", "a-b_c", "x" * 200])
def test_valid_server_names_are_accepted(client, name) -> None:
    response = create(client, name, stdio_body(enabled=False))
    assert response.status_code == 201
    assert response.json()["name"] == name


def test_duplicate_name_is_409_and_the_file_is_unchanged(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    before = mcp_json.read_bytes()
    response = create(client, "alpha", stdio_body("--tool", "other"))
    assert response.status_code == 409
    assert response.json() == {"detail": "MCP server 'alpha' already exists."}
    assert mcp_json.read_bytes() == before


def test_a_disabled_server_is_saved_and_never_started(
    client, tmp_path, scrub, snapshot
) -> None:
    dump = tmp_path / "dump.json"
    response = create(client, "off", stdio_body(dump=dump, enabled=False))
    assert response.status_code == 201
    body = response.json()
    assert (body["enabled"], body["state"], body["tool_names"], body["started_at"]) == (
        False, "stopped", [], None,
    )  # fmt: skip
    snapshot.check("create_disabled_response.json", norm(body, scrub))
    assert not dump.exists()


@pytest.mark.parametrize(
    ("body", "loc", "kind"),
    [
        ({"name": "a", "server": {"command": "x"}}, ["body", "server"], "union_tag_not_found"),
        (
            {"name": "a", "server": {"transport": "stdio", "command": "x", "bogus": 1}},
            ["body", "server", "stdio", "bogus"],
            "extra_forbidden",
        ),
        (
            {"name": "a", "server": {"transport": "stdio", "command": ""}},
            ["body", "server", "stdio", "command"],
            "string_too_short",
        ),
        (
            {"name": "a", "server": {"transport": "http", "url": ""}},
            ["body", "server", "http", "url"],
            "string_too_short",
        ),
        (
            {"name": "", "server": {"transport": "stdio", "command": "x"}},
            ["body", "name"],
            "string_too_short",
        ),
        (
            {"name": "a", "server": {"transport": "stdio", "command": "x", "args": "x"}},
            ["body", "server", "stdio", "args"],
            "list_type",
        ),
        (
            {"name": "a", "server": {"transport": "stdio", "command": "x", "env": {"A": 1}}},
            ["body", "server", "stdio", "env", "A"],
            "string_type",
        ),
        (
            {"name": "a", "server": {"transport": "sse", "url": "x"}},
            ["body", "server"],
            "union_tag_invalid",
        ),
        (
            {"name": "a", "server": {"transport": "stdio", "command": "x"}, "more": 1},
            ["body", "more"],
            "extra_forbidden",
        ),
        (
            {"name": "a", "server": {"type": "stdio", "command": "x"}},
            ["body", "server"],
            "union_tag_not_found",
        ),
        ({"server": {"transport": "stdio", "command": "x"}}, ["body", "name"], "missing"),
        ({"name": "a"}, ["body", "server"], "missing"),
    ],
)
def test_invalid_bodies_are_fastapi_422s_and_save_nothing(
    client, mcp_json, body, loc, kind
) -> None:
    before = mcp_json.read_bytes()
    response = client.post("/api/mcp/servers", json=body)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [d["loc"] for d in detail] == [loc]
    assert [d["type"] for d in detail] == [kind]
    assert mcp_json.read_bytes() == before


def test_update_replaces_the_config_and_restarts_the_runner(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    first = client.get("/api/mcp/servers/alpha").json()["started_at"]
    response = client.put(
        "/api/mcp/servers/alpha",
        json={"server": stdio_body("--tool", "one", "--tool", "two", capabilities=["c"])},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_names"] == ["mcp_alpha_one", "mcp_alpha_two"]
    assert body["started_at"] != first
    assert body["config"]["capabilities"] == ["c"]
    assert read_json(mcp_json)["servers"]["alpha"]["args"][-4:] == [
        "--tool", "one", "--tool", "two",
    ]  # fmt: skip


def test_update_can_switch_transport_and_disable(client, mcp_json, http_mcp) -> None:
    create(client, "alpha", stdio_body())
    response = client.put(
        "/api/mcp/servers/alpha",
        json={"server": {"transport": "http", "url": http_mcp.url}},
    )
    assert response.status_code == 200
    assert response.json()["transport"] == "http"
    assert response.json()["tool_names"] == ["mcp_alpha_ping"]
    response = client.put(
        "/api/mcp/servers/alpha",
        json={"server": {"transport": "http", "url": http_mcp.url, "enabled": False}},
    )
    body = response.json()
    assert (body["enabled"], body["state"], body["tool_names"]) == (False, "stopped", [])
    assert read_json(mcp_json)["servers"]["alpha"]["enabled"] is False


def test_update_unknown_server_is_404_and_does_not_create_it(client, mcp_json) -> None:
    before = mcp_json.read_bytes()
    response = client.put("/api/mcp/servers/zz", json={"server": stdio_body()})
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'zz' not found."}
    assert mcp_json.read_bytes() == before


def test_update_does_not_validate_the_name_in_the_path(client) -> None:
    """Only POST validates names; PUT/DELETE just look the name up in the file."""
    response = client.put("/api/mcp/servers/a%20b", json={"server": stdio_body()})
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'a b' not found."}


def test_delete_removes_the_entry_and_returns_the_name(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    create(client, "beta", stdio_body())
    response = client.delete("/api/mcp/servers/alpha")
    assert response.status_code == 200
    assert response.json() == {"name": "alpha"}
    assert list(read_json(mcp_json)["servers"]) == ["beta"]
    assert client.get("/api/mcp/servers/alpha").status_code == 404
    names = [s["name"] for s in client.get("/api/mcp/servers").json()["servers"]]
    assert names == ["beta"]


def test_delete_unknown_server_is_404(client) -> None:
    response = client.delete("/api/mcp/servers/zz")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'zz' not found."}


def test_delete_a_disabled_server(client, mcp_json) -> None:
    create(client, "off", stdio_body(enabled=False))
    assert client.delete("/api/mcp/servers/off").json() == {"name": "off"}
    assert read_json(mcp_json) == {"servers": {}}


def test_restart_returns_the_fresh_status(client) -> None:
    create(client, "alpha", stdio_body())
    first = client.get("/api/mcp/servers/alpha").json()
    response = client.post("/api/mcp/servers/alpha/restart")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["started_at"] != first["started_at"]
    assert {**body, "started_at": None} == {**first, "started_at": None}


def test_restart_unknown_server_is_404(client) -> None:
    response = client.post("/api/mcp/servers/zz/restart")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server 'zz' not found."}


def test_restart_of_a_disabled_server_stays_stopped(client) -> None:
    create(client, "off", stdio_body(enabled=False))
    body = client.post("/api/mcp/servers/off/restart").json()
    assert (body["enabled"], body["state"]) == (False, "stopped")


def test_methods_and_paths_outside_the_contract(client) -> None:
    assert client.patch("/api/mcp/servers/x", json={}).status_code == 405
    assert client.put("/api/mcp/servers", json={}).status_code == 405
    assert client.delete("/api/mcp/servers").status_code == 405
    assert client.get("/api/mcp/apply").status_code == 405
    assert client.get("/api/mcp/servers/x/restart").status_code == 405
    assert client.get("/api/mcp/servers/x/oauth/connect").status_code == 405
    assert client.get("/api/mcp/app-tools/call").status_code == 405
    assert client.get("/api/mcp/unknown").status_code == 404
    assert client.get("/api/mcp").status_code == 404


def test_wait_state_helper_sees_the_runner(client) -> None:
    create(client, "alpha", stdio_body())
    assert wait_state(client, "alpha", "ready")["name"] == "alpha"


def test_two_servers_can_expose_the_same_prefixed_tool_name(client) -> None:
    """Finding T1: ``mcp_<server>_<tool>`` is ambiguous across ``_`` boundaries."""
    first = create(client, "a", stdio_body("--tool", "b_c")).json()
    second = create(client, "a_b", stdio_body("--tool", "c")).json()
    assert first["tool_names"] == second["tool_names"] == ["mcp_a_b_c"]
