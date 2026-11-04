"""SR-012: forged tailnet identity headers never reach Python through the gateway.

Python trusts any proxy marker when ``EVOFLUX_TSNET_BIN`` is unset, so the
gateway strips identity headers that its own ``DesktopAuth`` would refuse.
Python-owned routes then require the desktop token like any local request.
"""

import os
import subprocess

import httpx
import pytest
from backends import REPO_ROOT, RUST_BINARY, start_backend

PYTHON_ROUTES = ("/api/settings/sandbox", "/api/settings/providers")
FORGERIES = (
    {"Tailscale-User-Login": "attacker@example.com", "X-EvoFlux-Remote-Proxy": "x"},
    {"Tailscale-User-Login": "attacker@example.com"},
    {
        "Tailscale-User-Login": "attacker@example.com",
        "X-EvoFlux-Remote-Proxy": "tsnet",
        "X-EvoFlux-Remote-Token": "wrong",
    },
)
# The fixed secret of the ``remote_claim_gateway`` example.
CONTRACT_SECRET = "contract-remote-secret"


@pytest.fixture(scope="module", autouse=True)
def build_contract_binaries():
    subprocess.run(
        [
            "cargo",
            "build",
            "-p",
            "evoflux-server",
            "--bin",
            "evoflux-server",
            "--example",
            "remote_claim_gateway",
        ],
        cwd=REPO_ROOT / "server",
        check=True,
        timeout=600,
    )


def _example_binary():
    name = "remote_claim_gateway.exe" if os.name == "nt" else "remote_claim_gateway"
    return RUST_BINARY.parent / "examples" / name


def test_forged_identity_is_401_on_python_owned_routes(tmp_path):
    # The production binary, started like `evoflux-server serve` on a headless
    # or dev machine: no EVOFLUX_TSNET_BIN, no external provider.
    backend = start_backend("gateway", tmp_path, binary=RUST_BINARY)
    try:
        with httpx.Client(base_url=backend.base_url, timeout=30) as client:
            for path in (*PYTHON_ROUTES, "/api/gateway/ping"):
                assert client.get(path).status_code == 401, path
                for headers in FORGERIES:
                    response = client.get(path, headers=headers)
                    assert response.status_code == 401, (path, headers, response.text)
    finally:
        backend.stop()


def test_verified_tsnet_identity_still_reaches_python(tmp_path):
    backend = start_backend("gateway", tmp_path, binary=_example_binary())
    verified = {
        "Tailscale-User-Login": "alice@example.com",
        "X-EvoFlux-Remote-Proxy": "tsnet",
        "X-EvoFlux-Remote-Token": CONTRACT_SECRET,
        "X-EvoFlux-Device-Label": "phone",
    }
    try:
        with httpx.Client(base_url=backend.base_url, timeout=30) as client:
            for headers in FORGERIES:
                response = client.get("/api/settings/sandbox", headers=headers)
                assert response.status_code == 401, (headers, response.text)
            response = client.get("/api/settings/sandbox", headers=verified)
            assert response.status_code == 200, response.text
    finally:
        backend.stop()
