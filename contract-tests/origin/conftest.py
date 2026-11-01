"""Origin-area fixtures: the gateway's Host/Origin checks are not a board lane."""

from __future__ import annotations

import pytest


@pytest.fixture
def rust_units() -> list[str]:
    """``TARGET=rust`` routes edge-stateless, so both a Rust- and a Python-owned route are checked."""
    return ["edge-stateless"]
