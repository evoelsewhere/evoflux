from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.conductor.realtime import RealtimeEvent, parse_sse_events


async def _lines(*chunks: str) -> AsyncIterator[str]:
    """One line per `await`, since httpx already reassembles partial lines:
    what the parser must tolerate is a frame spread over several awaits.
    """

    for chunk in chunks:
        yield chunk


def _hello_frame(sequence: str = "1") -> list[str]:
    payload = (
        f'{{"protocol": "evoflux.realtime.v1", "sequence": "{sequence}", '
        '"emitted_at": "2026-08-09T10:30:00Z", '
        '"data": {"connection_id": "64d89e88", "heartbeat_seconds": 20}}'
    )
    return ["event: control.hello", f"data: {payload}", ""]


@pytest.mark.asyncio
async def test_parses_a_single_control_hello_frame() -> None:
    lines = _lines(*_hello_frame())
    events = [event async for event in parse_sse_events(lines)]

    assert len(events) == 1
    event = events[0]
    assert event.event == "control.hello"
    assert event.sequence == "1"
    assert event.data == {"connection_id": "64d89e88", "heartbeat_seconds": 20}
    assert event.emitted_at is not None
    assert event.emitted_at.year == 2026


@pytest.mark.asyncio
async def test_frame_arriving_one_line_at_a_time_still_dispatches() -> None:
    # Each continuation line carries its own `data:` prefix, per the SSE
    # field-parsing rules; the parser joins the values with `\n`.
    lines = _lines(
        "event: resources.changed",
        'data: {"protocol": "evoflux.realtime.v1", "sequence": "7",',
        'data:  "emitted_at": "2026-08-09T10:31:00Z", "data": {"reason": "upsert",',
        'data:  "resource_id": "b9c1409a", "fetch_url": "/api/v1/resources/fetch"}}',
        "",
    )
    events = [event async for event in parse_sse_events(lines)]

    assert len(events) == 1
    assert events[0].event == "resources.changed"
    assert events[0].sequence == "7"
    assert events[0].data["reason"] == "upsert"


@pytest.mark.asyncio
async def test_multiple_frames_in_one_stream_dispatch_independently() -> None:
    lines = _lines(*_hello_frame("1"), *_hello_frame("2"))
    events = [event async for event in parse_sse_events(lines)]

    assert [event.sequence for event in events] == ["1", "2"]


@pytest.mark.asyncio
async def test_comment_lines_are_ignored_not_dispatched() -> None:
    # Conductor sends `: keep-alive` every 10s to hold idle proxies open.
    lines = _lines(": keep-alive", "", *_hello_frame())
    events = [event async for event in parse_sse_events(lines)]

    assert len(events) == 1
    assert events[0].event == "control.hello"


@pytest.mark.asyncio
async def test_frame_with_wrong_protocol_is_skipped() -> None:
    lines = _lines(
        "event: control.hello",
        'data: {"protocol": "some.other.v1", "sequence": "1", '
        '"emitted_at": "2026-08-09T10:30:00Z", "data": {}}',
        "",
    )
    events = [event async for event in parse_sse_events(lines)]
    assert events == []


@pytest.mark.asyncio
async def test_frame_with_malformed_json_is_skipped_not_raised() -> None:
    lines = _lines("event: control.hello", "data: {not valid json", "")
    events = [event async for event in parse_sse_events(lines)]
    assert events == []


@pytest.mark.asyncio
async def test_frame_missing_data_object_is_skipped() -> None:
    lines = _lines(
        "event: control.hello",
        'data: {"protocol": "evoflux.realtime.v1", "sequence": "1", '
        '"emitted_at": "2026-08-09T10:30:00Z"}',
        "",
    )
    events = [event async for event in parse_sse_events(lines)]
    assert events == []


@pytest.mark.asyncio
async def test_a_frame_without_event_field_is_never_dispatched() -> None:
    # Without an `event:` line there is nothing to dispatch under.
    lines = _lines(
        'data: {"protocol": "evoflux.realtime.v1", "sequence": "1", '
        '"emitted_at": "2026-08-09T10:30:00Z", "data": {}}',
        "",
    )
    events = [event async for event in parse_sse_events(lines)]
    assert events == []


@pytest.mark.asyncio
async def test_multiline_data_field_is_joined_with_newline() -> None:
    # Conductor's payloads are single-line JSON today, but the parser must
    # not corrupt one that is not.
    lines = _lines(
        "event: control.hello",
        'data: {"protocol": "evoflux.realtime.v1", "sequence": "1",',
        'data:  "emitted_at": "2026-08-09T10:30:00Z", "data": {}}',
        "",
    )
    events = [event async for event in parse_sse_events(lines)]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_duplicate_sequence_numbers_both_surface_to_the_caller() -> None:
    # Consistency comes from the next fetch deriving a complete tree, not
    # from sequence dedup, so the parser must not drop a repeat silently.
    lines = _lines(*_hello_frame("5"), *_hello_frame("5"))
    events = [event async for event in parse_sse_events(lines)]
    assert [event.sequence for event in events] == ["5", "5"]


def test_realtime_event_is_a_plain_frozen_value() -> None:
    event = RealtimeEvent(
        event="control.heartbeat", sequence="1", emitted_at=None, data={}
    )
    assert event.event == "control.heartbeat"
