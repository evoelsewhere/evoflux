from __future__ import annotations

import importlib.util
import os
import signal
import sys
import threading
import time
from pathlib import Path


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
    assert marker.read_text() == "yes"


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
