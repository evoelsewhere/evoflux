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
    stream ends. Raises ``TimeoutError`` once ``timeout_s`` seconds have passed,
    even if the server only sends comment keep-alives or nothing at all."""
    # Not exported publicly; httpx-sse is pinned in uv.lock (0.4.3).
    from httpx_sse._decoders import SSEDecoder

    deadline = time.monotonic() + timeout_s
    decoder = SSEDecoder()
    events: list[Event] = []
    headers = {"Accept": "text/event-stream", "Cache-Control": "no-store"}
    try:
        with client.stream(
            "GET", url, headers=headers, timeout=httpx.Timeout(timeout_s)
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                # Checked on every line, comments and blanks included.
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"no terminating event from {url} in {timeout_s}s"
                    )
                sse = decoder.decode(line.rstrip("\n"))
                if sse is None:
                    continue
                event = Event(sse.event, _decode(sse.data))
                events.append(event)
                if until(event):
                    return events
    except httpx.ReadTimeout as exc:
        raise TimeoutError(f"no data from {url} within {timeout_s}s") from exc
    return events


def assert_same_sequence(a: list[Event], b: list[Event]) -> None:
    """Compare event type, order and normalized payload."""
    left = [(e.event, normalize(e.data)) for e in a]
    right = [(e.event, normalize(e.data)) for e in b]
    assert left == right, f"SSE sequences differ:\n  a={left}\n  b={right}"
