from __future__ import annotations

import json

import pytest

from app.agent.providers import cache_probe


@pytest.fixture(autouse=True)
def _reset_probe_state() -> None:
    cache_probe._history.clear()
    cache_probe._counter.clear()


def _body(text: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": text},
        ]
    }


def test_probe_scopes_requests_by_conversation_partition(monkeypatch, tmp_path):
    path = tmp_path / "probe.jsonl"
    monkeypatch.setenv("EVOFLUX_CACHE_PROBE", "1")
    monkeypatch.setenv("EVOFLUX_CACHE_PROBE_PATH", str(path))

    cache_probe.record(
        _body("stable one"), provider="xiaomi", model="mimo-v2.5", scope="session-a"
    )
    cache_probe.record(
        _body("stable two"), provider="xiaomi", model="mimo-v2.5", scope="session-a"
    )
    cache_probe.record(
        _body("stable two"), provider="xiaomi", model="mimo-v2.5", scope="session-b"
    )

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["stable_chars"] == 0
    assert rows[1]["key"].endswith(":session-a")
    assert rows[1]["stable_chars"] > 0
    assert rows[2]["key"].endswith(":session-b")
    assert rows[2]["stable_chars"] == 0
