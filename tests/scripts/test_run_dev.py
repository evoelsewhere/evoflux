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
    assert (
        services[2].env["EVOFLUX_DESKTOP_DEV_BACKEND_URL"]
        == "http://127.0.0.1:8123"
    )


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
                "time.sleep(30)"
            ),
        ],
        cwd=tmp_path,
        env={},
    )
    failing = run_dev.Service(
        name="fail",
        command=[sys.executable, "-c", "import time; time.sleep(0.2); raise SystemExit(7)"],
        cwd=tmp_path,
        env={},
    )

    assert run_dev.supervise([long_running, failing]) == 7

    if sys.platform == "win32":
        # Windows has no process-group signal that reaches an arbitrary
        # SIGTERM handler (CTRL_BREAK_EVENT only reaches a SIGBREAK
        # handler) — the supervisor force-kills the whole tree instead
        # (see signal_process_group's docstring), so there is no graceful
        # marker to check here. The meaningful assertion already
        # happened above: supervise() returned 7 instead of hanging on
        # the "long" service's sleep(30).
        pass
    else:
        assert marker.read_text() == "yes"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "os.kill(getpid(), SIGINT) maps to GenerateConsoleCtrlEvent"
        "(CTRL_C_EVENT) on Windows, which the OS broadcasts to every"
        " process attached to the current console — including this test"
        " process itself, outside of run_dev.py's own control — rather"
        " than delivering a signal this test can scope to just the child"
        " it spawned. Crashes the interpreter instead of exercising"
        " run_dev.py's own SIGINT handling."
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
