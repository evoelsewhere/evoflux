"""WebBridge — WebSocket relay between agent and browser extension.

Provides:
- ``WS /webbridge/relay`` — extension connects here to register
- ``WS /webbridge/agent/{session_id}`` — external agent consumers
- ``GET /webbridge/status`` — list connected extensions

Architecture:
    Agent ←→ Relay Server ←→ Chrome Extension ←→ Real Browser (CDP)

These endpoints are thin adapters over
:data:`app.services.webbridge_service.webbridge_manager`, which owns the
extension registry, request/response correlation and event fan-out. The
in-process ``webbridge`` agent tool talks to the same manager directly, so
it never needs a loopback WebSocket of its own.

Both WS endpoints require the desktop token via the ``?_token=`` query
param when one is configured (see :mod:`app.core.desktop_auth`) — without
it, any local web page could open a socket and impersonate an extension
or drive the user's browser. When no token is configured (CLI mode) the
endpoints stay open, matching the HTTP middleware's behaviour.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import DbSession
from app.core.desktop_auth import (
    _QS_TOKEN_PARAM,
    desktop_token_matches,
    expected_desktop_token,
)
from app.models.chat import ChatSession
from app.services.agent_service import NoTeamConfigured
from app.services.interactive_message_service import (
    resolve_team_for_session,
    submit_persisted_interactive_message,
)
from app.services.webbridge_pairing_service import (
    authenticate_pairing,
    claim_interaction_dispatch,
    create_or_get_interaction,
    create_pairing,
    delete_tab_binding,
    list_active_pairings,
    list_tab_bindings,
    revoke_pairing,
    upsert_tab_binding,
    webbridge_interaction_rate_limiter,
    webbridge_pairing_code_store,
    webbridge_ticket_store,
)
from app.services.webbridge_service import (
    NO_EXTENSION_ERROR,
    ExtensionConnection,
    webbridge_manager,
)

router = APIRouter()
_MAX_RELAY_FRAME_BYTES = 1_000_000
_MAX_INTERACTION_METADATA_BYTES = 256_000


async def _ws_authorized(ws: WebSocket) -> bool:
    """Enforce the desktop token on a WebSocket handshake.

    Mirrors :class:`app.core.desktop_auth.DesktopTokenMiddleware` for WS
    endpoints: open when no token is configured; otherwise the ``?_token=``
    query param must match. On failure the socket is closed with code 4401
    *before* accept so no handler logic runs.
    """
    expected = expected_desktop_token()
    if not expected:
        return True
    if desktop_token_matches(ws.query_params.get(_QS_TOKEN_PARAM), expected):
        return True
    logger.warning("webbridge_ws_rejected path={}", ws.url.path)
    await ws.close(code=4401)
    return False


async def _extension_ws_authorization(
    ws: WebSocket,
) -> tuple[bool, str | None]:
    """Authorize an extension relay and return its pairing identity, if any."""
    ticket = ws.query_params.get("_ticket")
    if ticket is not None:
        pairing_id = webbridge_ticket_store.consume(ticket)
        if pairing_id is not None:
            return True, pairing_id
        logger.warning("webbridge_ticket_rejected path={}", ws.url.path)
        await ws.close(code=4401)
        return False, None
    return await _ws_authorized(ws), None


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    return value.strip() if scheme.casefold() == "bearer" else ""


async def _paired_request(
    request: Request,
    db: DbSession,
    *,
    required_scope: str,
):
    pairing = await authenticate_pairing(
        db,
        _bearer_token(request),
        required_scope=required_scope,
    )
    if pairing is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_pairing", "message": "Pair WebBridge first."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return pairing


async def _stage_persisted_bindings(pairing_id: str) -> None:
    """Load a paired browser's durable bindings into fail-closed manager state."""
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        bindings = await list_tab_bindings(db, uuid.UUID(pairing_id))
    for binding in bindings:
        webbridge_manager.stage_session_tab_binding(
            str(binding.session_id),
            pairing_id,
            binding.tab_id,
            binding.origin,
        )


async def _remove_stale_bindings(pairing_id: str, stale: list[tuple[str, int]]) -> None:
    if not stale:
        return
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        for _, tab_id in stale:
            await delete_tab_binding(
                db, pairing_id=uuid.UUID(pairing_id), tab_id=tab_id
            )
        await db.commit()


# ── REST status ───────────────────────────────────────────────────────────────


class PairingCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value


class PairingCodeResponse(BaseModel):
    code: str
    expires_in: int = 300


@router.post("/pairing/code", response_model=PairingCodeResponse, status_code=201)
async def issue_pairing_code(body: PairingCodeRequest) -> PairingCodeResponse:
    """Create a one-time code from an already-authenticated EvoFlux UI."""
    if not expected_desktop_token():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "pairing_requires_auth",
                "message": "Configure an EvoFlux access key before pairing WebBridge.",
            },
        )
    return PairingCodeResponse(code=webbridge_pairing_code_store.issue(body.label))


class PairingExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    browser: str = Field(default="unknown", max_length=40)
    version: str = Field(default="unknown", max_length=40)


class PairingExchangeResponse(BaseModel):
    pairing_id: str
    credential: str
    scopes: list[str]


class PairingInfo(BaseModel):
    pairing_id: str
    label: str
    browser: str
    version: str
    scopes: list[str]
    created_at: str
    last_seen_at: str


@router.post(
    "/pairing/exchange", response_model=PairingExchangeResponse, status_code=201
)
async def exchange_pairing_code(
    body: PairingExchangeRequest,
    db: DbSession,
) -> PairingExchangeResponse:
    """Exchange a one-time code for a revocable, scoped pairing credential."""
    grant = webbridge_pairing_code_store.consume(body.code)
    if grant is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "invalid_pairing_code",
                "message": "Code is invalid or expired.",
            },
        )
    pairing, credential = await create_pairing(
        db,
        grant=grant,
        browser=body.browser,
        version=body.version,
    )
    logger.info(
        "webbridge_paired pairing_id={} browser={}", pairing.id, pairing.browser
    )
    return PairingExchangeResponse(
        pairing_id=str(pairing.id),
        credential=credential,
        scopes=pairing.scopes,
    )


@router.get("/pairings", response_model=list[PairingInfo])
async def get_pairings(db: DbSession) -> list[PairingInfo]:
    pairings = await list_active_pairings(db)
    return [
        PairingInfo(
            pairing_id=str(pairing.id),
            label=pairing.label,
            browser=pairing.browser,
            version=pairing.version,
            scopes=pairing.scopes,
            created_at=pairing.created_at.isoformat(),
            last_seen_at=pairing.last_seen_at.isoformat(),
        )
        for pairing in pairings
    ]


@router.delete("/pairings/{pairing_id}", status_code=204)
async def delete_pairing(pairing_id: uuid.UUID, db: DbSession) -> None:
    pairing = await revoke_pairing(db, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found.")
    await db.commit()
    pairing_key = str(pairing_id)
    webbridge_ticket_store.revoke(pairing_key)
    await webbridge_manager.close_extension(pairing_key, code=4403)
    logger.info("webbridge_pairing_revoked pairing_id={}", pairing_id)


class RelayTicketResponse(BaseModel):
    ticket: str
    expires_in: int = 30


@router.post("/relay-ticket", response_model=RelayTicketResponse, status_code=201)
async def issue_relay_ticket(request: Request, db: DbSession) -> RelayTicketResponse:
    """Mint a single-use relay ticket without placing the credential in a URL."""
    pairing = await _paired_request(request, db, required_scope="relay")
    try:
        ticket = webbridge_ticket_store.issue(str(pairing.id))
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_pairing", "message": "Pairing was revoked."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return RelayTicketResponse(ticket=ticket)


class InteractionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tab_id: int | None = None
    page_instance_id: str | None = Field(default=None, max_length=128)
    origin: str = Field(default="", max_length=2048)
    user_gesture: bool = False


class InteractionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID | None = None


class InteractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_INTERACTION_METADATA_BYTES:
            raise ValueError("metadata exceeds 256000 bytes")
        return value


class InteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    delivery: Literal["draft", "submit"]
    source: InteractionSource = Field(default_factory=InteractionSource)
    target: InteractionTarget = Field(default_factory=InteractionTarget)
    payload: InteractionPayload = Field(default_factory=InteractionPayload)


class InteractionAck(BaseModel):
    interaction_id: str
    interaction_record_id: str
    status: str
    target_session_id: str | None = None
    message_id: str | None = None
    error_code: str | None = None
    error: str | None = None


class TabBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    origin: str = Field(default="", max_length=2048)
    page_instance_id: str | None = Field(default=None, max_length=128)


class TabBindingResponse(BaseModel):
    tab_id: int
    session_id: str
    origin: str
    page_instance_id: str | None
    expires_at: str


def _tab_binding_response(binding) -> TabBindingResponse:
    return TabBindingResponse(
        tab_id=binding.tab_id,
        session_id=str(binding.session_id),
        origin=binding.origin,
        page_instance_id=binding.page_instance_id,
        expires_at=binding.expires_at.isoformat(),
    )


@router.get("/bindings", response_model=list[TabBindingResponse])
async def get_tab_bindings(request: Request, db: DbSession) -> list[TabBindingResponse]:
    pairing = await _paired_request(request, db, required_scope="bindings:write")
    bindings = await list_tab_bindings(db, pairing.id)
    for binding in bindings:
        webbridge_manager.bind_session_tab(
            str(binding.session_id), str(pairing.id), binding.tab_id
        )
    return [_tab_binding_response(binding) for binding in bindings]


@router.put("/bindings/{tab_id}", response_model=TabBindingResponse)
async def bind_tab_to_session(
    tab_id: int,
    body: TabBindingRequest,
    request: Request,
    db: DbSession,
) -> TabBindingResponse:
    pairing = await _paired_request(request, db, required_scope="bindings:write")
    if await db.get(ChatSession, body.session_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "session_not_found",
                "message": "Target session not found.",
            },
        )
    binding = await upsert_tab_binding(
        db,
        pairing_id=pairing.id,
        tab_id=tab_id,
        session_id=body.session_id,
        origin=body.origin,
        page_instance_id=body.page_instance_id,
    )
    webbridge_manager.bind_session_tab(str(body.session_id), str(pairing.id), tab_id)
    return _tab_binding_response(binding)


@router.delete("/bindings/{tab_id}", status_code=204)
async def unbind_tab(tab_id: int, request: Request, db: DbSession) -> None:
    pairing = await _paired_request(request, db, required_scope="bindings:write")
    binding = await delete_tab_binding(db, pairing_id=pairing.id, tab_id=tab_id)
    if binding is not None:
        webbridge_manager.unbind_session_tab(
            str(binding.session_id), extension_id=str(pairing.id)
        )


@router.post("/interactions", response_model=InteractionAck)
async def ingest_interaction(
    body: InteractionRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> InteractionAck:
    """Persist one idempotent browser-originated interaction draft."""
    pairing = await _paired_request(request, db, required_scope="interactions:write")
    interaction_id = request.headers.get("idempotency-key", "").strip()
    if not interaction_id or len(interaction_id) > 128:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_idempotency_key",
                "message": "Idempotency-Key is required and must be at most 128 characters.",
            },
        )

    target_session_id = body.target.session_id
    prompt = body.payload.prompt
    normalized_prompt = prompt.strip() if prompt is not None else ""
    if body.delivery == "submit":
        if not body.source.user_gesture:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "user_gesture_required",
                    "message": "Submitting an interaction requires a user gesture.",
                },
            )
        if target_session_id is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "session_required",
                    "message": "Submit delivery requires a target session.",
                },
            )
        if not normalized_prompt:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "prompt_required",
                    "message": "Submit delivery requires a non-blank prompt.",
                },
            )
    refusal = webbridge_manager.check_interaction_policy(
        origin=body.source.origin,
        user_gesture=body.source.user_gesture,
        context_type=body.payload.metadata.get("context_type"),
    )
    if refusal is not None:
        raise HTTPException(
            status_code=403,
            detail={"code": "sharing_policy_refused", "message": refusal},
        )
    if target_session_id is not None:
        session = await db.get(ChatSession, target_session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "session_not_found",
                    "message": "Target session not found.",
                },
            )

    request_payload = body.model_dump(mode="json")
    try:
        interaction, created = await create_or_get_interaction(
            db,
            pairing_id=pairing.id,
            interaction_id=interaction_id,
            request_payload=request_payload,
            kind=body.kind,
            delivery=body.delivery,
            status="draft" if body.delivery == "draft" else "pending",
            target_session_id=target_session_id,
            origin=body.source.origin,
            tab_id=body.source.tab_id,
            page_instance_id=body.source.page_instance_id,
            payload_metadata=body.payload.metadata,
            prompt=prompt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc

    if created:
        max_per_minute = webbridge_manager._policy().interactions.max_per_minute
        if not webbridge_interaction_rate_limiter.allow(
            str(pairing.id), max_per_minute
        ):
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": "Too many browser interactions. Try again shortly.",
                },
                headers={"Retry-After": "60"},
            )

    should_dispatch = False
    if body.delivery == "submit":
        if created:
            await db.commit()
        should_dispatch = await claim_interaction_dispatch(db, interaction)

    if should_dispatch:
        try:
            session, team = await resolve_team_for_session(
                db, str(target_session_id), require_existing=True
            )
            assert session is not None
            result = await submit_persisted_interactive_message(
                db,
                session=session,
                team=team,
                content=normalized_prompt,
            )
            interaction.status = result.status
            interaction.message_id = result.message_id
        except (NoTeamConfigured, ValueError) as exc:
            interaction.status = "rejected"
            interaction.error_code = "dispatch_unavailable"
            interaction.error = str(exc)
        except Exception as exc:
            logger.exception(
                "webbridge_interaction_dispatch_failed interaction_id={} type={}",
                interaction_id,
                type(exc).__name__,
            )
            interaction.status = "rejected"
            interaction.error_code = "dispatch_failed"
            interaction.error = "Browser interaction could not be dispatched."
        interaction.processed_at = datetime.now(timezone.utc)
        interaction.dispatch_lease_until = None
        db.add(interaction)
        await db.commit()

    response.status_code = 202 if created else 200
    return InteractionAck(
        interaction_id=interaction.interaction_id,
        interaction_record_id=str(interaction.id),
        status=interaction.status,
        target_session_id=(
            str(interaction.target_session_id)
            if interaction.target_session_id is not None
            else None
        ),
        message_id=str(interaction.message_id) if interaction.message_id else None,
        error_code=interaction.error_code,
        error=interaction.error,
    )


class ExtensionInfo(BaseModel):
    extension_id: str
    browser: str
    version: str
    protocol_version: int = 1
    capabilities: dict[str, Any] = Field(default_factory=dict)
    paired: bool = False
    connected_at: float
    current_url: str = ""
    current_title: str = ""
    tabs: list[dict[str, Any]] = Field(default_factory=list)


class WebBridgeStatusResponse(BaseModel):
    connected: bool
    extensions: list[ExtensionInfo] = Field(default_factory=list)


@router.get("/status")
async def get_webbridge_status() -> WebBridgeStatusResponse:
    """Return list of connected browser extensions."""
    status = webbridge_manager.status()
    return WebBridgeStatusResponse(
        connected=status["connected"],
        extensions=[ExtensionInfo(**ext) for ext in status["extensions"]],
    )


class AuditEntry(BaseModel):
    ts: float
    session_id: str
    extension_id: str | None = None
    action: str
    url: str = ""
    success: bool
    error: str | None = None


class WebBridgeAuditResponse(BaseModel):
    entries: list[AuditEntry] = Field(default_factory=list)


@router.get("/audit")
async def get_webbridge_audit(limit: int | None = None) -> WebBridgeAuditResponse:
    """Most-recent-first log of commands the agent ran against the browser.

    Because WebBridge drives a real, logged-in browser, this trail lets the
    user review exactly what the agent did (and what the domain policy
    refused). ``limit`` caps the count; the default comes from
    ``webbridge.audit_log_size``.
    """
    entries = webbridge_manager.audit_entries(limit)
    return WebBridgeAuditResponse(entries=[AuditEntry(**e) for e in entries])


# ── Guided browser launch (auto-install) ──────────────────────────────────────

_EXTENSION_DIR_ENV = "EVOFLUX_WEBBRIDGE_EXTENSION_DIR"

# Chrome install locations probed on Windows when ``chrome`` is not on PATH.
_WIN_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)

_LAUNCH_MESSAGE = (
    "Browser launched with the WebBridge extension loaded. Note: Chrome must "
    "have been FULLY quit before this launch — an already-running Chrome "
    "ignores the extension flags. Chrome also shows a developer-mode "
    "extension bubble on each launch; that is expected for unpacked "
    "extensions — keep the extension enabled to use WebBridge."
)


class LaunchBrowserResponse(BaseModel):
    ok: bool
    browser: str
    message: str


def _resolve_extension_dir() -> Path | None:
    """Locate the unpacked WebBridge extension directory.

    The ``EVOFLUX_WEBBRIDGE_EXTENSION_DIR`` override wins when set; otherwise
    fall back to ``<repo root>/extensions/webbridge`` (repo root = two parents
    up from the ``app`` package). Returns ``None`` when no candidate resolves
    to an existing directory — the caller turns that into a 404 with
    manual-install instructions.
    """
    override = os.environ.get(_EXTENSION_DIR_ENV)
    if override:
        candidate = Path(override).expanduser()
    else:
        import app as _app_pkg

        repo_root = Path(_app_pkg.__file__).resolve().parent.parent
        candidate = repo_root / "extensions" / "webbridge"
    return candidate if candidate.is_dir() else None


# Files/dirs never worth shipping in the downloadable package.
_PACKAGE_SKIP_DIRS = frozenset({"__pycache__", ".git", "node_modules"})
_PACKAGE_SKIP_NAMES = frozenset({".DS_Store", "Thumbs.db"})
_PACKAGE_FILENAME = "evoflux-webbridge.zip"


@router.get("/download")
async def download_extension() -> Response:
    """Return the unpacked WebBridge extension as a downloadable ``.zip``.

    Lets a user install the extension without hunting for a folder: download,
    unzip, then ``Load unpacked`` the ``webbridge/`` directory. Files are
    nested under a top-level ``webbridge/`` so the unzip yields one clean
    folder to point Chrome at.
    """
    ext_dir = _resolve_extension_dir()
    if ext_dir is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "WebBridge extension directory not found. Set "
                f"${_EXTENSION_DIR_ENV} or install from the source tree's "
                "extensions/webbridge directory."
            ),
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ext_dir.rglob("*")):
            rel = path.relative_to(ext_dir)
            if any(part in _PACKAGE_SKIP_DIRS for part in rel.parts):
                continue
            if path.name in _PACKAGE_SKIP_NAMES:
                continue
            if path.is_file():
                zf.write(path, arcname=str(Path("webbridge") / rel))

    logger.info("webbridge_download_extension bytes={}", buf.tell())
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_PACKAGE_FILENAME}"'},
    )


# Chrome launch flags:
# - --load-extension: side-load the unpacked WebBridge extension.
# - --silent-debugger-extension-api: suppress the yellow "<ext> started
#   debugging this browser" infobar that chrome.debugger otherwise shows on
#   every CDP attach. It only takes effect for a Chrome *started* with the
#   flag, which is why the guided launch fully relaunches the browser.
def _chrome_flags(extension_dir: Path) -> list[str]:
    return [
        f"--load-extension={extension_dir}",
        "--silent-debugger-extension-api",
    ]


def _chrome_launch_command(
    extension_dir: Path,
) -> tuple[str, list[str], dict[str, Any]]:
    """Return ``(browser_label, argv, popen_kwargs)`` for the current platform.

    Raises ``RuntimeError`` with a user-facing message when no Chrome-family
    executable can be found or the platform is unsupported.
    """
    flags = _chrome_flags(extension_dir)
    if sys.platform == "darwin":
        return "chrome", ["open", "-na", "Google Chrome", "--args", *flags], {}
    if sys.platform == "win32":
        exe = shutil.which("chrome")
        if exe is None:
            for candidate in _WIN_CHROME_CANDIDATES:
                expanded = os.path.expandvars(candidate)
                if Path(expanded).is_file():
                    exe = expanded
                    break
        if exe is None:
            raise RuntimeError(
                "Google Chrome was not found on this machine. Install Chrome, "
                "or load the extension manually from chrome://extensions."
            )
        # DETACHED_PROCESS + CREATE_NO_WINDOW: fully independent of this
        # process, no console window. getattr defaults keep this importable
        # (and testable) on non-Windows hosts where the constants don't exist.
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        return "chrome", [exe, *flags], {"creationflags": creationflags}
    if sys.platform.startswith("linux"):
        exe = shutil.which("google-chrome") or shutil.which("chromium")
        if exe is None:
            raise RuntimeError(
                "Neither google-chrome nor chromium was found on PATH. Install "
                "Chrome or Chromium, or load the extension manually from "
                "chrome://extensions."
            )
        browser = "chromium" if "chromium" in Path(exe).name else "chrome"
        return browser, [exe, *flags], {}
    raise RuntimeError(
        f"Unsupported platform '{sys.platform}'. Load the extension manually "
        "from chrome://extensions instead."
    )


@router.post("/launch-browser")
async def launch_browser() -> LaunchBrowserResponse:
    """Launch the user's Chrome-family browser with the extension loaded.

    Guided auto-install: spawns Chrome with ``--load-extension`` pointing at
    the unpacked WebBridge extension, so the user never has to visit
    chrome://extensions by hand. The process is spawned detached — this
    endpoint never waits on the browser.
    """
    extension_dir = _resolve_extension_dir()
    if extension_dir is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "WebBridge extension directory not found (looked at "
                f"${_EXTENSION_DIR_ENV} and <install>/extensions/webbridge). "
                "Install it manually: open chrome://extensions, enable "
                "Developer mode, then 'Load unpacked' and select the "
                "extensions/webbridge directory from your EvoFlux installation."
            ),
        )
    try:
        browser, argv, popen_kwargs = _chrome_launch_command(extension_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        subprocess.Popen(  # noqa: S603 — argv is built from trusted local paths
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **popen_kwargs,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to launch {browser}: {exc}"
        ) from exc
    logger.info("webbridge_launch_browser browser={} argv={}", browser, argv)
    return LaunchBrowserResponse(ok=True, browser=browser, message=_LAUNCH_MESSAGE)


# ── Extension WebSocket ───────────────────────────────────────────────────────


@router.websocket("/relay")
async def extension_relay(ws: WebSocket) -> None:
    """WebSocket endpoint for browser extensions to connect.

    Protocol (extension → relay):
    - ``{"type": "register", "extension_id": "...", "browser": "chrome", "version": "120"}``
    - ``{"type": "response", "request_id": "...", "success": true, "data": {...}}``
    - ``{"type": "event", "event": "tab_updated", "data": {...}}``
    - ``{"type": "ping"}`` — heartbeat (refreshes liveness)

    Protocol (relay → extension):
    - ``{"type": "registered", "extension_id": "..."}``
    - ``{"type": "command", "request_id": "...", "action": "...", "params": {...}}``
    - ``{"type": "pong"}`` — heartbeat reply
    """
    authorized, pairing_id = await _extension_ws_authorization(ws)
    if not authorized:
        return
    await ws.accept()
    extension_id: str | None = None
    registered_connection: ExtensionConnection | None = None

    try:
        while True:
            raw = await ws.receive_text()
            if len(raw.encode("utf-8")) > _MAX_RELAY_FRAME_BYTES:
                await ws.close(code=1009)
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type")

            if msg_type == "register":
                if pairing_id is not None and webbridge_ticket_store.is_revoked(
                    pairing_id
                ):
                    await ws.close(code=4403)
                    break
                extension_id = (
                    pairing_id or msg.get("extension_id") or str(uuid.uuid4())
                )
                previous_connection = webbridge_manager.get_extension(extension_id)
                registered_connection = webbridge_manager.register_extension(
                    extension_id=extension_id,
                    browser=msg.get("browser", "unknown"),
                    version=msg.get("version", "unknown"),
                    send=ws.send_text,
                    protocol_version=msg.get("protocol_version", 1),
                    capabilities=msg.get("capabilities", {}),
                    close=lambda code: ws.close(code=code),
                    paired=pairing_id is not None,
                )
                if pairing_id is not None:
                    await _stage_persisted_bindings(pairing_id)
                if (
                    previous_connection is not None
                    and previous_connection.close is not None
                ):
                    try:
                        await previous_connection.close(4409)
                    except Exception as exc:
                        logger.debug(
                            "webbridge_replaced_socket_close_failed extension_id={} error={}",
                            extension_id,
                            exc,
                        )
                ack: dict[str, Any] = {
                    "type": "registered",
                    "extension_id": extension_id,
                }
                if pairing_id is not None:
                    ack.update({"pairing_id": pairing_id, "protocol_version": 2})
                await ws.send_text(json.dumps(ack))
            elif extension_id is None:
                # Everything below requires a registered connection.
                continue
            elif msg_type == "response":
                webbridge_manager.handle_response(
                    msg.get("request_id", ""),
                    success=msg.get("success", False),
                    data=msg.get("data"),
                    error=msg.get("error"),
                    extension_id=extension_id,
                    connection=registered_connection,
                )
            elif msg_type == "event":
                event_name = msg.get("event")
                event_data = msg.get("data", {})
                webbridge_manager.handle_event(
                    extension_id,
                    event_name,
                    event_data,
                    connection=registered_connection,
                )
                if pairing_id is not None and event_name == "tab_updated":
                    stale = webbridge_manager.validate_pending_tab_bindings(
                        pairing_id, event_data.get("tabs", [])
                    )
                    await _remove_stale_bindings(pairing_id, stale)
            elif msg_type == "ping":
                webbridge_manager.touch(extension_id, connection=registered_connection)
                await ws.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "pong":
                webbridge_manager.touch(extension_id, connection=registered_connection)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("webbridge_ext_error extension_id={} error={}", extension_id, e)
    finally:
        if extension_id:
            # Fails every command still pending on this extension.
            webbridge_manager.unregister_extension(
                extension_id, connection=registered_connection
            )


# ── Agent WebSocket ───────────────────────────────────────────────────────────


@router.websocket("/agent/{session_id}")
async def agent_relay(ws: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for external agent consumers of WebBridge.

    The in-process ``webbridge`` tool does not use this endpoint — it calls
    the manager directly. This remains for external consumers and tests.

    Protocol (agent → relay):
    - ``{"action": "navigate", "url": "..."}``
    - ``{"action": "click", "x": 100, "y": 200}``
    - ``{"action": "type", "text": "hello"}``
    - ``{"action": "screenshot"}``
    - ``{"action": "get_tabs"}``
    - ``{"action": "switch_tab", "index": 0}``
    - ``{"action": "evaluate", "script": "document.title"}``
    - ``{"action": "extract"}``
    - ``{"action": "status"}``

    Protocol (relay → agent):
    - ``{"type": "response", "request_id": "...", "success": true, "data": {...}}``
    - ``{"type": "event", "event": "...", "data": {...}}``
    - ``{"type": "no_extension", "error": "..."}``
    """
    if not await _ws_authorized(ws):
        return
    await ws.accept()
    queue = webbridge_manager.subscribe_agent(session_id)
    logger.info("webbridge_agent_connected session_id={}", session_id)

    async def forward_events() -> None:
        try:
            while True:
                event = await queue.get()
                await ws.send_text(json.dumps(event))
        except Exception:
            pass

    event_task = asyncio.create_task(forward_events())
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw.encode("utf-8")) > _MAX_RELAY_FRAME_BYTES:
                await ws.close(code=1009)
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action")
            if not action:
                continue

            if action != "status" and not webbridge_manager.has_active_extension():
                await ws.send_text(
                    json.dumps({"type": "no_extension", "error": NO_EXTENSION_ERROR})
                )
                continue

            params = {k: v for k, v in msg.items() if k != "action"}
            result = await webbridge_manager.send_command(session_id, action, params)
            await ws.send_text(json.dumps({"type": "response", **result}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("webbridge_agent_error session_id={} error={}", session_id, e)
    finally:
        event_task.cancel()
        webbridge_manager.unsubscribe_agent(session_id, queue)
        logger.info("webbridge_agent_disconnected session_id={}", session_id)
