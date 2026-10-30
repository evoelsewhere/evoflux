"""Gateway proxy contract (Task 10; Review Focus 1-3).

Runs with ``TARGET=gateway``. Tests marked "fake" put the gateway in front of
``fake_upstream.py``; the others in front of the real Python sidecar.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
from websockets.sync.client import connect

from backends import GATEWAY_HARNESS, REPO_ROOT, Backend

BACKEND_UNAVAILABLE = {"detail": "Backend is restarting.", "code": "backend_unavailable"}
UPLOAD_BYTES = 200 * 1024 * 1024
RSS_GROWTH_LIMIT = 32 * 1024 * 1024
# CSI sequences, and OSC sequences ended by BEL or ESC \ (ConPTY titles).
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def python_upstream(tmp_path: Path) -> dict[str, int]:
    """``{"pid": …, "port": …}`` of the Python child the gateway runs now."""
    return json.loads((tmp_path / "gateway-python.json").read_text(encoding="utf-8"))


def rss_bytes(pid: int) -> int:
    """Resident set size (Windows: working set) of ``pid``."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
        assert handle, f"OpenProcess({pid}) failed"
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            ok = psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            assert ok, "GetProcessMemoryInfo failed"
            return int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        match = re.search(r"VmRSS:\s+(\d+) kB", status.read_text())
        assert match
        return int(match.group(1)) * 1024
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip()) * 1024


def auth(backend: Backend) -> dict[str, str]:
    return {"Authorization": f"Bearer {backend.token}"}


def test_all_health_contracts_pass_through_gateway() -> None:
    """Rerun T3's health suite with the gateway in front of Python."""
    env = dict(os.environ)
    env["TARGET"] = "gateway"
    env.setdefault("EVOFLUX_CONTRACT_SERVER_BIN", str(GATEWAY_HARNESS))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "contract-tests/health",
            "-q",
            "-rs",
            "--no-cov",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Exit code 5 would mean nothing was collected; skips are listed by -rs.
    assert "SKIPPED" not in result.stdout, result.stdout


def test_sse_events_not_buffered(fake_backend: Backend) -> None:
    """fake: the upstream sends event 1, waits 1 s, sends event 2."""
    start = time.monotonic()
    with httpx.stream("GET", f"{fake_backend.base_url}/fake/sse", timeout=30.0) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"
        lines = response.iter_lines()
        first = next(line for line in lines if line.startswith("data:"))
        first_at = time.monotonic() - start
        second = next(line for line in lines if line.startswith("data:"))
        second_at = time.monotonic() - start
    assert first == "data: one"
    assert first_at < 0.3, f"first event after {first_at:.3f}s"
    assert second == "data: two"
    assert second_at >= 0.9


def test_client_disconnect_reaches_upstream(fake_backend: Backend) -> None:
    """fake: closing the client mid-stream is seen upstream within 2 s."""
    with httpx.stream("GET", f"{fake_backend.base_url}/fake/sse", timeout=30.0) as response:
        next(line for line in response.iter_lines() if line.startswith("data:"))
        closed_at = time.time()
    deadline = time.monotonic() + 5
    seen = None
    while time.monotonic() < deadline and seen is None:
        seen = httpx.get(f"{fake_backend.base_url}/fake/sse-status").json()["disconnected_at"]
        time.sleep(0.05)
    assert seen is not None, "upstream never saw the disconnect"
    assert seen - closed_at < 2.0, f"disconnect seen after {seen - closed_at:.2f}s"


def test_websocket_terminal_round_trip(backend: Backend) -> None:
    session = uuid.uuid4()
    url = backend.base_url.replace("http://", "ws://")
    url = f"{url}/api/team/{session}/terminal?_token={backend.token}"
    output = ""
    with connect(url, open_timeout=30) as ws:
        # Wait for the shell's banner/prompt so the keystrokes are not lost.
        first = ws.recv(timeout=30)
        output += first.decode("utf-8", "replace") if isinstance(first, bytes) else ""
        ws.send(json.dumps({"type": "input", "data": "echo hi\r"}))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            if isinstance(frame, bytes):
                output += frame.decode("utf-8", "replace")
            # The PTY echoes "echo hi"; the command's own output is a bare "hi" line.
            plain = ANSI.sub("", output)
            if re.search(r"(?m)^hi\r?$", plain):
                break
        else:
            raise AssertionError(f"no 'hi' line in terminal output: {output!r}")
        ws.send(json.dumps({"type": "close"}))


def test_websocket_rejection_is_pythons(backend: Backend) -> None:
    """Python refuses the socket before accept; the client sees Python's 403."""
    url = backend.base_url.replace("http://", "ws://")
    url = f"{url}/api/team/{uuid.uuid4()}/terminal?_token=wrong"
    try:
        with connect(url, open_timeout=30):
            raise AssertionError("socket opened with a wrong token")
    except Exception as exc:  # noqa: BLE001 — websockets raises InvalidStatus
        response = getattr(exc, "response", None)
        assert response is not None, repr(exc)
        assert response.status_code == 403


def _chunks(total: int, size: int = 1 << 20) -> Iterator[bytes]:
    block = b"x" * size
    sent = 0
    while sent < total:
        piece = block[: min(size, total - sent)]
        sent += len(piece)
        yield piece


def test_large_upload_streams(fake_backend: Backend) -> None:
    """fake: a 200 MB chunked upload passes with gateway RSS growth under 32 MB."""
    baseline = rss_bytes(fake_backend.pid)
    peak = baseline
    done = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not done.is_set():
            peak = max(peak, rss_bytes(fake_backend.pid))
            time.sleep(0.02)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        response = httpx.post(
            f"{fake_backend.base_url}/fake/upload",
            content=_chunks(UPLOAD_BYTES),
            timeout=120.0,
        )
    finally:
        done.set()
        sampler.join()
    assert response.status_code == 200
    assert response.json() == {"bytes": UPLOAD_BYTES}
    growth = peak - baseline
    assert growth < RSS_GROWTH_LIMIT, f"gateway RSS grew {growth / 2**20:.1f} MiB"


def test_python_request_size_limit_answers(backend: Backend) -> None:
    """Python's RequestSizeLimitMiddleware still answers a 200 MB upload itself."""
    response = httpx.post(
        f"{backend.base_url}/api/import/upload",
        content=_chunks(UPLOAD_BYTES),
        headers={**auth(backend), "Content-Length": str(UPLOAD_BYTES)},
        timeout=120.0,
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large."}


def test_python_crash_returns_502_then_recovers(backend: Backend, tmp_path: Path) -> None:
    live = f"{backend.base_url}/api/health/live"
    assert httpx.get(live, headers=auth(backend), timeout=30.0).status_code == 200
    pid = python_upstream(tmp_path)["pid"]
    os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
    start = time.monotonic()
    response = httpx.get(live, headers=auth(backend), timeout=5.0)
    elapsed = time.monotonic() - start
    assert response.status_code == 502
    assert response.json() == BACKEND_UNAVAILABLE
    assert elapsed < 1.0, f"502 after {elapsed:.2f}s"
    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        try:
            status = httpx.get(live, headers=auth(backend), timeout=5.0).status_code
        except httpx.HTTPError:
            status = None
        if status == 200:
            break
        time.sleep(0.2)
    assert status == 200, "python did not come back within 15 s"
    assert python_upstream(tmp_path)["pid"] != pid


def test_direct_python_access_rejected(backend: Backend, tmp_path: Path) -> None:
    port = python_upstream(tmp_path)["port"]
    response = httpx.get(
        f"http://127.0.0.1:{port}/api/health/live", headers=auth(backend), timeout=30.0
    )
    assert response.status_code == 403
