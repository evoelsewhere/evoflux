"""Fixtures for the black-box contract suite.

``TARGET`` (python|rust|gateway, default python) picks the backend under test.
``AREA`` is consumed by ``make contract``, which points pytest at one directory.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from backends import Backend, BackendStartError, Target, start_backend
from mock_provider.server import MockProvider

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "migration"))
from check_board import load_routing, owner_for, parse_board  # noqa: E402


def unit_for_test(path: Path) -> str:
    area = path.relative_to(ROOT / "contract-tests").parts[0]
    rows = parse_board(
        (ROOT / "server" / "MIGRATION_BOARD.md").read_text(encoding="utf-8")
    )
    units = [
        row["unit"] for row in rows if row["lane"] == area and row["unit"] != "none"
    ]
    if len(units) != 1:
        raise pytest.UsageError(f"no unique migration unit for contract area {area!r}")
    return units[0]


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
def rust_units(request: pytest.FixtureRequest) -> list[str]:
    """Units routed to Rust under ``TARGET=rust``; areas that are not board lanes override it."""
    return [unit_for_test(Path(str(request.node.path)))]


@pytest.fixture
def backend(
    request: pytest.FixtureRequest,
    target: Target,
    rust_units: list[str],
    tmp_path: Path,
    db_fixture: Path | None,
) -> Iterator[Backend]:
    try:
        extra_env = None
        if target == "rust":
            extra_env = {
                "EVOFLUX_ROUTE_OVERRIDE": ",".join(
                    f"{unit}=rust" for unit in rust_units
                )
            }
        started = start_backend(target, tmp_path, db_fixture, extra_env=extra_env)
    except BackendStartError as exc:
        pytest.fail(str(exc), pytrace=False)
    try:
        request.node._replay_backend_url = started.base_url
        request.node._replay_backend_token = started.token
        yield started
    finally:
        started.stop()
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            print(f"--- {target} backend log tail ---\n{started.log_tail()}")


@pytest.fixture(autouse=True)
def replay_capture(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    transcript = os.environ.get("EVOFLUX_REPLAY_TRANSCRIPT")
    if not transcript:
        return
    original = httpx.Client.send
    routing = load_routing(ROOT / "server" / "routing.toml")
    unit = os.environ["EVOFLUX_REPLAY_UNIT"]

    def send(client, http_request, **kwargs):
        response = original(client, http_request, **kwargs)
        base = getattr(request.node, "_replay_backend_url", None)
        if (
            base
            and str(http_request.url).startswith(base + "/")
            and owner_for(routing, http_request.url.path) == unit
        ):
            response.read()
            try:
                body = response.json()
            except ValueError:
                body = response.text
            token = getattr(request.node, "_replay_backend_token", "")
            headers = {
                k: v.replace(token, "<backend-token>") if token else v
                for k, v in http_request.headers.items()
                if k.lower()
                not in {
                    "host",
                    "content-length",
                    "connection",
                    "user-agent",
                    "accept-encoding",
                }
            }
            try:
                request_body = http_request.content.decode("utf-8")
            except UnicodeDecodeError:
                import base64

                request_body = {
                    "base64": base64.b64encode(http_request.content).decode("ascii")
                }
            row = {
                "test": request.node.nodeid,
                "method": http_request.method,
                "path": http_request.url.raw_path.decode().replace(
                    token, "<backend-token>"
                )
                if token
                else http_request.url.raw_path.decode(),
                "request_headers": headers,
                "request_body": request_body,
                "status": response.status_code,
                "media_type": response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower(),
                "body": body,
            }
            with Path(transcript).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return response

    monkeypatch.setattr(httpx.Client, "send", send)


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
