"""Run a provider parity case against the mock provider on either backend.

Each case runs in a child process with an isolated home, config and working
directory, so no developer ``.env`` or provider key reaches it:

* ``python``: ``python_driver.py`` (the Python provider stack);
* ``rust``: the ``provider_parity`` example of ``evoflux-area-providers``.

The child prints the event list as JSON; the requests come from the mock.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from mock_provider.server import MockProvider

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parent
ROOT = CONTRACT.parent
#: Inside the crate, so its unit tests (and cargo-mutants' copy of ``server/``)
#: can replay the recordings without ``contract-tests/``.
PARITY_DIR = ROOT / "server" / "crates" / "area-providers" / "tests" / "parity"
RUST_BIN = (
    ROOT
    / "server"
    / "target"
    / "debug"
    / "examples"
    / ("provider_parity.exe" if os.name == "nt" else "provider_parity")
)

#: Variables a child may inherit; everything else (keys, .env paths) is dropped.
_PASS_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")


def recording_path(name: str) -> Path:
    if name.startswith("providers/"):
        return HERE / "recordings" / f"{name.removeprefix('providers/')}.jsonl"
    return CONTRACT / "mock_provider" / "recordings" / f"{name}.jsonl"


def parse_recording(name: str | None) -> list[list[dict[str, Any]]]:
    """The responses ``MockProvider.load`` makes of a recording."""
    if name is None:
        return []
    responses: list[list[dict[str, Any]]] = []
    for raw in recording_path(name).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        entry = json.loads(raw)
        if "response" in entry or not responses:
            responses.append([])
            if "response" in entry:
                continue
        responses[-1].append(entry)
    return responses


def load_recording(mock: MockProvider, name: str) -> None:
    """``MockProvider.load`` for a recording in either directory."""
    relative = os.path.relpath(recording_path(name).with_suffix(""), CONTRACT / "mock_provider" / "recordings")
    mock.load(relative)


def closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def build_rust_example() -> None:
    subprocess.run(
        ["cargo", "build", "-q", "-p", "evoflux-area-providers", "--example", "provider_parity"],
        cwd=ROOT / "server",
        check=True,
    )


def run_child(target: str, case: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k.upper() in _PASS_ENV}
        env.update(
            HOME=tmp,
            USERPROFILE=tmp,
            APPDATA=tmp,
            LOCALAPPDATA=tmp,
            EVOFLUX_DATA_DIR=str(Path(tmp) / "data"),
            EVOFLUX_CONFIG_DIR=str(Path(tmp) / "config"),
            EVOFLUX_STATE_DIR=str(Path(tmp) / "state"),
            EVOFLUX_CACHE_DIR=str(Path(tmp) / "cache"),
            PYTHONIOENCODING="utf-8",
            RUST_LOG="off",
        )
        case_file = Path(tmp) / "case.json"
        case_file.write_text(json.dumps(case), encoding="utf-8")
        if target == "python":
            argv = [sys.executable, str(HERE / "python_driver.py"), str(case_file), base_url]
        elif target == "rust":
            argv = [str(RUST_BIN), str(case_file), base_url]
        else:
            raise ValueError(f"no provider driver for TARGET={target}")
        done = subprocess.run(
            argv, cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        if done.returncode != 0:
            raise RuntimeError(f"{target} driver failed:\n{done.stderr[-4000:]}")
        return json.loads(done.stdout.strip().splitlines()[-1])


def run(target: str, case: dict[str, Any]) -> dict[str, Any]:
    mock = MockProvider()
    try:
        if case["refuse"]:
            base_url = closed_port_url()
        else:
            load_recording(mock, case["recording"])
            base_url = f"{mock.base_url}/v1"
        events = run_child(target, case, base_url)
        return {"requests": list(mock.requests), "events": events}
    finally:
        mock.close()
