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
    paired_principal_id: str | None,
    paired_destination_id: str | None,
) -> RemoteInboundAction | None:
    """Return a normalized action, or ``None`` for unauthorized/unsupported data.

    ``paired_principal_id``/``paired_destination_id`` are ``None`` before a
    contact has ever been bound (discovery mode). There is no strict-match
    filter to apply yet, so the only thing recognized from *any* sender is a
    ``/pair <code>`` attempt — mirroring Telegram's pre-pairing ``/start
    <token>``, which is likewise open to anyone holding the token/code and
    is authorized by the code's own entropy plus
    :class:`~app.remote.pairing.PairingService` rate limiting, not by sender
    identity. Everything else from an unrecognized sender is dropped so no
    unpaired contact can inject arbitrary text before pairing exists.
    """
    if payload.get("attachment") is not None or payload.get("attachments"):
        return None
    principal_id = _string(payload, "principal_id", "sender")
    # `chat_identifier`/`chat_guid` are imsg's *portable string* handles for
    # a chat. Its numeric `chat_id` (a database rowid) is deliberately not a
    # fallback here: `_string()` only extracts string values, so an int
    # would already be skipped, but sending it would also require the
    # outbound `send` RPC call to select by that same integer rather than
    # the string identifier this module binds as the pairing's destination.
    destination_id = _string(
        payload, "destination_id", "chat_identifier", "chat_guid"
    )
    if principal_id is None or destination_id is None:
        return None

    if paired_principal_id is None or paired_destination_id is None:
        text = _string(payload, "text", "body")
        if text is None or not text.strip().lower().startswith("/pair"):
            return None
        source_key = _string(payload, "guid", "id", "source_key")
        if source_key is None:
            return None
        return RemoteInboundAction(
            connection_id=connection_id,
            kind=RemoteInboundActionKind.TEXT,
            principal=RemotePrincipal(
                connection_id=connection_id,
                principal_id=principal_id,
                destination_id=destination_id,
                display=_string(payload, "display", "sender_name") or "",
            ),
            source_key=source_key,
            text=text,
            callback_token=None,
        )

    if principal_id != paired_principal_id or destination_id != paired_destination_id:
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
