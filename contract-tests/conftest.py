"""Fixtures for the black-box contract suite.

``TARGET`` (python|rust|gateway, default python) picks the backend under test.
``AREA`` is consumed by ``make contract``, which points pytest at one directory.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from backends import Backend, BackendStartError, Target, start_backend


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        help="Rewrite snapshot files from the current backend (use against python).",
    )


@pytest.fixture(scope="session")
def target() -> Target:
    value = os.environ.get("TARGET", "python")
    if value not in ("python", "rust", "gateway"):
        raise pytest.UsageError(
            f"TARGET must be python, rust or gateway, got {value!r}"
        )
    return value  # ty: ignore[invalid-return-type]


@pytest.fixture
def db_fixture() -> Path | None:
    """Override in an area's conftest to start from a fixture database."""
    return None


@pytest.fixture
def backend(
    target: Target, tmp_path: Path, db_fixture: Path | None
) -> Iterator[Backend]:
    try:
        started = start_backend(target, tmp_path, db_fixture)
    except BackendStartError as exc:
        pytest.fail(str(exc), pytrace=False)
    try:
        yield started
    except BaseException:
        print(f"--- {target} backend log tail ---\n{started.log_tail()}")
        raise
    finally:
        started.stop()


@pytest.fixture
def client(backend: Backend) -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": f"Bearer {backend.token}"},
        timeout=30.0,
    ) as http:
        yield http


class Snapshots:
    def __init__(self, directory: Path, update: bool) -> None:
        self._dir = directory
        self._update = update

    def check(self, name: str, value: object) -> None:
        path = self._dir / name
        if self._update:
            path.parent.mkdir(parents=True, exist_ok=True)
            rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
            path.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            return
        assert path.exists(), f"missing snapshot {path}; record with --snapshot-update"
        assert json.loads(path.read_text(encoding="utf-8")) == value


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> Snapshots:
    directory = Path(str(request.node.path)).parent / "snapshots"
    return Snapshots(directory, bool(request.config.getoption("--snapshot-update")))
