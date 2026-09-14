"""``/api/remote/*`` — desktop HTTP API for the (v1 single) remote connection.

Every route here uses the existing desktop authentication
(``DesktopTokenMiddleware`` — wired in ``app/api/app.py`` like every other
route) and no custom credential type (AC-2, AC-33). Handlers only parse/
validate HTTP shape, call :class:`~app.remote.connection_service.RemoteConnectionService`,
:class:`~app.remote.pairing.PairingService`, and
:data:`~app.remote.runtime.remote_runtime`, and translate the domain errors
those already raise into HTTP responses. No business logic is duplicated
here — connection limits, credential custody, and pairing rules all stay in
their owning service.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.schemas.remote import (
    RemoteConnectionCreateRequest,
    RemoteConnectionPatchRequest,
    RemoteConnectionResponse,
    RemoteConnectionStatusBody,
    RemoteConnectionTokenReplaceRequest,
    RemotePairingLinkResponse,
    RemotePairingResponse,
)
from app.core.credential_store import CredentialStoreError
from app.core.db import get_session
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.connection_service import (
    CredentialStoreFactory,
    RemoteConnectionConflictError,
    RemoteConnectionNotFoundError,
    RemoteConnectionService,
    RemoteCredentialError,
    default_credential_store_factory,
)
from app.remote.contracts import RemoteAdapterValidationError
from app.remote.pairing import PairingService, pairing_service as _pairing_service
from app.remote.runtime import TelegramAdapterFactory, remote_runtime

router = APIRouter()

# ── Dependencies ──────────────────────────────────────────────────────────
#
# Plain functions (not classes) so tests can override them via FastAPI's
# ``app.dependency_overrides`` — the same pattern ``app/api/routes/scheduler.py``
# uses for its singleton. ``_credential_store_factory`` is a module-level
# variable rather than a dependency because it is also used outside any
# request (``_token_configured``) — tests monkeypatch it directly.
#
# ``_pairing_service`` is re-exported from ``app.remote.pairing`` rather than
# constructed here: it must be the exact same process-wide instance the
# Telegram adapter's inbound dispatch consumes tokens against
# (``app/remote/runtime.py``), since pairing tokens live only in that
# instance's memory. A second, locally-constructed ``PairingService()``
# would silently never see a token this route mints.

_credential_store_factory: CredentialStoreFactory = default_credential_store_factory


def get_connection_service() -> RemoteConnectionService:
    return RemoteConnectionService(adapter_factory=TelegramAdapterFactory())


def get_pairing_service() -> PairingService:
    return _pairing_service


# ── Helpers ───────────────────────────────────────────────────────────────


def _token_configured(connection_id: uuid.UUID) -> bool:
    store = _credential_store_factory(connection_id)
    try:
        return store.load() is not None
    except CredentialStoreError:
        return False


async def _get_pairing(
    session: AsyncSession, connection_id: uuid.UUID
) -> RemotePairing | None:
    result = await session.exec(
        select(RemotePairing).where(RemotePairing.connection_id == connection_id)
    )
    return result.first()


async def _status_body(
    session: AsyncSession, connection_id: uuid.UUID
) -> RemoteConnectionStatusBody:
    status = remote_runtime.status(connection_id)
    pairing = await _get_pairing(session, connection_id)
    return RemoteConnectionStatusBody(
        connection_id=status.connection_id,
        state=status.state,
        last_error_class=status.last_error_class,
        last_successful_poll_at=status.last_successful_poll_at,
        paired=pairing is not None,
        phone_reachable=status.phone_reachable,
        informational_drop_count=status.informational_drop_count,
        high_priority_drop_count=status.high_priority_drop_count,
    )


async def _connection_response(
    session: AsyncSession, connection: RemoteConnection
) -> RemoteConnectionResponse:
    return RemoteConnectionResponse(
        id=connection.id,
        adapter=connection.adapter,
        label=connection.label,
        enabled=connection.enabled,
        adapter_principal_id=connection.adapter_principal_id,
        adapter_username=connection.adapter_username,
        token_configured=_token_configured(connection.id),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
        status=await _status_body(session, connection.id),
    )


async def _connection_or_404(
    session: AsyncSession, service: RemoteConnectionService, connection_id: uuid.UUID
) -> RemoteConnection:
    connection = await service.get(session, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Remote connection not found.")
    return connection


# ── Connections ───────────────────────────────────────────────────────────


@router.get("/connections")
async def list_connections(
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> list[RemoteConnectionResponse]:
    """Zero-or-one v1 connection summary and safe runtime state."""
    connections = await service.list(session)
    return [await _connection_response(session, c) for c in connections]


@router.post("/connections", status_code=201)
async def create_connection(
    body: RemoteConnectionCreateRequest,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> RemoteConnectionResponse:
    """Validate a write-only token, vault it, and create the connection.

    ``409`` when one already exists (AC-3, v1's one-connection limit).
    """
    try:
        connection = await service.create_connection(
            session, token=body.token, label=body.label
        )
    except RemoteConnectionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemoteAdapterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RemoteCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await remote_runtime.reconcile_connection(connection.id)
    # ``reconcile_connection`` uses the read pool internally, so it never
    # contends with the request's write session under SQLite's pool-size-1.
    return await _connection_response(session, connection)


@router.patch("/connections/{connection_id}")
async def patch_connection(
    connection_id: uuid.UUID,
    body: RemoteConnectionPatchRequest,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> RemoteConnectionResponse:
    """Change label and/or enabled state. Adapter kind and bot identity are
    immutable here — the request schema simply has no field for them."""
    connection = await _connection_or_404(session, service, connection_id)

    if body.label is not None:
        connection = await service.set_label(session, connection_id, label=body.label)
    if body.enabled is not None:
        connection = await service.set_enabled(
            session, connection_id, enabled=body.enabled
        )

    await remote_runtime.reconcile_connection(connection_id)
    return await _connection_response(session, connection)


@router.put("/connections/{connection_id}/token")
async def replace_token(
    connection_id: uuid.UUID,
    body: RemoteConnectionTokenReplaceRequest,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> RemoteConnectionResponse:
    """Validate and atomically replace the write-only bot token.

    Re-pairs (invalidates the existing pairing) when the new token resolves
    to a different bot — handled entirely inside
    ``RemoteConnectionService.update_token`` (AC-6, AC-10).
    """
    try:
        connection = await service.update_token(
            session, connection_id, token=body.token
        )
    except RemoteConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RemoteAdapterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RemoteCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await remote_runtime.reconcile_connection(connection_id)
    return await _connection_response(session, connection)


@router.delete("/connections/{connection_id}", status_code=204)
async def remove_connection(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> None:
    """Stop and remove the connection, pairing, tokens, and vault credential."""
    try:
        await service.remove(session, connection_id)
    except RemoteConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RemoteCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await remote_runtime.reconcile_connection(connection_id)


# ── Pairing ───────────────────────────────────────────────────────────────


@router.post("/connections/{connection_id}/pairing-links")
async def issue_pairing_link(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
    pairing_service: PairingService = Depends(get_pairing_service),
) -> RemotePairingLinkResponse:
    """Mint a single-use deep link and return link, QR payload, and expiry."""
    connection = await _connection_or_404(session, service, connection_id)
    link = pairing_service.issue_link(connection)
    return RemotePairingLinkResponse(
        url=link.url, qr_payload=link.qr_payload, expires_at=link.expires_at
    )


@router.get("/connections/{connection_id}/pairing")
async def get_pairing(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> RemotePairingResponse | None:
    """Safe paired-account decoration, or ``null`` when unpaired."""
    await _connection_or_404(session, service, connection_id)
    pairing = await _get_pairing(session, connection_id)
    if pairing is None:
        return None
    return RemotePairingResponse(
        id=pairing.id,
        label=pairing.label,
        display=pairing.display,
        created_at=pairing.created_at,
        last_seen_at=pairing.last_seen_at,
    )


@router.delete("/connections/{connection_id}/pairing", status_code=204)
async def revoke_pairing(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
    pairing_service: PairingService = Depends(get_pairing_service),
) -> None:
    """Revoke the paired account (AC-10) — a later ``authorize`` call for
    the former principal fails immediately, with no cache to invalidate."""
    await _connection_or_404(session, service, connection_id)
    await pairing_service.unpair(session, connection_id)


# ── Status ────────────────────────────────────────────────────────────────


@router.get("/connections/{connection_id}/status")
async def get_connection_status(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: RemoteConnectionService = Depends(get_connection_service),
) -> RemoteConnectionStatusBody:
    """Adapter lifecycle, last safe error, poll time, pairing state,
    reachability, and drop counts (AC-34)."""
    await _connection_or_404(session, service, connection_id)
    return await _status_body(session, connection_id)
