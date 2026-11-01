"""``POST /api/mcp/app-tools/call`` and the unhandled-500 behaviour of a bad ``mcp.json``."""

from __future__ import annotations

import pytest

from mcp_helpers import create, fresh, seed_mcp_app, stdio_body, wait_state

NIL = "00000000-0000-0000-0000-000000000000"


def call(client, session, server="alpha", tool="echo", tool_call_id="call-1", **extra):
    body = {
        "session_id": session,
        "tool_call_id": tool_call_id,
        "server": server,
        "tool": tool,
        **extra,
    }
    return client.post("/api/mcp/app-tools/call", json=body)


def test_a_bound_app_tool_call_returns_the_dumped_result(client, tmp_path) -> None:
    create(client, "alpha", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha")
    response = call(client, session, arguments={"k": 1, "nested": {"a": [1, 2]}})
    assert response.status_code == 200
    assert response.json() == {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": '{"arguments": {"k": 1, "nested": {"a": [1, 2]}}, "tool": "echo"}',
                }
            ],
            "isError": False,
            "resultType": "complete",
        }
    }


def test_arguments_default_to_an_empty_object(client, tmp_path) -> None:
    create(client, "alpha", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha")
    text = call(client, session).json()["result"]["content"][0]["text"]
    assert text == '{"arguments": {}, "tool": "echo"}'


def test_an_http_server_works_the_same_way(client, tmp_path, http_mcp) -> None:
    create(client, "web", {"transport": "http", "url": http_mcp.url})
    session = seed_mcp_app(tmp_path, "web")
    response = call(client, session, server="web", tool="ping", arguments={"x": "y"})
    assert response.status_code == 200
    assert response.json()["result"]["content"][0]["text"] == (
        '{"arguments": {"x": "y"}, "tool": "ping"}'
    )


def test_the_tool_name_is_the_unprefixed_name(client, tmp_path) -> None:
    create(client, "alpha", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha")
    for name in ("mcp_alpha_echo", "nope", "ECHO"):
        response = call(client, session, tool=name)
        assert response.status_code == 403
        assert response.json() == {"detail": f"MCP tool '{name}' is not available."}


def test_a_server_that_differs_from_the_bound_one_is_403(client, tmp_path) -> None:
    create(client, "alpha", stdio_body())
    create(client, "beta", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha")
    response = call(client, session, server="beta")
    assert response.status_code == 403
    assert response.json() == {"detail": "MCP app server mismatch."}


def test_a_bound_server_that_is_not_running_is_404(client, tmp_path) -> None:
    session = seed_mcp_app(tmp_path, "ghost")
    response = call(client, session, server="ghost")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server not found."}


def test_a_disabled_server_is_409_not_connected(client, tmp_path) -> None:
    create(client, "off", stdio_body(enabled=False))
    session = seed_mcp_app(tmp_path, "off")
    response = call(client, session, server="off")
    assert response.status_code == 409
    assert response.json() == {"detail": "MCP server 'off' is not connected."}


def test_a_server_in_error_state_is_409_not_connected(client, tmp_path) -> None:
    create(client, "bad", {"transport": "stdio", "command": "/nonexistent/zzz-mcp"})
    session = seed_mcp_app(tmp_path, "bad")
    response = call(client, session, server="bad")
    assert response.status_code == 409
    assert response.json() == {"detail": "MCP server 'bad' is not connected."}


def test_the_check_order_is_artifact_then_mismatch_then_server(client, tmp_path) -> None:
    session = seed_mcp_app(tmp_path, "alpha")
    assert call(client, session, server="other", tool_call_id="zzz").status_code == 404
    assert call(client, session, server="other").status_code == 403


def test_an_unknown_tool_call_id_is_404(client, tmp_path) -> None:
    create(client, "alpha", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha")
    response = call(client, session, tool_call_id="zzz")
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP app artifact not found."}


def test_an_unknown_session_is_404(client) -> None:
    response = call(client, NIL)
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP app artifact not found."}


def test_a_non_uuid_session_id_is_422(client) -> None:
    response = call(client, "not-a-uuid")
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid session_id."}


@pytest.mark.parametrize(
    ("role", "extra"),
    [("assistant", None), ("tool", {}), ("tool", {"mcp_app": "alpha"}), ("tool", {"mcp_app": None})],
)
def test_only_a_tool_message_with_an_mcp_app_object_is_an_artifact(
    client, tmp_path, role, extra
) -> None:
    create(client, "alpha", stdio_body())
    session = seed_mcp_app(tmp_path, "alpha", role=role, extra=extra)
    response = call(client, session)
    assert response.status_code == 404
    assert response.json() == {"detail": "MCP app artifact not found."}


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"tool_call_id": "t", "server": "s", "tool": "y"}, ["body", "session_id"]),
        ({"session_id": NIL, "server": "s", "tool": "y"}, ["body", "tool_call_id"]),
        ({"session_id": NIL, "tool_call_id": "t", "tool": "y"}, ["body", "server"]),
        ({"session_id": NIL, "tool_call_id": "t", "server": "s"}, ["body", "tool"]),
        ({"session_id": NIL, "tool_call_id": "t", "server": "", "tool": "y"}, ["body", "server"]),
        ({"session_id": NIL, "tool_call_id": "t", "server": "s", "tool": ""}, ["body", "tool"]),
        (
            {"session_id": NIL, "tool_call_id": "t", "server": "s", "tool": "y", "arguments": []},
            ["body", "arguments"],
        ),
        (
            {"session_id": NIL, "tool_call_id": "t", "server": "s", "tool": "y", "more": 1},
            ["body", "more"],
        ),
    ],
)
def test_app_call_body_validation_is_422(client, body, loc) -> None:
    response = client.post("/api/mcp/app-tools/call", json=body)
    assert response.status_code == 422
    assert [d["loc"] for d in response.json()["detail"]] == [loc]


# ── Finding M1: a malformed mcp.json is an unhandled 500 on most routes ──────


@pytest.fixture
def broken(client, mcp_json):
    create(client, "alpha", stdio_body())
    wait_state(client, "alpha", "ready")
    mcp_json.write_text("{bad", encoding="utf-8")
    return client


def test_listing_with_a_malformed_file_is_a_500(broken) -> None:
    response = broken.get("/api/mcp/servers")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/mcp/servers/alpha", None),
        ("POST", "/api/mcp/servers", {"name": "b", "server": {"transport": "stdio", "command": "x"}}),
        ("PUT", "/api/mcp/servers/alpha", {"server": {"transport": "stdio", "command": "x"}}),
        ("DELETE", "/api/mcp/servers/alpha", None),
        ("POST", "/api/mcp/servers/alpha/restart", None),
        ("POST", "/api/mcp/servers/alpha/oauth/connect", None),
    ],
)
def test_every_route_that_reads_the_file_is_a_500_when_it_is_malformed(
    broken, method, path, body
) -> None:
    with fresh(broken) as http:
        response = http.request(method, path, json=body)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_a_missing_server_is_still_404_with_a_malformed_file(broken) -> None:
    """Only the live-runner lookup is tried first, so an unknown name never reads the file."""
    with fresh(broken) as http:
        assert http.get("/api/mcp/servers/zz").status_code == 404


def test_a_deleted_mcp_json_reads_as_an_empty_config(client, mcp_json) -> None:
    mcp_json.unlink()
    assert client.get("/api/mcp/servers").json() == {"servers": []}
    created = create(client, "alpha", stdio_body())
    assert created.status_code == 201
    assert mcp_json.exists()
