"""Dev-server preview routes and the two file-watch SSE streams."""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

from sse import collect_events
from tp_helpers import free_port, port_open, same_path

T = "/api/team"
NOT_A_DIR = "Workspace does not exist or is not a directory: "


def write_launch(root: Path, *configs: dict, folder: str = ".evoflux") -> None:
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / "launch.json").write_text(
        json.dumps({"version": "0.0.2", "configurations": list(configs)}), encoding="utf-8"
    )


def server_config(port: int, name: str = "web", **extra) -> dict:
    return {
        "name": name,
        "runtimeExecutable": sys.executable,
        "runtimeArgs": ["-m", "http.server", str(port), "--bind", "127.0.0.1"],
        "port": port,
        "startupTimeoutSeconds": 60,
        **extra,
    }


def targets(client: httpx.Client, root: Path) -> dict:
    response = client.get(f"{T}/preview/targets", params={"workspace": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(check, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError("condition not reached")


# ── preview targets ───────────────────────────────────────────────────────────


def test_targets_of_a_workspace_without_a_launch_file(client: httpx.Client, workspace: Path) -> None:
    body = targets(client, workspace)
    assert list(body) == ["workspace", "source", "suggested_source", "error", "targets"]
    assert same_path(body["workspace"], workspace)
    assert body["source"] is None and body["error"] is None and body["targets"] == []
    assert body["suggested_source"] == ".evoflux/launch.json"


def test_targets_list_configured_entries_in_file_order(client: httpx.Client, workspace: Path) -> None:
    first, second = free_port(), free_port()
    write_launch(
        workspace,
        server_config(first, "api", cwd="sub", dependsOn=None),
        {**server_config(second, "web"), "dependsOn": "api"},
    )
    body = targets(client, workspace)
    assert same_path(body["source"], workspace / ".evoflux" / "launch.json")
    rows = body["targets"]
    assert [r["name"] for r in rows] == ["api", "web"]
    assert list(rows[0]) == [
        "name", "port", "url", "command", "cwd", "depends_on", "configured", "running", "reused", "pid",
    ]
    assert rows[0]["port"] == first and rows[0]["url"] == f"http://localhost:{first}"
    assert rows[0]["cwd"] == "sub" and rows[0]["depends_on"] is None
    assert rows[1]["depends_on"] == "api"
    assert all(r["configured"] and not r["running"] and not r["reused"] and r["pid"] is None for r in rows)
    assert "http.server" in rows[0]["command"]


def test_the_claude_launch_file_is_the_fallback(client: httpx.Client, workspace: Path) -> None:
    write_launch(workspace, server_config(free_port(), "fallback"), folder=".claude")
    body = targets(client, workspace)
    assert [r["name"] for r in body["targets"]] == ["fallback"]
    assert same_path(body["source"], workspace / ".claude" / "launch.json")
    write_launch(workspace, server_config(free_port(), "primary"))
    assert [r["name"] for r in targets(client, workspace)["targets"]] == ["primary"]


def test_an_invalid_launch_file_is_reported_in_the_error_field(client: httpx.Client, workspace: Path) -> None:
    (workspace / ".evoflux").mkdir()
    (workspace / ".evoflux" / "launch.json").write_text("{not json", encoding="utf-8")
    body = targets(client, workspace)
    assert body["targets"] == [] and body["error"]
    write_launch(workspace, {"name": "x", "runtimeExecutable": "node", "port": 70000})
    assert "invalid port" in targets(client, workspace)["error"]
    write_launch(workspace, {"name": "x", "port": 3000})
    assert "missing 'runtimeExecutable'" in targets(client, workspace)["error"]
    write_launch(workspace, {"name": "x", "runtimeExecutable": "node", "port": 3000, "startupTimeoutSeconds": 0})
    assert "startupTimeoutSeconds" in targets(client, workspace)["error"]


def test_preview_validates_the_workspace(client: httpx.Client, tmp_path: Path) -> None:
    gone = tmp_path / "nope"
    for response in [
        client.get(f"{T}/preview/targets", params={"workspace": str(gone)}),
        client.post(f"{T}/preview/start", json={"workspace": str(gone), "name": "web"}),
        client.post(f"{T}/preview/stop", json={"workspace": str(gone), "name": "web"}),
    ]:
        assert response.status_code == 422
        assert response.json() == {"detail": f"{NOT_A_DIR}{gone.resolve()}"}
    assert client.get(f"{T}/preview/targets").status_code == 422
    assert client.post(f"{T}/preview/start", json={"workspace": str(tmp_path)}).status_code == 422


def test_start_of_an_unknown_name_or_without_a_file_is_a_422(client: httpx.Client, workspace: Path) -> None:
    missing = client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "web"})
    assert missing.status_code == 422
    assert "No launch config found" in missing.json()["detail"]
    write_launch(workspace, server_config(free_port(), "api"))
    unknown = client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "nope"})
    assert unknown.status_code == 422
    assert "nope" in unknown.json()["detail"] and "api" in unknown.json()["detail"]
    assert not any(p["kind"] == "preview" for p in client.get(f"{T}/processes").json()["processes"])


def test_stop_of_a_target_that_is_not_running_answers_ok(client: httpx.Client, workspace: Path) -> None:
    write_launch(workspace, server_config(free_port(), "api"))
    response = client.post(f"{T}/preview/stop", json={"workspace": str(workspace), "name": "api"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["url"] is None and body["message"]


def test_start_list_terminate_and_stop_a_dev_server(client: httpx.Client, workspace: Path) -> None:
    port = free_port()
    write_launch(workspace, server_config(port, "web"))
    started = client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "web"})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["ok"] is True and body["url"] == f"http://localhost:{port}" and body["message"]
    try:
        assert port_open(port)
        row = next(r for r in targets(client, workspace)["targets"] if r["name"] == "web")
        assert row["running"] is True and row["reused"] is False and isinstance(row["pid"], int)
        listed = [p for p in client.get(f"{T}/processes").json()["processes"] if p["kind"] == "preview"]
        assert len(listed) == 1
        process = listed[0]
        assert process["label"] == "web" and process["killable"] is True
        assert process["id"].startswith("preview_") and process["pid"] == row["pid"]
        assert process["metadata"]["port"] == port
        assert process["metadata"]["url"] == f"http://localhost:{port}"
        assert process["metadata"]["reused"] is False
        assert same_path(process["metadata"]["workspace"], workspace)
        # a second start reuses the running server
        again = client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "web"})
        assert again.status_code == 200 and again.json()["ok"] is True
        stopped = client.post(f"{T}/preview/stop", json={"workspace": str(workspace), "name": "web"})
        assert stopped.status_code == 200 and stopped.json()["ok"] is True
        wait_for(lambda: not port_open(port))
        assert not any(p["kind"] == "preview" for p in client.get(f"{T}/processes").json()["processes"])
        # start again and end it through the process list instead
        client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "web"})
        assert port_open(port)
        process_id = next(
            p["id"] for p in client.get(f"{T}/processes").json()["processes"] if p["kind"] == "preview"
        )
        assert client.delete(f"{T}/processes/{process_id}").status_code == 204
        wait_for(lambda: not port_open(port))
    finally:
        client.post(f"{T}/preview/stop", json={"workspace": str(workspace), "name": "web"})


def test_a_port_that_is_already_serving_is_reused_and_not_killable(client: httpx.Client, workspace: Path) -> None:
    import http.server
    import socketserver

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: D401, ARG002
            return

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Quiet) as outside:
        port = int(outside.server_address[1])
        thread = threading.Thread(target=outside.serve_forever, daemon=True)
        thread.start()
        try:
            write_launch(workspace, server_config(port, "web"))
            row = targets(client, workspace)["targets"][0]
            assert row["running"] is True and row["reused"] is True and row["pid"] is None
            started = client.post(f"{T}/preview/start", json={"workspace": str(workspace), "name": "web"})
            assert started.status_code == 200 and started.json()["ok"] is True
            listed = [p for p in client.get(f"{T}/processes").json()["processes"] if p["kind"] == "preview"]
            assert listed and all(p["killable"] is False and p["metadata"]["reused"] for p in listed)
            for p in listed:
                client.delete(f"{T}/processes/{p['id']}")
            assert port_open(port)  # a server EvoFlux did not start is never killed
        finally:
            outside.shutdown()


# ── file watch ────────────────────────────────────────────────────────────────


def touch_later(path: Path, delay: float = 1.5) -> threading.Thread:
    def run() -> None:
        time.sleep(delay)
        path.write_text("created\n", encoding="utf-8", newline="")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_the_workspace_watch_stream_reports_added_files(client: httpx.Client, workspace: Path) -> None:
    thread = touch_later(workspace / "new.txt")
    events = collect_events(
        client,
        f"{T}/workspace/watch?workspace={workspace}",
        until=lambda e: e.event == "fs_change" and any(c["path"] == "new.txt" for c in e.data),
        timeout_s=40,
    )
    thread.join()
    change = events[-1]
    assert change.event == "fs_change"
    assert {"type": "added", "path": "new.txt"} in change.data


def test_hidden_folders_do_not_produce_events_but_a_root_gitignore_does(
    client: httpx.Client, workspace: Path
) -> None:
    (workspace / ".hidden").mkdir()
    (workspace / "sub").mkdir()

    def run() -> None:
        time.sleep(1.5)
        (workspace / ".hidden" / "x.txt").write_text("x\n", encoding="utf-8", newline="")
        (workspace / ".gitignore").write_text("*.log\n", encoding="utf-8", newline="")
        (workspace / "sub" / "seen.txt").write_text("s\n", encoding="utf-8", newline="")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    seen: set[str] = set()

    def done(event) -> bool:
        if event.event == "fs_change":
            seen.update(c["path"] for c in event.data)
        return {".gitignore", "sub/seen.txt"} <= seen

    collect_events(client, f"{T}/workspace/watch?workspace={workspace}", until=done, timeout_s=40)
    thread.join()
    assert not any(path.startswith(".hidden") for path in seen)


def test_the_session_watch_stream_follows_the_session_folder(
    client: httpx.Client, workspace_root_of_backend: Path
) -> None:
    created = client.post(f"{T}/sessions/resolve", json={"mode": "work", "create": True})
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    folder = workspace_root_of_backend / sid
    folder.mkdir(parents=True, exist_ok=True)
    thread = touch_later(folder / "from-session.txt")
    events = collect_events(
        client,
        f"{T}/{sid}/files/watch",
        until=lambda e: e.event == "fs_change" and any(c["path"] == "from-session.txt" for c in e.data),
        timeout_s=40,
    )
    thread.join()
    assert events[-1].event == "fs_change"


def test_the_workspace_watch_validates_the_folder(client: httpx.Client, tmp_path: Path) -> None:
    gone = tmp_path / "nope"
    response = client.get(f"{T}/workspace/watch", params={"workspace": str(gone)})
    assert response.status_code == 422
    assert response.json() == {"detail": f"{NOT_A_DIR}{gone.resolve()}"}
    assert client.get(f"{T}/workspace/watch").status_code == 422


def test_the_session_watch_accepts_any_id(client: httpx.Client) -> None:
    """No UUID check: the stream opens for any text (it watches the default folder)."""
    with client.stream("GET", f"{T}/{uuid.uuid4()}/files/watch") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
