from __future__ import annotations

import pytest

from app.conductor.semver import SemanticVersion


def test_semver_orders_prerelease_and_stable_versions() -> None:
    assert SemanticVersion.parse("1.0.0-alpha.1") < SemanticVersion.parse("1.0.0")
    assert SemanticVersion.parse("1.0.0-1") < SemanticVersion.parse("1.0.0-alpha")
    assert SemanticVersion.parse("1.9.9") < SemanticVersion.parse("2.0.0")


def test_semver_ignores_build_metadata_for_precedence() -> None:
    assert SemanticVersion.parse("1.2.3+linux") == SemanticVersion.parse("1.2.3+darwin")


@pytest.mark.parametrize(
    "value",
    ["1", "1.0", "01.0.0", "1.0.0-01", "1.0.0+", "v1.0.0"],
)
def test_semver_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        SemanticVersion.parse(value)
