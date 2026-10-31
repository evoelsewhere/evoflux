"""Remote claim parity through the production gateway."""

import os
import json
from datetime import date
import sqlite3
import subprocess
import httpx
import pytest
from backends import REPO_ROOT, RUST_BINARY, start_backend


@pytest.fixture(scope="session", autouse=True)
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
    )


@pytest.fixture
def production(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "quoteoftheday.json").write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "quote": "Contract quote",
                "author": "Contract author",
            }
        ),
        encoding="utf-8",
    )
    binary = (
        RUST_BINARY.parent
        / "examples"
        / ("remote_claim_gateway.exe" if os.name == "nt" else "remote_claim_gateway")
    )
    backend = start_backend("gateway", tmp_path, binary=binary)
    try:
        yield backend, tmp_path / "data" / "evoflux.db"
    finally:
        backend.stop()


def test_remote_claim_parity(production):
    backend, db_path = production
    first = {
        "Tailscale-User-Login": "alice@example.com",
        "X-EvoFlux-Device-Label": "phone",
    }
    other = {**first, "X-EvoFlux-Device-Label": "laptop"}
    python_path, rust_path = "/api/quote", "/api/test-claim"
    with httpx.Client(base_url=backend.base_url, timeout=30) as client:
        for path in (python_path, rust_path):
            with sqlite3.connect(db_path) as db:
                db.execute("DELETE FROM remote_use_sessions")
            first_response = client.get(path, headers=first)
            repeat_response = client.get(path, headers=first)
            assert first_response.status_code == repeat_response.status_code == 200
            assert (
                first_response.json()
                == repeat_response.json()
                == {"quote": "Contract quote", "author": "Contract author"}
            )
            blocked_python = client.get(python_path, headers=other)
            blocked_rust = client.get(rust_path, headers=other)
            assert blocked_python.status_code == blocked_rust.status_code == 409
            assert blocked_python.json() == blocked_rust.json()


def test_production_gateway_claims_the_python_database_override(tmp_path):
    custom = tmp_path / "custom.db"
    backend = start_backend(
        "gateway",
        tmp_path,
        binary=RUST_BINARY,
        extra_env={"DATABASE_URL": f"sqlite+aiosqlite:///{custom.as_posix()}"},
    )
    try:
        first = {
            "Tailscale-User-Login": "alice@example.com",
            "X-EvoFlux-Device-Label": "phone",
        }
        second = {**first, "X-EvoFlux-Device-Label": "laptop"}
        with httpx.Client(base_url=backend.base_url, timeout=30) as client:
            assert client.get("/api/gateway/ping", headers=first).status_code == 200
            conflict = client.get("/api/quote", headers=second)
            assert conflict.status_code == 409
            assert conflict.json()["current"]["device_label"] == "phone"
    finally:
        backend.stop()
