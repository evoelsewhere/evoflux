"""Gateway-only fixtures (Task 10). These tests run with ``TARGET=gateway`` only.

The backend is the gateway test binary (``evoflux-gateway-harness``, built by
``cd server && cargo build -p evoflux-gateway``) unless
``EVOFLUX_CONTRACT_SERVER_BIN`` names another one. ``fake_backend`` puts the
gateway in front of ``fake_upstream.py`` instead of the real sidecar.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from backends import GATEWAY_HARNESS, Backend, BackendStartError, start_backend

FAKE_UPSTREAM = Path(__file__).resolve().parent / "fake_upstream.py"

if os.environ.get("TARGET", "python") != "gateway":
    collect_ignore_glob = ["test_*.py"]


def _binary() -> Path:
    override = os.environ.get("EVOFLUX_CONTRACT_SERVER_BIN")
    binary = Path(override) if override else GATEWAY_HARNESS
    if not binary.exists():
        pytest.fail(
            f"{binary} is missing; build it with: cd server && cargo build -p evoflux-gateway",
            pytrace=False,
        )
    return binary


def _start(tmp_path: Path, extra_env: dict[str, str]) -> Backend:
    state = tmp_path / "gateway-python.json"
    env = {"EVOFLUX_GATEWAY_STATE_FILE": str(state), **extra_env}
    try:
        return start_backend("gateway", tmp_path, binary=_binary(), extra_env=env)
    except BackendStartError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    started = _start(tmp_path, {})
    try:
        yield started
    finally:
        started.stop()
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            print(f"--- gateway log tail ---\n{started.log_tail()}")


@pytest.fixture
def fake_backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    started = _start(
        tmp_path,
        {
            "EVOFLUX_GATEWAY_CLI_ENTRY": str(FAKE_UPSTREAM),
            "EVOFLUX_GATEWAY_SITE_PACKAGES": str(FAKE_UPSTREAM.parent),
        },
    )
    try:
        yield started
    finally:
        started.stop()
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            print(f"--- gateway log tail ---\n{started.log_tail()}")
