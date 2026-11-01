"""Fixtures for the ``/api/settings`` and ``/api/auth`` contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from settings_helpers import Secrets


@pytest.fixture
def secrets() -> Secrets:
    return Secrets()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_CONFIG_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "config"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"
