"""Collect and compare server-sent events as sequences, never as raw bytes."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, NamedTuple

import httpx

from normalize import normalize


class Event(NamedTuple):
    event: str
    data: Any


def _decode(data: str) -> Any:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data


def collect_events(
    client: httpx.Client,
    url: str,
    *,
    until: Callable[[Event], bool],
    timeout_s: float,
) -> list[Event]:
    """Read ``url`` until ``until(event)`` is true (that event is included) or the
    stream ends. Raises ``TimeoutError`` once ``timeout_s`` seconds have passed."""
    from httpx_sse import connect_sse

    deadline = time.monotonic() + timeout_s
    events: list[Event] = []
    timeout = httpx.Timeout(timeout_s)
    with connect_sse(client, "GET", url, timeout=timeout) as source:
        for sse in source.iter_sse():
            event = Event(sse.event, _decode(sse.data))
            events.append(event)
            if until(event):
                return events
            if time.monotonic() > deadline:
                raise TimeoutError(f"no terminating event from {url} in {timeout_s}s")
    return events


def assert_same_sequence(a: list[Event], b: list[Event]) -> None:
    """Compare event type, order and normalized payload."""
    left = [(e.event, normalize(e.data)) for e in a]
    right = [(e.event, normalize(e.data)) for e in b]
    assert left == right, f"SSE sequences differ:\n  a={left}\n  b={right}"
