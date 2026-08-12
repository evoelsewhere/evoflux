#!/usr/bin/env python3
"""Run EvoFlux source development services as one supervised process group.

This script is launched through ``uv run`` by the root Makefile. It validates
all required tools before touching ports, prefixes each service's output, and
stops every owned process when one service exits or the user presses Ctrl-C.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
TAURI_DIR = ROOT / "desktop" / "src-tauri"
VITE_PORT = 5173
SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Service:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the EvoFlux API and Vite, optionally with Tauri."
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8000,
        help="Loopback port for the source API (default: 8000).",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Also run the Tauri shell against the source API.",
    )
    args = parser.parse_args()
    if not 1 <= args.api_port <= 65535:
        parser.error("--api-port must be between 1 and 65535")
    if args.api_port == VITE_PORT:
        parser.error(f"--api-port cannot use Vite's port {VITE_PORT}")
    return args


def require_executable(name: str, install_hint: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"'{name}' not found — {install_hint}")
    return executable


def preflight(desktop: bool) -> tuple[str, str | None]:
    require_executable("lsof", "install lsof and ensure it is on PATH")
    bun = require_executable("bun", "install from https://bun.sh")
    if not desktop:
        return bun, None

    cargo = require_executable("cargo", "install Rust via https://rustup.rs")
    check = subprocess.run(
        [cargo, "tauri", "--version"],
        cwd=TAURI_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode != 0:
        raise RuntimeError(
            "'cargo tauri' not found — install with "
            "'cargo install tauri-cli --version ^2.0 --locked'"
        )
    return bun, cargo


def listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"could not inspect port {port}: {detail}")
    return [int(value) for value in result.stdout.split()]


def stop_dev_ports(ports: list[int]) -> None:
    for port in ports:
        pids = listening_pids(port)
        if not pids:
            continue
        print(f"stopping processes on port {port}: {' '.join(map(str, pids))}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and listening_pids(port):
            time.sleep(0.2)
        remaining = listening_pids(port)
        if remaining:
            print(
                f"force stopping processes on port {port}: "
                f"{' '.join(map(str, remaining))}"
            )
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def build_services(
    api_port: int, desktop: bool, bun: str, cargo: str | None
) -> list[Service]:
    api_url = f"http://127.0.0.1:{api_port}"
    services = [
        Service(
            name="api",
            command=[
                sys.executable,
                "-m",
                "uvicorn",
                "app.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
                "--reload",
                "--reload-dir",
                "app",
                "--no-access-log",
            ],
            cwd=ROOT,
            env={},
        ),
        Service(
            name="web",
            command=[bun, "dev"],
            cwd=WEB_DIR,
            env={"VITE_API_PROXY_TARGET": api_url},
        ),
    ]
    if desktop:
        assert cargo is not None
        services.append(
            Service(
                name="desktop",
                command=[cargo, "tauri", "dev", "-c", "tauri.dev.conf.json"],
                cwd=TAURI_DIR,
                env={"EVOFLUX_DESKTOP_DEV_BACKEND_URL": api_url},
            )
        )
    return services


def stream_output(name: str, output: BinaryIO, lock: threading.Lock) -> None:
    prefix = f"[{name}] ".encode()
    try:
        for line in iter(output.readline, b""):
            with lock:
                sys.stdout.buffer.write(prefix + line)
                sys.stdout.buffer.flush()
    finally:
        output.close()


def signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def stop_processes(
    processes: list[subprocess.Popen[bytes]], initial_signal: signal.Signals
) -> None:
    for process in processes:
        signal_process_group(process, initial_signal)
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            signal_process_group(process, signal.SIGKILL)
    for process in processes:
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def spawn_service(service: Service) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(service.env)
    return subprocess.Popen(
        service.command,
        cwd=service.cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def supervise(services: list[Service]) -> int:
    processes: list[subprocess.Popen[bytes]] = []
    output_threads: list[threading.Thread] = []
    output_lock = threading.Lock()
    received_signal: signal.Signals | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal received_signal
        received_signal = signal.Signals(signum)

    previous_handlers = {
        sig: signal.signal(sig, handle_signal) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for service in services:
            process = spawn_service(service)
            processes.append(process)
            assert process.stdout is not None
            thread = threading.Thread(
                target=stream_output,
                args=(service.name, process.stdout, output_lock),
                daemon=True,
            )
            thread.start()
            output_threads.append(thread)

        while received_signal is None:
            for service, process in zip(services, processes, strict=True):
                returncode = process.poll()
                if returncode is None:
                    continue
                stop_processes(processes, signal.SIGTERM)
                for thread in output_threads:
                    thread.join(timeout=1.0)
                exit_code = returncode if returncode >= 0 else 128 - returncode
                if exit_code != 0:
                    print(f"{service.name} exited with status {exit_code}", file=sys.stderr)
                return exit_code
            time.sleep(0.1)

        stop_processes(processes, received_signal)
        for thread in output_threads:
            thread.join(timeout=1.0)
        return 128 + int(received_signal)
    except (OSError, subprocess.SubprocessError):
        stop_processes(processes, signal.SIGTERM)
        raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if any(process.poll() is None for process in processes):
            stop_processes(processes, signal.SIGTERM)


def main() -> int:
    args = parse_args()
    try:
        bun, cargo = preflight(args.desktop)
        stop_dev_ports([args.api_port, VITE_PORT])
        services = build_services(args.api_port, args.desktop, bun, cargo)
        return supervise(services)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
