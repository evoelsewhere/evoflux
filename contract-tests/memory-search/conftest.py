"""Fixtures for the memory-search contract."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_WIKI_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "wiki"
