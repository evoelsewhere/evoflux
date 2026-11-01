"""The stdio MCP server process: how it is launched, supervised and stopped.

The fake server in ``stdio_server.py`` records its argv, cwd, environment and
pid in the ``--dump`` file, so every launch parameter is observed from the
child's side. Nothing here starts a third-party server.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from mcp_helpers import (
    create,
    expected_mcp_json,
    lf,
    pid_alive,
    read_json,
    stdio_body,
    stdio_config,
    wait_for,
    wait_state,
)


def dumped(path: Path) -> dict:
    return wait_for(lambda: path.exists() and read_json(path))


def test_command_args_and_cwd_reach_the_child_unchanged(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    work = tmp_path / "work dir"
    work.mkdir()
    response = create(
        client, "alpha", stdio_body("a b", "--tool", "t", "", dump=dump, cwd=str(work))
    )
    assert response.status_code == 201
    seen = dumped(dump)
    assert seen["argv"] == ["a b", "--tool", "t", "", "--dump", str(dump)]
    assert Path(seen["cwd"]).resolve() == work.resolve()


def test_without_cwd_the_child_inherits_the_sidecar_working_directory(
    client, tmp_path
) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    assert Path(dumped(dump)["cwd"]).resolve() == (tmp_path / "cwd").resolve()


def test_cwd_is_not_confined_to_any_directory(client, tmp_path) -> None:
    """Finding C2: a ``cwd`` outside every workspace root is accepted."""
    dump = tmp_path / "dump.json"
    outside = tmp_path.parent
    response = create(client, "alpha", stdio_body(dump=dump, cwd=str(outside)))
    assert response.json()["state"] == "ready"
    assert Path(dumped(dump)["cwd"]).resolve() == outside.resolve()


def test_the_child_environment_is_not_the_sidecar_environment(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump, env={"MINE": "1"}))
    env = dumped(dump)["env"]
    assert env["MINE"] == "1"
    assert "PATH" in env
    for leaked in ("EVOFLUX_CONFIG_DIR", "EVOFLUX_DATA_DIR", "EVOFLUX_CACHE_DIR", "PYTHONPATH", "APP_ENV"):
        assert leaked not in env


def test_a_configured_path_replaces_the_resolved_user_path(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump, env={"PATH": str(tmp_path)}))
    assert dumped(dump)["env"]["PATH"] == str(tmp_path)


def test_a_command_that_does_not_exist_is_an_error_state_not_an_http_error(
    client, mcp_json
) -> None:
    response = create(
        client, "ghost", {"transport": "stdio", "command": "/nonexistent/zzz-mcp"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "error"
    assert body["error"].startswith("FileNotFoundError:")
    assert body["tool_names"] == []
    assert body["started_at"] is None
    assert body["enabled"] is True
    assert list(read_json(mcp_json)["servers"]) == ["ghost"]


def test_a_server_that_exits_during_start_reports_the_nested_error(client) -> None:
    response = create(client, "dying", stdio_body("--fail-start"))
    body = response.json()
    assert body["state"] == "error"
    assert body["error"] == "ExceptionGroup (ExceptionGroup (MCPError: Connection closed))"


def test_a_cwd_that_is_not_a_directory_is_an_error_state(client, tmp_path) -> None:
    response = create(client, "alpha", stdio_body(cwd=str(tmp_path / "nodir")))
    body = response.json()
    assert response.status_code == 201
    assert body["state"] == "error"
    assert body["error"].split(":")[0] in {"NotADirectoryError", "FileNotFoundError"}


def test_a_server_that_never_answers_is_returned_as_starting_after_15_seconds(
    client,
) -> None:
    hang = {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-c", "import time; time.sleep(120)"],
    }
    response = create(client, "slow", hang)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "starting"
    assert body["tool_names"] == []
    assert body["started_at"] is None
    assert client.get("/api/mcp/servers/slow").json()["state"] == "starting"
    # Deleting a starting runner cancels it.
    assert client.delete("/api/mcp/servers/slow").json() == {"name": "slow"}
    assert client.get("/api/mcp/servers/slow").status_code == 404


def test_delete_stops_the_child_process(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    pid = dumped(dump)["pid"]
    assert pid_alive(pid)
    client.delete("/api/mcp/servers/alpha")
    wait_for(lambda: not pid_alive(pid))


def test_restart_replaces_the_child_process(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    first = dumped(dump)["pid"]
    dump.unlink()
    assert client.post("/api/mcp/servers/alpha/restart").json()["state"] == "ready"
    second = dumped(dump)["pid"]
    assert second != first
    wait_for(lambda: not pid_alive(first))
    assert pid_alive(second)


def test_update_replaces_the_child_process(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    first = dumped(dump)["pid"]
    client.put("/api/mcp/servers/alpha", json={"server": stdio_body("--tool", "x")})
    wait_for(lambda: not pid_alive(first))


def test_disabling_stops_the_child_and_enabling_starts_a_new_one(client, tmp_path) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    first = dumped(dump)["pid"]
    dump.unlink()
    client.put("/api/mcp/servers/alpha", json={"server": stdio_body(dump=dump, enabled=False)})
    wait_for(lambda: not pid_alive(first))
    assert not dump.exists()
    body = client.put("/api/mcp/servers/alpha", json={"server": stdio_body(dump=dump)}).json()
    assert body["state"] == "ready"
    assert pid_alive(dumped(dump)["pid"])


def test_tool_names_are_prefixed_with_the_server_name(client) -> None:
    body = create(client, "my-srv", stdio_body("--tool", "a", "--tool", "b_c")).json()
    assert body["tool_names"] == ["mcp_my-srv_a", "mcp_my-srv_b_c"]


# ── Start-up, the file watcher and /apply ───────────────────────────────────


def preseed_text(servers: dict) -> str:
    return expected_mcp_json(servers).decode()


BOOT_SERVERS = {
    "on": stdio_config(),
    "off": stdio_config(enabled=False),
    "gone": {
        "args": [],
        "capabilities": [],
        "command": "/nonexistent/zzz-mcp",
        "cwd": None,
        "enabled": True,
        "env": {},
        "transport": "stdio",
    },
}


@pytest.mark.preseed(preseed_text(BOOT_SERVERS))
def test_servers_in_mcp_json_are_started_in_the_background_at_boot(client, mcp_json) -> None:
    wait_state(client, "on", "ready")
    wait_state(client, "gone", "error")
    listing = {s["name"]: s for s in client.get("/api/mcp/servers").json()["servers"]}
    # The file is sorted by key and the runners follow the file order.
    assert list(listing) == ["gone", "off", "on"]
    assert (listing["off"]["enabled"], listing["off"]["state"]) == (False, "stopped")
    assert listing["on"]["tool_names"] == ["mcp_on_echo"]
    # Start-up never rewrites the file.
    assert lf(mcp_json.read_bytes()) == preseed_text(BOOT_SERVERS).encode()


@pytest.mark.preseed("{not json")
def test_a_malformed_mcp_json_at_boot_is_not_fatal_and_apply_says_422(client) -> None:
    response = client.post("/api/mcp/apply")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Invalid JSON in ")
    assert response.json()["detail"].endswith(
        "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
    )


def test_a_server_added_by_editing_mcp_json_is_started_by_the_watcher(
    client, mcp_json
) -> None:
    mcp_json.write_bytes(preseed_text({"edited": stdio_config()}).encode())
    status = wait_state(client, "edited", "ready", timeout=30)
    assert status["tool_names"] == ["mcp_edited_echo"]
    assert status["config"]["command"] == sys.executable


def test_a_server_removed_by_editing_mcp_json_is_stopped_by_the_watcher(
    client, mcp_json, tmp_path
) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump))
    pid = dumped(dump)["pid"]
    mcp_json.write_bytes(preseed_text({}).encode())
    wait_for(lambda: client.get("/api/mcp/servers/alpha").status_code == 404, timeout=30)
    wait_for(lambda: not pid_alive(pid))


def test_apply_reads_the_file_now_and_keeps_unchanged_runners(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    before = client.get("/api/mcp/servers/alpha").json()
    stored = read_json(mcp_json)["servers"]
    stored["beta"] = stdio_config("--tool", "b")
    mcp_json.write_bytes(preseed_text(stored).encode())
    response = client.post("/api/mcp/apply")
    assert response.status_code == 200
    names = [s["name"] for s in response.json()["servers"]]
    assert names == ["alpha", "beta"]
    assert response.json()["servers"][0] == before
    assert wait_state(client, "beta", "ready")["tool_names"] == ["mcp_beta_b"]


def test_apply_with_no_changes_returns_the_current_list(client) -> None:
    create(client, "alpha", stdio_body())
    listing = client.get("/api/mcp/servers").json()
    assert client.post("/api/mcp/apply").json() == listing


def test_apply_restarts_a_server_whose_entry_changed(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    first = client.get("/api/mcp/servers/alpha").json()["started_at"]
    stored = read_json(mcp_json)["servers"]
    stored["alpha"] = stdio_config("--tool", "changed")
    mcp_json.write_bytes(preseed_text(stored).encode())
    client.post("/api/mcp/apply")
    status = wait_for(
        lambda: (s := client.get("/api/mcp/servers/alpha").json())["started_at"]
        not in (None, first)
        and s["state"] == "ready"
        and s
    )
    assert status["tool_names"] == ["mcp_alpha_changed"]


@pytest.mark.parametrize(
    ("content", "start"),
    [
        ('{"servers": []}', "1 validation error for MCPConfig"),
        ('{"servers": {}, "extra": 1}', "1 validation error for MCPConfig"),
        ("[]", None),
        ('{"servers": {"1bad": {"transport": "stdio", "command": "x"}}}', "Invalid MCP server name '1bad'"),
        ('{"servers": {"a": {"transport": "stdio", "command": ""}}}', "4 validation errors for MCPConfig"),
    ],
)
def test_apply_rejects_a_file_that_does_not_validate_with_422(
    client, mcp_json, content, start
) -> None:
    mcp_json.write_text(content, encoding="utf-8")
    response = client.post("/api/mcp/apply")
    assert response.status_code == 422
    detail = response.json()["detail"]
    if start is None:
        assert detail.endswith("mcp.json: expected a JSON object at top level")
    else:
        assert detail.startswith(start)


def test_apply_with_a_malformed_file_keeps_the_running_servers(client, mcp_json) -> None:
    create(client, "alpha", stdio_body())
    mcp_json.write_text("{bad", encoding="utf-8")
    assert client.post("/api/mcp/apply").status_code == 422
    # The runner is untouched; the status route is the one that reads the file.
    assert client.get("/api/mcp/servers/nope").status_code == 404


def test_http_header_names_and_stdio_fields_survive_a_round_trip_through_the_file(
    client, mcp_json
) -> None:
    create(client, "alpha", stdio_body(capabilities=["z", "a"], env={"E": ""}))
    first = json.loads(lf(mcp_json.read_bytes()))
    client.post("/api/mcp/apply")
    assert json.loads(lf(mcp_json.read_bytes())) == first
    assert os.path.exists(mcp_json)
