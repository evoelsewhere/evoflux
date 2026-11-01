"""Shared builders for the ``/api/mcp`` contract.

Every path the API returns lives under the test's temp dir, so ``Scrub`` turns
it into ``<tmp>`` (with ``/`` separators) before anything is compared.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

STDIO_SERVER = Path(__file__).with_name("stdio_server.py")

#: Every route of the unit as (method, path, JSON body). The bodies are valid,
#: so a 401 proves authentication runs before anything else.
ROUTES: list[tuple[str, str, object]] = [
    ("GET", "/api/mcp/servers", None),
    ("GET", "/api/mcp/servers/x", None),
    ("POST", "/api/mcp/servers", {"name": "x", "server": {"transport": "stdio", "command": "x"}}),
    ("PUT", "/api/mcp/servers/x", {"server": {"transport": "stdio", "command": "x"}}),
    ("DELETE", "/api/mcp/servers/x", None),
    ("POST", "/api/mcp/servers/x/restart", None),
    ("POST", "/api/mcp/servers/x/oauth/connect", None),
    ("POST", "/api/mcp/apply", None),
    (
        "POST",
        "/api/mcp/app-tools/call",
        {
            "session_id": "00000000-0000-0000-0000-000000000000",
            "tool_call_id": "t",
            "server": "x",
            "tool": "y",
        },
    ),
]


def stdio_body(
    *extra_args: str,
    dump: Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """A ``server`` body that runs the fake stdio server with this interpreter."""
    args = [str(STDIO_SERVER), *extra_args]
    if dump is not None:
        args += ["--dump", str(dump)]
    body: dict[str, Any] = {"transport": "stdio", "command": sys.executable, "args": args}
    body.update(fields)
    return body


def create(client, name: str, server: dict[str, Any]):
    return client.post("/api/mcp/servers", json={"name": name, "server": server})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for(predicate, timeout: float = 20.0, interval: float = 0.1):
    """Poll ``predicate`` until it returns something truthy."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the condition")
        time.sleep(interval)


def wait_state(client, name: str, state: str, timeout: float = 20.0) -> dict[str, Any]:
    def probe():
        response = client.get(f"/api/mcp/servers/{name}")
        if response.status_code == 200 and response.json()["state"] == state:
            return response.json()
        return None

    return wait_for(probe, timeout)


class Scrub:
    """Replace the temp dir in JSON-able values and fold path separators."""

    def __init__(self, tmp: Path) -> None:
        self._roots = {str(tmp), str(tmp.resolve())}

    def text(self, value: str) -> str:
        for root in self._roots:
            pattern = re.escape(root) + r"[^\s'\"<>|?*:]*"
            value = re.sub(
                pattern,
                lambda m: m.group(0).replace(root, "<tmp>").replace("\\", "/"),
                value,
            )
        return value

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        return value


def lf(data: bytes) -> bytes:
    """The bytes Python writes on POSIX.

    ``save_config`` and ``_save_env_values`` write in text mode, so on Windows
    ``\n`` is written as ``\r\n``. Folding it back gives the POSIX bytes.
    """
    return data.replace(b"\r\n", b"\n") if os.name == "nt" else data


def expected_mcp_json(servers: dict[str, Any]) -> bytes:
    """What ``save_config`` writes: sorted keys, two-space indent, final newline."""
    return (json.dumps({"servers": servers}, indent=2, sort_keys=True) + "\n").encode()


def stdio_config(*extra_args: str, **fields: Any) -> dict[str, Any]:
    """The stored ``mcp.json`` entry for ``stdio_body(*extra_args, **fields)``."""
    body = stdio_body(*extra_args, **fields)
    return {
        "args": body["args"],
        "capabilities": body.get("capabilities", []),
        "command": body["command"],
        "cwd": body.get("cwd"),
        "enabled": body.get("enabled", True),
        "env": body.get("env", {}),
        "transport": "stdio",
    }


def norm(value: Any, scrub: Scrub) -> Any:
    """Make a status body comparable: interpreter, script, temp dir, timestamp."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "started_at" and item:
                out[key] = "<ts>"
            else:
                out[key] = norm(item, scrub)
        return out
    if isinstance(value, list):
        return [norm(item, scrub) for item in value]
    if isinstance(value, str):
        value = value.replace(sys.executable, "<python>").replace(str(STDIO_SERVER), "<stdio_server>")
        return scrub(value)
    return value


def seed_mcp_app(
    tmp: Path,
    server: str,
    tool_call_id: str = "call-1",
    *,
    role: str = "tool",
    extra: dict[str, Any] | None = None,
) -> str:
    """Insert a chat session with one tool message that carries an MCP app.

    The route reads ``session_messages.extra['mcp_app']``; nothing else in the
    public API creates one without a real tool run, so the test writes the row.
    """
    session_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    con = sqlite3.connect(tmp / "data" / "evoflux.db")
    try:
        con.execute(
            "insert into chat_sessions (id, created_at, updated_at) values (?, ?, ?)",
            (session_id.hex, now, now),
        )
        con.execute(
            "insert into session_messages (id, session_id, role, tool_call_id, extra, created_at)"
            " values (?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                session_id.hex,
                role,
                tool_call_id,
                json.dumps({"mcp_app": {"server": server}} if extra is None else extra),
                now,
            ),
        )
        con.commit()
    finally:
        con.close()
    return str(session_id)


def pid_alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).is_running() and (
            psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return False


def fresh(client):
    """A new client with the same base URL and token.

    uvicorn closes the connection after an unhandled exception (a 500), so the
    next request on the same keep-alive connection fails with a read error.
    """
    import httpx

    return httpx.Client(base_url=str(client.base_url), headers=dict(client.headers), timeout=30.0)
