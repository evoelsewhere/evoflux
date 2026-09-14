"""Pydantic request/response models for ``/api/remote/*``.

Secret-bearing request models use write-only fields: the ``token`` on
:class:`RemoteConnectionCreateRequest` and
:class:`RemoteConnectionTokenReplaceRequest` is accepted but never echoed
back. Every response model instead reports ``token_configured: bool`` —
never the credential or a fingerprint of it (spec: "Desktop HTTP API").
None of these models carry an example that looks like a real bot token.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.remote.contracts import RemoteConnectionState, RemoteErrorClass

__all__ = [
    "RemoteConnectionCreateRequest",
    "RemoteConnectionPatchRequest",
    "RemoteConnectionResponse",
    "RemoteConnectionStatusBody",
    "RemoteConnectionTokenReplaceRequest",
    "RemotePairingLinkResponse",
    "RemotePairingResponse",
]

#: A clearly-fake placeholder — never a shape resembling a real Telegram
#: bot token — so OpenAPI examples cannot be mistaken for a live credential.
_TOKEN_EXAMPLE = "<paste-your-bot-token-from-botfather>"


class RemoteConnectionCreateRequest(BaseModel):
    """``POST /api/remote/connections`` body."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    token: str = Field(
        min_length=1,
        repr=False,
        description="Bot token from @BotFather. Write-only — never returned by the API.",
        json_schema_extra={"example": _TOKEN_EXAMPLE},
    )


class RemoteConnectionPatchRequest(BaseModel):
    """``PATCH /api/remote/connections/{id}`` body.

    Only ``label`` and ``enabled`` are accepted — adapter kind and bot
    identity are immutable outside of :class:`RemoteConnectionTokenReplaceRequest`
    (``extra="forbid"`` rejects any other field with a clean 422 rather than
    silently ignoring it).
    """

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None


class RemoteConnectionTokenReplaceRequest(BaseModel):
    """``PUT /api/remote/connections/{id}/token`` body."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(
        min_length=1,
        repr=False,
        description="Replacement bot token. Write-only — never returned by the API.",
        json_schema_extra={"example": _TOKEN_EXAMPLE},
    )


class RemoteConnectionStatusBody(BaseModel):
    """Safe, diagnosable connection status (AC-34).

    Mirrors :class:`app.remote.contracts.RemoteAdapterStatus` field-for-field
    but is this module's own response shape — never the dataclass directly —
    so a later change to the internal contract cannot silently change the
    wire shape.
    """

    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    state: RemoteConnectionState
    last_error_class: RemoteErrorClass
    last_successful_poll_at: datetime | None
    paired: bool
    phone_reachable: bool | None
    informational_drop_count: int
    high_priority_drop_count: int


class RemoteConnectionResponse(BaseModel):
    """``GET/POST/PATCH/PUT .../connections[...]`` response shape.

    Deliberately has no ``token`` field at all — only ``token_configured``.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    adapter: str
    label: str
    enabled: bool
    adapter_principal_id: str
    adapter_username: str
    token_configured: bool
    created_at: datetime
    updated_at: datetime
    status: RemoteConnectionStatusBody


class RemotePairingLinkResponse(BaseModel):
    """``POST /api/remote/connections/{id}/pairing-links`` response."""

    model_config = ConfigDict(extra="forbid")

    url: str
    qr_payload: str
    expires_at: datetime


class RemotePairingResponse(BaseModel):
    """``GET /api/remote/connections/{id}/pairing`` response when paired.

    Only safe, untrusted decoration — never the raw provider chat/user ID
    beyond what is already the ``principal``/``destination`` the rest of the
    system treats as opaque identifiers.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str
    display: str
    created_at: datetime
    last_seen_at: datetime
