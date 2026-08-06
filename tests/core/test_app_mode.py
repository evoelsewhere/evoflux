from __future__ import annotations

import pytest

from app.core.app_mode import AppMode, normalize_app_mode, parse_app_mode


@pytest.mark.parametrize("legacy", ["normal", "forge"])
def test_legacy_work_names_normalize_at_boundary(legacy):
    assert parse_app_mode(legacy) is AppMode.WORK
    assert normalize_app_mode(legacy) == "work"


@pytest.mark.parametrize("mode", ["work", "coding", AppMode.WORK, AppMode.CODING])
def test_canonical_modes_round_trip(mode):
    assert normalize_app_mode(mode) in {"work", "coding"}


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="work.*coding"):
        parse_app_mode("aim")
