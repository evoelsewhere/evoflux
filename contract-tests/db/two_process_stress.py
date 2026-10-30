"""Run the actual Python API and the Rust writers against one SQLite file."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path

import httpx

from backends import start_backend
from conftest import configure_backend_provider
from mock_provider.server import MockProvider
from sse import collect_events

TABLES = ("chat_sessions", "session_messages", "session_folders", "memory_facts")


def wait_for_backend_exit(pid: int) -> None:
    """Wait for the handshake PID, not just the Windows venv launcher."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the PID no longer exists
            return
        raise ctypes.WinError(error)
    try:
        result = kernel.WaitForSingleObject(handle, 15000)
        if result != 0:  # WAIT_OBJECT_0
            raise RuntimeError(f"backend PID {pid} did not exit: wait result {result}")
    finally:
        kernel.CloseHandle(handle)


def counts(db: Path) -> dict[str, int]:
    try:
        with closing(sqlite3.connect(db, timeout=30)) as conn:
            return {
                name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name in TABLES
            }
    except sqlite3.Error as exc:
        exc.add_note(
            f"SQLite error: {getattr(exc, 'sqlite_errorname', 'unknown')} "
            f"({getattr(exc, 'sqlite_errorcode', 'unknown')})"
        )
        raise


def run_two_process_stress(
    db: Path, temp: Path, executable: Path, seconds: int = 120, mode: str = "concurrent"
) -> dict:
    backend = start_backend("python", temp / "concurrent", db)
    shared = temp / "concurrent" / "data" / "evoflux.db"
    provider = MockProvider()
    process = None
    try:
        ready_deadline = time.monotonic() + 90
        while not any(
            "optional_services_ready total_ms=" in line for line in tuple(backend.log)
        ):
            if backend.process.poll() is not None or time.monotonic() >= ready_deadline:
                raise RuntimeError("Python backend did not finish optional startup")
            time.sleep(0.1)
        provider.load("openai_text_hello")
        with httpx.Client(
            base_url=backend.base_url,
            headers={"Authorization": f"Bearer {backend.token}"},
            timeout=60,
            trust_env=False,
        ) as client:
            configure_backend_provider(client, provider)
            before = counts(shared)
            process = subprocess.Popen(
                [
                    str(executable),
                    "--db",
                    str(shared),
                    "--seconds",
                    str(seconds),
                    "--writers",
                    "4",
                    "--report",
                    "json",
                    "--mode",
                    mode,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            deadline = time.monotonic() + seconds
            session_ids = set()
            message_ids = set()
            while time.monotonic() < deadline:
                sent = client.post(
                    "/api/team/chat", data={"message": f"db-stress-{uuid.uuid4()}"}
                )
                sent.raise_for_status()
                sid = sent.json()["session_id"]
                events = collect_events(
                    client,
                    f"/api/team/{sid}/stream",
                    until=lambda e: e.event in ("done", "error"),
                    timeout_s=60,
                )
                assert any(e.event == "done" for e in events), (
                    f"agent turn failed: {events}"
                )
                history = client.get(f"/api/team/{sid}/history")
                history.raise_for_status()
                messages = history.json()["lead"]["messages"]
                assert any(m["role"] == "user" for m in messages)
                session_ids.add(sid)
                message_ids.update(m["id"] for m in messages)
            stdout, stderr = process.communicate(timeout=seconds + 60)
            if process.returncode:
                raise RuntimeError(
                    f"Rust writer failed ({process.returncode}): {stderr}"
                )
            report = json.loads(stdout)
            assert report["failed"] == 0
            expected = dict(before)
            for table, count in report["counts"].items():
                expected[table] += count
            expected["chat_sessions"] += len(session_ids)
            expected["session_messages"] += len(message_ids)
            print(
                json.dumps(
                    {
                        "mode": mode,
                        "rust": report,
                        "python_sessions": len(session_ids),
                        "python_messages": len(message_ids),
                        "expected_counts": expected,
                    }
                ),
                flush=True,
            )
        backend.stop()
        wait_for_backend_exit(backend.pid)
        return {
            "db": shared,
            "actual_counts": counts(shared),
            "expected_counts": expected,
            "rust_acknowledged": report["acknowledged"],
            "python_sessions": len(session_ids),
            "python_messages": len(message_ids),
            "rust": report,
        }
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        backend.stop()
        provider.close()
