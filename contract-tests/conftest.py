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
from mock_provider.server import MockProvider


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        help="Rewrite snapshot files from the current backend (use against python).",
    )


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    setattr(item, f"rep_{report.when}", report)
    return report


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
    request: pytest.FixtureRequest,
    target: Target,
    tmp_path: Path,
    db_fixture: Path | None,
) -> Iterator[Backend]:
    try:
        started = start_backend(target, tmp_path, db_fixture)
    except BackendStartError as exc:
        pytest.fail(str(exc), pytrace=False)
    try:
        yield started
    finally:
        started.stop()
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            print(f"--- {target} backend log tail ---\n{started.log_tail()}")


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
def snapshot(request: pytest.FixtureRequest, target: Target) -> Snapshots:
    update = bool(request.config.getoption("--snapshot-update"))
    if update and target != "python":
        raise pytest.UsageError("--snapshot-update records from TARGET=python only")
    directory = Path(str(request.node.path)).parent / "snapshots"
    return Snapshots(directory, update)


@pytest.fixture
def mock_provider() -> Iterator[MockProvider]:
    """A replaying model provider on 127.0.0.1; see ``mock_provider/server.py``."""
    provider = MockProvider()
    try:
        yield provider
    finally:
        provider.close()
