"""Harness-area fixtures: the harness is test infrastructure, not a board lane."""

from __future__ import annotations

import pytest


@pytest.fixture
def rust_units() -> list[str]:
    """The harness tests only need a live backend, so ``TARGET=rust`` routes edge-stateless like perf."""
    return ["edge-stateless"]
