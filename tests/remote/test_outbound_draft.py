from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.remote.outbound import RemoteProjection
from app.services.stream_envelope import StreamEnvelope
from tests.remote.test_outbound import FakeAdapter


def _envelope(event: str, **data: object) -> StreamEnvelope:
    return StreamEnvelope.from_parts(event=event, data={"type": event, **data})


@pytest.mark.asyncio
async def test_private_draft_streams_delta_and_finalizes_with_edit() -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    adapter.streaming_provider = "private_draft"
    projection.set_adapter(adapter)
    session_id = "draft-session"
    connection_id = str(uuid4())
    projection.register_session(
        session_id,
        connection_id=connection_id,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        session_id,
        connection_id=connection_id,
        destination_id="chat-1",
        principal_id="user-1",
        title="Draft task",
        status="working",
        response_mode="live",
    )
    await asyncio.sleep(0.05)

    projection.observe(session_id, _envelope("message", text="Partial answer"))
    await asyncio.sleep(0.05)

    assert len(adapter.drafts) == 1
    assert adapter.drafts[0]["destination_id"] == "chat-1"
    assert adapter.drafts[0]["text"] == "Partial answer"
    assert adapter.edited == []

    projection.observe(session_id, _envelope("done", response_text="Final answer"))
    await projection.drain_pending()

    assert len(adapter.edited) == 1
    assert "Draft task" in adapter.edited[0].text
