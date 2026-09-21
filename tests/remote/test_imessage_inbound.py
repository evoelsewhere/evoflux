from __future__ import annotations

from uuid import uuid4

from app.remote.contracts import RemoteInboundActionKind
from app.remote.imessage.inbound import normalize_inbound


def test_normalizes_authorized_text() -> None:
    connection_id = uuid4()
    action = normalize_inbound(
        {
            "guid": "m1",
            "sender": "+1555",
            "chat_identifier": "chat-1",
            "text": "status",
            "sender_name": "Operator",
        },
        connection_id=connection_id,
        paired_principal_id="+1555",
        paired_destination_id="chat-1",
    )

    assert action is not None
    assert action.kind is RemoteInboundActionKind.TEXT
    assert action.principal.display == "Operator"


def test_numeric_chat_id_is_not_a_destination_fallback() -> None:
    """imsg's `chat_id` is a numeric database rowid, not the portable string
    identifier this module binds as `destination_id` — accepting it here
    would have to coerce an int to a str, and comparing that coerced value
    against `paired_destination_id` (always a `chat_identifier`/`chat_guid`
    string) would never match a real pairing anyway."""
    action = normalize_inbound(
        {
            "guid": "m1b",
            "sender": "+1555",
            "chat_id": 42,
            "text": "status",
        },
        connection_id=uuid4(),
        paired_principal_id="+1555",
        paired_destination_id="chat-1",
    )

    assert action is None


def test_normalizes_tapback_and_numbered_reply_as_callbacks() -> None:
    kwargs = {
        "connection_id": uuid4(),
        "paired_principal_id": "+1555",
        "paired_destination_id": "chat-1",
    }
    tapback = normalize_inbound(
        {
            "guid": "m2",
            "principal_id": "+1555",
            "destination_id": "chat-1",
            "tapback": "callback:approve",
        },
        **kwargs,
    )
    numbered = normalize_inbound(
        {
            "guid": "m3",
            "principal_id": "+1555",
            "destination_id": "chat-1",
            "text": " 2 ",
        },
        **kwargs,
    )

    assert tapback is not None and tapback.callback_token == "callback:approve"
    assert numbered is not None and numbered.callback_token == "number:2"


def test_rejects_attachment_and_unpaired_sender() -> None:
    kwargs = {
        "connection_id": uuid4(),
        "paired_principal_id": "+1555",
        "paired_destination_id": "chat-1",
    }
    assert (
        normalize_inbound(
            {
                "guid": "m4",
                "principal_id": "+1555",
                "destination_id": "chat-1",
                "attachments": [{"name": "photo.jpg"}],
            },
            **kwargs,
        )
        is None
    )
    assert (
        normalize_inbound(
            {
                "guid": "m5",
                "principal_id": "+1999",
                "destination_id": "chat-1",
                "text": "status",
            },
            **kwargs,
        )
        is None
    )
