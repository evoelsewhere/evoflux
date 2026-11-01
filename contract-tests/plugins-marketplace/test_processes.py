"""The processes an enabled plugin starts, and the registries it feeds.

Only the stdlib fake MCP server in this folder is ever started. Remote
(`streamable-http`) servers are only pointed at a closed loopback port.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from plugin_helpers import (
    PYTHON_NAME,
    install,
    servers,
    wait_for,
    write_mcp_plugin,
    write_plugin,
)

psutil = pytest.importorskip("psutil")
pytestmark = pytest.mark.usefixtures("needs_python_on_path")

CRED_NAMESPACE = "org.evoelsewhere.evoflux.credentials"
SETTLED = ("ready", "error", "auth_required")


def runtime_name(installation_id: str, server: str = "fake") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", server).strip("_-") or "server"
    suffix = hashlib.sha256(server.encode()).hexdigest()[:8]
    return f"plugin_{installation_id[:8]}_{slug[:40]}_{suffix}"


def settled(client, name: str = "fake", timeout: float = 40.0) -> dict:
    found = wait_for(
        lambda: (lambda s: s if s and s["state"] in SETTLED else None)(servers(client).get(name)),
        timeout=timeout,
    )
    assert found, f"server {name!r} never settled: {servers(client)}"
    return found


def record(platform_dir: Path, installation_id: str) -> dict:
    return json.loads(
        (platform_dir / "data" / installation_id / "started.json").read_text(encoding="utf-8")
    )


def new_pid(platform_dir: Path, installation_id: str, old: int, timeout: float = 40.0) -> int:
    def changed():
        try:
            pid = record(platform_dir, installation_id)["pid"]
        except (OSError, ValueError):
            return None
        return pid if pid != old else None

    found = wait_for(changed, timeout=timeout)
    assert found, "the server process was not restarted"
    return found


def gone(pid: int, timeout: float = 30.0) -> bool:
    return bool(wait_for(lambda: not psutil.pid_exists(pid), timeout=timeout))


def test_enabling_starts_the_declared_stdio_server(client, src, platform_dir) -> None:
    root = write_mcp_plugin(
        src / "m",
        "m",
        args=["${PLUGIN_ROOT}/fake_mcp_server.py", "${PLUGIN_DATA}/arg"],
        env={"FROM_PLUGIN": "${PLUGIN_ROOT}/x", "PLAIN": "value"},
        cwd="./sub",
    )
    (root / "sub").mkdir()
    created = install(client, root, enabled=True)["installation"]
    status = settled(client)
    assert status == {
        "installation_id": created["id"],
        "plugin_name": "m",
        "server_name": "fake",
        "runtime_name": runtime_name(created["id"]),
        "transport": "stdio",
        "enabled": True,
        "state": "ready",
        "error": None,
        "tool_names": [f"mcp_{runtime_name(created['id'])}_echo"],
        "started_at": status["started_at"],
    }
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00", status["started_at"])
    started = record(platform_dir, created["id"])
    installed_root = str(Path(created["root"]).resolve())
    data_root = str((platform_dir / "data" / created["id"]).resolve())
    # argv excludes the script path, whose ``${PLUGIN_ROOT}`` expansion is proven by it running.
    assert started["argv"] == [f"{data_root}/arg"]
    assert Path(started["cwd"]) == Path(installed_root) / "sub"
    env = started["env"]
    assert env["PLUGIN_ROOT"] == installed_root
    assert env["PLUGIN_DATA"] == data_root
    assert env["FROM_PLUGIN"] == f"{installed_root}/x"
    assert env["PLAIN"] == "value"
    assert Path(data_root).is_dir()


def test_the_server_does_not_inherit_the_backend_environment(client, src, platform_dir) -> None:
    created = install(client, write_mcp_plugin(src / "m", "m"), enabled=True)["installation"]
    settled(client)
    env = record(platform_dir, created["id"])["env"]
    assert not [key for key in env if key.upper().startswith("EVOFLUX")]
    assert "PYTHONPATH" not in env
    assert "DATABASE_URL" not in env
    assert {"PLUGIN_ROOT", "PLUGIN_DATA", "PATH"} <= set(env)


def test_server_status_is_listed_through_the_mcp_routes_too(client, src) -> None:
    created = install(client, write_mcp_plugin(src / "m", "m"), enabled=True)["installation"]
    settled(client)
    listed = client.get("/api/mcp/servers").json()["servers"]
    assert listed == [
        {
            "name": runtime_name(created["id"]),
            "transport": "stdio",
            "enabled": True,
            "state": "ready",
            "error": None,
            "tool_names": [f"mcp_{runtime_name(created['id'])}_echo"],
            "started_at": listed[0]["started_at"],
            "config": None,
            "source": "plugin",
            "plugin_installation_id": created["id"],
            "plugin_name": "m",
            "plugin_server_name": "fake",
        }
    ]


def test_disabling_stops_the_process_and_removes_the_status(client, src, platform_dir) -> None:
    created = install(client, write_mcp_plugin(src / "m", "m"), enabled=True)["installation"]
    settled(client)
    pid = record(platform_dir, created["id"])["pid"]
    assert psutil.pid_exists(pid)
    assert client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": False}).status_code == 200
    assert wait_for(lambda: not servers(client), timeout=30)
    assert gone(pid)


def test_enabling_later_starts_it(client, src, platform_dir) -> None:
    created = install(client, write_mcp_plugin(src / "m", "m"), enabled=False)["installation"]
    assert servers(client) == {}
    client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": True})
    assert settled(client)["state"] == "ready"


def test_uninstall_stops_the_process_before_removing_files(client, src, platform_dir) -> None:
    created = install(client, write_mcp_plugin(src / "m", "m"), enabled=True)["installation"]
    settled(client)
    pid = record(platform_dir, created["id"])["pid"]
    response = client.delete(f"/api/plugins/{created['id']}")
    assert response.status_code == 200
    assert gone(pid)
    assert not (platform_dir / "installed" / created["id"]).exists()
    assert servers(client) == {}
    assert (platform_dir / "data" / created["id"] / "started.json").exists()


def test_update_restarts_the_server_from_the_new_package(client, src, platform_dir) -> None:
    root = write_mcp_plugin(src / "m", "m")
    created = install(client, root, enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])["pid"]
    newer = write_mcp_plugin(src / "m2", "m")
    manifest = json.loads((newer / "plugin.json").read_text(encoding="utf-8"))
    manifest["version"] = "2.0.0"
    (newer / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    response = client.post(f"/api/plugins/{created['id']}/update", json={"path": str(newer)})
    assert response.status_code == 200
    new_pid(platform_dir, created["id"], first)
    assert gone(first)
    cwd = Path(record(platform_dir, created["id"])["cwd"])
    assert cwd.name == "2.0.0"


def test_a_workspace_write_restarts_even_when_mcp_json_is_unchanged(client, src, platform_dir) -> None:
    root = write_mcp_plugin(src / "dev", "dev")
    created = install(client, root, mode="link", enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])["pid"]
    response = client.put(
        "/api/plugins/workspace/file",
        json={"root": str(root), "path": "notes.txt", "content": "x"},
    )
    assert response.status_code == 200
    second = new_pid(platform_dir, created["id"], first)
    assert gone(first)
    assert psutil.pid_exists(second)


def test_editing_mcp_json_through_the_workspace_changes_what_is_executed(client, src, platform_dir) -> None:
    """Pinned (S1): a workspace write is enough to change the command line of a running plugin."""
    root = write_mcp_plugin(src / "dev", "dev")
    created = install(client, root, mode="link", enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])["pid"]
    config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    config["mcpServers"]["fake"]["args"] = ["fake_mcp_server.py", "--injected", "1"]
    response = client.put(
        "/api/plugins/workspace/file",
        json={"root": str(root), "path": "mcp.json", "content": json.dumps(config)},
    )
    assert response.status_code == 200
    new_pid(platform_dir, created["id"], first)
    assert record(platform_dir, created["id"])["argv"] == ["--injected", "1"]


def test_an_external_edit_to_a_linked_package_is_picked_up_by_the_watcher(client, src, platform_dir) -> None:
    root = write_mcp_plugin(src / "dev", "dev")
    created = install(client, root, mode="link", enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])["pid"]
    config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    config["mcpServers"]["fake"]["args"] = ["fake_mcp_server.py", "edited"]
    (root / "mcp.json").write_text(json.dumps(config, indent=4), encoding="utf-8")
    new_pid(platform_dir, created["id"], first)
    assert record(platform_dir, created["id"])["argv"] == ["edited"]


def test_a_broken_linked_package_keeps_the_last_good_server_running(client, src, platform_dir) -> None:
    root = write_mcp_plugin(src / "dev", "dev")
    created = install(client, root, mode="link", enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])["pid"]
    response = client.put(
        "/api/plugins/workspace/file",
        json={"root": str(root), "path": "mcp.json", "content": "{broken"},
    )
    assert response.status_code == 200
    assert response.json()["inspection"]["mcp_servers"] == []
    status = settled(client)
    assert status["state"] == "ready"
    assert psutil.pid_exists(record(platform_dir, created["id"])["pid"])
    assert first is not None


def test_credentials_are_injected_as_environment_variables(client, src, platform_dir) -> None:
    fields = [
        {"key": "token", "label": "T", "type": "secret", "env": "MY_TOKEN"},
        {"key": "flag", "label": "F", "type": "boolean", "env": "MY_FLAG"},
    ]
    root = write_plugin(
        src / "c",
        "c",
        mcp={"fake": {"type": "stdio", "command": PYTHON_NAME, "args": ["fake_mcp_server.py"]}},
        manifest_extra={"extensions": {CRED_NAMESPACE: {"fields": fields}}},
    )
    from plugin_helpers import FAKE_SERVER

    (root / "fake_mcp_server.py").write_bytes(FAKE_SERVER.read_bytes())
    created = install(client, root, enabled=True)["installation"]
    settled(client)
    first = record(platform_dir, created["id"])
    assert "MY_TOKEN" not in first["env"]
    client.put(
        f"/api/plugins/{created['id']}/credentials",
        json={"values": {"token": "s3cret", "flag": False}},
    )
    new_pid(platform_dir, created["id"], first["pid"])
    env = record(platform_dir, created["id"])["env"]
    assert env["MY_TOKEN"] == "s3cret"
    assert env["MY_FLAG"] == "false"


def test_plugin_root_and_data_win_over_declared_values(client, src, platform_dir) -> None:
    """Credential env cannot name them, and ``mcp.json`` env that does is invalid."""
    root = write_mcp_plugin(src / "m", "m", env={"PLUGIN_ROOT": "/elsewhere"})
    created = install(client, root, mode="link", enabled=True)["installation"]
    listed = client.get("/api/plugins").json()
    component = listed["plugins"][0]["inspection"]["mcp_servers"][0]
    assert component["valid"] is False
    assert [d["code"] for d in component["diagnostics"]] == ["mcp-reserved-env"]
    assert listed["mcp_servers"] == []
    assert not (platform_dir / "data" / created["id"] / "started.json").exists()


@pytest.mark.parametrize(
    ("server", "code"),
    [
        ({"type": "stdio", "command": "/usr/bin/env"}, "mcp-command-invalid"),
        ({"type": "stdio", "command": "..\\evil.exe"}, "mcp-command-invalid"),
        ({"type": "stdio", "command": "./../escape"}, "mcp-command-escapes-root"),
        ({"type": "stdio", "command": "ok", "cwd": "/tmp"}, "mcp-cwd-invalid"),
        ({"type": "stdio", "command": "ok", "cwd": "./.."}, "mcp-cwd-escapes-root"),
        ({"type": "stdio", "command": "ok", "cwd": "${PLUGIN_ROOT}/../x"}, "mcp-cwd-escapes-root"),
        ({"type": "streamable-http", "url": "http://example.com/mcp"}, "mcp-url-insecure"),
        ({"type": "streamable-http", "url": "https://u:p@example.com/mcp"}, "mcp-url-unsafe"),
        ({"type": "streamable-http", "url": "ftp://example.com"}, "mcp-url-invalid"),
        ({"type": "streamable-http", "url": "https://example.com", "headers": {"bad name": "x"}}, "mcp-header-invalid"),
        ({"type": "websocket", "url": "wss://example.com"}, "mcp-server-invalid"),
    ],
)
def test_invalid_server_definitions_are_never_started(client, src, server, code) -> None:
    root = write_plugin(src / "inv", "inv", mcp={"s": server})
    install(client, root, mode="link", enabled=True)
    listed = client.get("/api/plugins").json()
    component = listed["plugins"][0]["inspection"]["mcp_servers"][0]
    assert component["valid"] is False
    assert code in [d["code"] for d in component["diagnostics"]]
    assert listed["mcp_servers"] == []


def test_the_legacy_sse_transport_is_valid_but_skipped(client, src) -> None:
    root = write_plugin(
        src / "sse", "sse", mcp={"s": {"type": "sse", "url": "https://example.com/sse"}}
    )
    install(client, root, mode="link", enabled=True)
    listed = client.get("/api/plugins").json()
    component = listed["plugins"][0]["inspection"]["mcp_servers"][0]
    assert component["valid"] is True
    assert [d["code"] for d in component["diagnostics"]] == ["mcp-transport-unsupported"]
    assert listed["mcp_servers"] == []


def test_a_missing_executable_is_an_error_state_not_a_failed_request(client, src) -> None:
    root = write_plugin(src / "nc", "nc", mcp={"s": {"type": "stdio", "command": "no-such-binary-xyz"}})
    created = install(client, root, enabled=True)["installation"]
    status = settled(client, "s")
    assert status["state"] == "error"
    assert status["error"]
    assert status["tool_names"] == []
    assert status["started_at"] is None
    assert status["runtime_name"] == runtime_name(created["id"], "s")


def test_a_remote_server_that_refuses_connections_is_an_error_state(client, src) -> None:
    root = write_plugin(
        src / "rm", "rm", mcp={"r": {"type": "streamable-http", "url": "http://127.0.0.1:9/mcp"}}
    )
    install(client, root, enabled=True)
    status = settled(client, "r")
    assert status["state"] == "error"
    assert status["transport"] == "http"
    assert status["tool_names"] == []


def test_each_plugin_gets_its_own_runtime_name(client, src) -> None:
    first = install(client, write_mcp_plugin(src / "one", "one"), enabled=True)["installation"]
    second = install(client, write_mcp_plugin(src / "two", "two"), enabled=True)["installation"]
    wait_for(lambda: len(client.get("/api/plugins").json()["mcp_servers"]) == 2, timeout=40)
    names = sorted(s["runtime_name"] for s in client.get("/api/plugins").json()["mcp_servers"])
    assert names == sorted([runtime_name(first["id"]), runtime_name(second["id"])])


def test_enabled_plugin_skills_reach_the_skills_registry(client, src) -> None:
    root = write_plugin(src / "sk", "sk", skills=("from-plugin",))
    created = install(client, root, enabled=False)["installation"]

    def listing():
        return {s["name"]: s for s in client.get("/api/skills").json()["skills"]}

    assert "from-plugin" not in listing()
    client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": True})
    skill = listing()["from-plugin"]
    assert skill["source"] == "plugin"
    assert skill["plugin_id"] == created["id"]
    assert skill["editable"] is False
    client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": False})
    assert "from-plugin" not in listing()
    client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": True})
    client.delete(f"/api/plugins/{created['id']}")
    assert "from-plugin" not in listing()
