"""Every v3.x release's database must open and serve under the current Python."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from fixtures import TAGS, upgrade_fixture, upgrade_manifest


@pytest.fixture(params=TAGS)
def tag(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def db_fixture(tag: str) -> Iterator[Path]:
    path = upgrade_fixture(tag)
    yield path
    path.unlink(missing_ok=True)
    path.parent.rmdir()


def test_each_fixture_opens_under_v3_1_1(client: httpx.Client, tag: str) -> None:
    manifest = upgrade_manifest(tag)
    response = client.get("/api/team/sessions")
    assert response.status_code == 200, response.text
    listed = response.text
    expected = manifest["created_ids"]["sessions"]
    assert len(expected) == 2
    for session_id in expected:
        assert session_id in listed, f"{tag}: session {session_id} not listed"
