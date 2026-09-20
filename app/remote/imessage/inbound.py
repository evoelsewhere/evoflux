"""Normalize iMessage provider updates at the remote authorization boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import UUID

from app.remote.contracts import (
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemotePrincipal,
)

_NUMBERED_REPLY = re.compile(r"^\s*(\d+)\s*$")


def normalize_inbound(
    payload: Mapping[str, object],
    *,
    connection_id: UUID,
    paired_principal_id: str,
    paired_destination_id: str,
) -> RemoteInboundAction | None:
    """Return a normalized action, or ``None`` for unauthorized/unsupported data."""
    if payload.get("attachment") is not None or payload.get("attachments"):
        return None
    principal_id = _string(payload, "principal_id", "sender")
    destination_id = _string(payload, "destination_id", "chat_id")
    if (
        principal_id is None
        or destination_id is None
        or principal_id != paired_principal_id
        or destination_id != paired_destination_id
    ):
        return None
    source_key = _string(payload, "guid", "id", "source_key")
    if source_key is None:
        return None
    text = _string(payload, "text", "body")
    callback = _string(payload, "callback_token", "tapback")
    if callback is not None:
        kind = RemoteInboundActionKind.CALLBACK
        callback_token = callback
    elif text is not None:
        numbered = _NUMBERED_REPLY.fullmatch(text)
        if numbered is not None:
            kind = RemoteInboundActionKind.CALLBACK
            callback_token = f"number:{numbered.group(1)}"
        else:
            kind = RemoteInboundActionKind.TEXT
            callback_token = None
    else:
        return None
    return RemoteInboundAction(
        connection_id=connection_id,
        kind=kind,
        principal=RemotePrincipal(
            connection_id=connection_id,
            principal_id=principal_id,
            destination_id=destination_id,
            display=_string(payload, "display", "sender_name") or "",
        ),
        source_key=source_key,
        text=text,
        callback_token=callback_token,
    )


def _string(payload: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None
