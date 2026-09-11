"""Client-side parsing for Conductor's `evoflux.realtime.v1` SSE protocol.

The normative envelope and event list are in evo-conductor's
docs/evoflux-integration.md ("Event contract"). Parsing is kept pure here so
it is testable without a network; the reconnect state machine driving it is
`ConductorService._realtime_loop`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from app.conductor.constants.api import REALTIME_PROTOCOL_NAME


@dataclass(slots=True, frozen=True)
class RealtimeEvent:
    """One parsed and envelope-validated `evoflux.realtime.v1` frame."""

    event: str
    sequence: str
    emitted_at: datetime | None
    data: dict[str, object]


async def parse_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[RealtimeEvent]:
    """Turn a line-oriented SSE stream into realtime protocol events.

    `lines` must already have terminators stripped (httpx's `aiter_lines()`
    does), so partial lines are reassembled before they reach here and only
    frame assembly is left: a blank line dispatches, a `:`-prefixed line is a
    keep-alive comment, and repeated `data:` lines join with `\\n`.

    An invalid envelope is skipped rather than raised, so one malformed or
    future-protocol frame cannot drop the connection.
    """

    event_name: str | None = None
    data_lines: list[str] = []

    async for line in lines:
        if line == "":
            if event_name is not None and data_lines:
                parsed = _parse_envelope(event_name, "\n".join(data_lines))
                if parsed is not None:
                    yield parsed
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field_name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field_name == "event":
            event_name = value
        elif field_name == "data":
            data_lines.append(value)
        # `id`/`retry` are unread: Last-Event-ID cannot recover events across
        # a Conductor restart, so reconnects always refetch instead of resume.


def _parse_envelope(event_name: str, raw_data: str) -> RealtimeEvent | None:
    try:
        envelope = json.loads(raw_data)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("protocol") != REALTIME_PROTOCOL_NAME:
        return None
    sequence = envelope.get("sequence")
    if not isinstance(sequence, str):
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    return RealtimeEvent(
        event=event_name,
        sequence=sequence,
        emitted_at=_parse_timestamp(envelope.get("emitted_at")),
        data=data,
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
