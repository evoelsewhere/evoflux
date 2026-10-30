"""Heavy-load scenarios for the responsiveness gate (design §8).

``FREEZE_SCENARIOS`` maps a name to a factory taking the running ``Backend`` and
returning a context manager. While the context is open, background threads keep
the backend busy the way the named situation does; the gate measures
``/api/health/live`` and a history page from the test thread meanwhile.

Adding a scenario (hook for the freeze diagnosis, Phase 0 task 1)::

    @freeze_scenario("name_from_the_diagnosis")
    def _my_scenario(backend: Backend) -> ContextManager[None]:
        return _hammer(backend, [...])

Whatever the diagnosis proves freezes v3.1.1 belongs here, so the gate keeps
measuring the real cause. A scenario that stalls v3 is listed in
``V3_STALLS`` so the test marks it ``xfail(strict=True)`` for ``python`` only.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import ContextManager
from urllib.parse import quote

import httpx

from backends import Backend

from perf_repo import ensure_large_repo
from perf_seed import (
    BIG_SESSION_ID,
    MCP_SERVER_NAME,
    MCP_SESSION_ID,
    MCP_TOOL_CALL_ID,
)

Scenario = Callable[[Backend], ContextManager[None]]
FREEZE_SCENARIOS: dict[str, Scenario] = {}
# Names whose v3.1.1 behaviour is a known stall, measured with the open-loop
# probes of ``perf_measure.probe_open_loop``. ``cold_start`` is not a
# ``FREEZE_SCENARIOS`` entry (it needs a fresh backend) but is gated the same way.
V3_STALLS: dict[str, str] = {
    "cold_start": "v3 stall: the MCP SDK import blocks the event loop for 1.1-1.9 s after the handshake (T1 analysis; 3/3 open-loop runs)",
    "large_repo_open": "v3 stall: /api/health/live p99 110-280 ms and history p99 > 2x idle while a 20k-file repo opens (3/3 open-loop runs, Windows reference machine)",
    "long_tool_run": "v3 stall: /api/health/live p99 60-180 ms while an MCP tool runs for 20 s (3/3 open-loop runs)",
    "large_history_page": "v3 stall: /api/health/live p99 170-390 ms under repeated large history reads (3/3 open-loop runs)",
    "concurrent_history_reads": "v3 stall: /api/health/live p99 270-370 ms with 20 concurrent history readers (3/3 open-loop runs)",
    "hung_mcp_server": "v3 stall: /api/health/live p99 74-97 ms while a hung MCP server is restarted (2 of 3 open-loop runs; the first passed)",
}

HISTORY_PATH = f"/api/team/{BIG_SESSION_ID}/history"
HISTORY_READERS = 20
LONG_TOOL_SECONDS = 20
RAMP_SECONDS = 1.5


def freeze_scenario(name: str) -> Callable[[Scenario], Scenario]:
    def register(factory: Scenario) -> Scenario:
        FREEZE_SCENARIOS[name] = factory
        return factory

    return register


@contextmanager
def _hammer(
    backend: Backend,
    requests: list[tuple[str, str, dict | None]],
    threads: int = 1,
    timeout: float = 60.0,
) -> Iterator[None]:
    """Run ``requests`` (method, path, json) in a loop on ``threads`` threads."""
    stop = threading.Event()

    def loop(offset: int) -> None:
        with httpx.Client(
            base_url=backend.base_url,
            headers={"Authorization": f"Bearer {backend.token}"},
            timeout=timeout,
        ) as http:
            index = offset
            while not stop.is_set():
                method, path, body = requests[index % len(requests)]
                index += 1
                try:
                    http.request(method, path, json=body)
                except httpx.HTTPError:
                    pass

    workers = [
        threading.Thread(target=loop, args=(n,), daemon=True) for n in range(threads)
    ]
    for worker in workers:
        worker.start()
    stop.wait(RAMP_SECONDS)
    try:
        yield
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=timeout + 5)


def _workspace(path: str) -> str:
    return quote(path, safe="")


@freeze_scenario("large_repo_open")
def large_repo_open(backend: Backend) -> ContextManager[None]:
    """Opening a 20k-file repository: tree, status, git status/log/branches.

    Replaces the repository index rebuild of the design text; v3.1.1 has none.
    """
    workspace = _workspace(str(ensure_large_repo()))
    paths = [
        f"/api/team/workspace/validate?workspace={workspace}",
        f"/api/team/workspace/files/list?workspace={workspace}",
        f"/api/team/workspace/status?workspace={workspace}",
        f"/api/team/workspace/git/repository?workspace={workspace}",
        f"/api/team/workspace/git/changes?workspace={workspace}",
        f"/api/team/workspace/git/log?workspace={workspace}",
    ]
    return _hammer(backend, [("GET", p, None) for p in paths], threads=3)


def _register_slow_mcp(backend: Backend, name: str, mode: str) -> None:
    from pathlib import Path

    script = str(Path(__file__).with_name("fake_mcp.py"))
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": f"Bearer {backend.token}"},
        timeout=60.0,
    ) as http:
        response = http.post(
            "/api/mcp/servers",
            json={
                "name": name,
                "server": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [script, mode],
                },
            },
        )
        response.raise_for_status()


@freeze_scenario("long_tool_run")
def long_tool_run(backend: Backend) -> ContextManager[None]:
    """A tool that keeps running for ``LONG_TOOL_SECONDS`` on an MCP server."""
    _register_slow_mcp(backend, MCP_SERVER_NAME, "slow")
    call = (
        "POST",
        "/api/mcp/app-tools/call",
        {
            "session_id": MCP_SESSION_ID,
            "tool_call_id": MCP_TOOL_CALL_ID,
            "server": MCP_SERVER_NAME,
            "tool": "work",
            "arguments": {"seconds": LONG_TOOL_SECONDS},
        },
    )
    return _hammer(backend, [call], threads=2, timeout=LONG_TOOL_SECONDS + 30)


@freeze_scenario("large_history_page")
def large_history_page(backend: Backend) -> ContextManager[None]:
    """Back-to-back reads of the biggest history page (~160 rows, ~190 KB)."""
    return _hammer(backend, [("GET", HISTORY_PATH, None)], threads=2)


@freeze_scenario("concurrent_history_reads")
def concurrent_history_reads(backend: Backend) -> ContextManager[None]:
    """Twenty clients reading history at once."""
    return _hammer(backend, [("GET", HISTORY_PATH, None)], threads=HISTORY_READERS)


@freeze_scenario("hung_mcp_server")
def hung_mcp_server(backend: Backend) -> ContextManager[None]:
    """An MCP server that never answers; restarts are requested repeatedly."""
    _register_slow_mcp(backend, "perf-hung", "hang")
    restart = ("POST", "/api/mcp/servers/perf-hung/restart", None)
    listing = ("GET", "/api/mcp/servers", None)
    return _hammer(backend, [restart, listing], threads=2, timeout=60.0)
