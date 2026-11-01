"""Fixtures for the ``/api/mcp`` contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_helpers import Scrub


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_CONFIG_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "config"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """``EVOFLUX_CACHE_DIR``; MCP OAuth state lives in ``mcp-oauth/<name>.json``."""
    return tmp_path / "cache"


@pytest.fixture
def mcp_json(config_dir: Path) -> Path:
    return config_dir / "mcp.json"


@pytest.fixture
def db_fixture(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """``@pytest.mark.preseed(text)`` writes ``mcp.json`` before the backend starts.

    ``start_backend`` creates the config dir with ``exist_ok``, and the backend
    reads ``mcp.json`` once at start-up, so this is the only way to test the
    start-up load.
    """
    marker = request.node.get_closest_marker("preseed")
    if marker is not None:
        config = tmp_path / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "mcp.json").write_text(marker.args[0], encoding="utf-8", newline="")
    return None


@pytest.fixture
def http_mcp():
    from http_server import FakeHttpMcp

    server = FakeHttpMcp()
    try:
        yield server
    finally:
        server.close()
