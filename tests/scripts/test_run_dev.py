from __future__ import annotations

import importlib.util
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_dev.py"
SPEC = importlib.util.spec_from_file_location("run_dev", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
run_dev = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_dev
SPEC.loader.exec_module(run_dev)


def test_build_services_propagates_api_port_to_web_and_desktop() -> None:
    services = run_dev.build_services(8123, True, "/bin/bun", "/bin/cargo")

    assert [service.name for service in services] == ["api", "web", "desktop"]
    assert services[0].command[-1] == "--no-access-log"
    assert services[0].command[services[0].command.index("--port") + 1] == "8123"
    assert services[1].env["VITE_API_PROXY_TARGET"] == "http://127.0.0.1:8123"
    assert services[2].env["EVOFLUX_DESKTOP_DEV_BACKEND_URL"] == "http://127.0.0.1:8123"


def test_supervisor_stops_siblings_when_a_service_fails(tmp_path: Path) -> None:
    marker = tmp_path / "stopped"
    long_running = run_dev.Service(
        name="long",
        command=[
            sys.executable,
            "-c",
            (
                "import pathlib, signal, sys, time; "
                f"marker = pathlib.Path({str(marker)!r}); "
                "signal.signal(signal.SIGTERM, "
                "lambda *_: (marker.write_text('yes'), sys.exit(0))); "
                "signal.signal(signal.SIGINT, "
                "lambda *_: (marker.write_text('yes'), sys.exit(0))); "
                "time.sleep(30)"
            ),
        ],
        cwd=tmp_path,
        env={},
    )
    failing = run_dev.Service(
        name="fail",
        command=[
            sys.executable,
            "-c",
            "import time; time.sleep(0.2); raise SystemExit(7)",
        ],
        cwd=tmp_path,
        env={},
    )

    assert run_dev.supervise([long_running, failing]) == 7
    if sys.platform != "win32":
        # Windows stops a sibling with TerminateProcess, which kills the
        # interpreter without delivering SIGTERM to Python signal handlers,
        # so only POSIX can observe the marker the handler writes.
        assert marker.read_text() == "yes"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "os.kill(pid, SIGINT) terminates the process unconditionally on Windows "
        "instead of delivering a real Ctrl-C, so the SIGINT-to-130 mapping cannot "
        "be observed there."
    ),
)
def test_supervisor_maps_interrupt_to_130(tmp_path: Path) -> None:
    service = run_dev.Service(
        name="long",
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env={},
    )

    def interrupt() -> None:
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        assert run_dev.supervise([service]) == 130
    finally:
        thread.join(timeout=1)


def test_listening_pids_ignores_the_localized_state_column(monkeypatch) -> None:
    netstat = (
        "  Proto  Local Address          Foreign Address        State           PID\n"
        "  TCP    0.0.0.0:8000           0.0.0.0:0              ABHÖREN         111\n"
        "  TCP    [::]:8000              [::]:0                 ABHÖREN         222\n"
        "  TCP    127.0.0.1:8000         127.0.0.1:51000        HERGESTELLT     333\n"
        "  TCP    0.0.0.0:9000           0.0.0.0:0              ABHÖREN         444\n"
    )

    class _Result:
        returncode = 0
        stdout = netstat
        stderr = ""

    monkeypatch.setattr(run_dev.sys, "platform", "win32")
    monkeypatch.setattr(run_dev.subprocess, "run", lambda *a, **k: _Result())
    assert run_dev.listening_pids(8000) == [111, 222]


def test_windows_stop_kills_the_whole_tree(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Proc:
        pid = 4242

        def poll(self):
            return None

        def terminate(self):  # pragma: no cover - must not be used
            raise AssertionError("terminate() only reaches the direct child")

    monkeypatch.setattr(run_dev.sys, "platform", "win32")
    monkeypatch.setattr(run_dev.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    run_dev.signal_process_group(_Proc(), signal.SIGTERM)
    run_dev.signal_process_group(_Proc(), getattr(signal, "SIGKILL", signal.SIGTERM))
    assert calls and all("/T" in call and "4242" in call for call in calls)
