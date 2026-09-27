"""Desktop session token authentication.

When the server is launched by the Tauri desktop shell, it is bound to
``127.0.0.1`` on an ephemeral port. Any other local process on the same
machine could otherwise reach the API. To prevent that, the shell
generates a random token per launch and passes it via the
``EVOFLUX_DESKTOP_TOKEN`` environment variable.

When that env var is set, this middleware rejects any request whose
``Authorization: Bearer <token>`` header (or ``?_token=`` query param,
for raw browser navigations and ``<a download>`` links) does not match.

When the env var is **not** set, the middleware is a no-op. CLI/server
users (``evoflux start``, etc.) keep the existing open-loopback
behaviour. This makes the desktop tier strictly opt-in.

Routes exempted from the check:

- ``/api/health/live``  — orchestrator probes need to work without auth.
- ``/api/health/ready`` — same.
- ``/metrics``          — Prometheus scrape target.
- ``/`` and SPA static assets — the bundled web UI needs to load *before*
  it can read the token and put it in its fetch headers.

The web UI receives the token via a script tag injected by the Tauri
shell into ``index.html`` (``window.__OAD_TOKEN__``) — see
``desktop/src-tauri`` for the injection logic.

Remote tailnet sessions
-----------------------

A request carrying a non-empty ``Tailscale-User-Login`` header — injected by
``tailscale serve`` on the tailnet HTTPS endpoint, never present on desktop
loopback requests — is attributed as a remote tailnet session. The bundled
``tsnet`` proxy also signs that header with an in-memory process secret, so a
local process cannot impersonate a tailnet peer while embedded mode is active.
The login is
stored on the request scope for routes (:func:`remote_session_login`) and the
single-device lock in ``app.services.remote_use_service`` is claimed
transparently for API paths. Another live session holding the lock
short-circuits the request with HTTP 409 (holder in the body). The desktop
bearer-token check is skipped for these requests — the tailnet identity *is*
the credential on that path; every other request follows the tiers above
unchanged.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import Request, WebSocket
from app.core.runtime_settings import load_runtime_settings
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


_ENV_VAR = "EVOFLUX_DESKTOP_TOKEN"
_ACCESS_KEY_ENV_VAR = "EVOFLUX_ACCESS_KEY"

# Exact paths that never require auth. Entries are matched literally —
# **not** as prefixes — so ``/metrics-evil`` cannot impersonate
# ``/metrics``.
_EXEMPT_EXACT: frozenset[str] = frozenset(
    {
        "/metrics",
        "/api/health/live",
        "/api/health/ready",
        # SPA shell entry points the UI may navigate to before it's
        # had a chance to read the token.
        "/",
        "/index.html",
        "/favicon.ico",
        "/favicon.svg",
        "/vite.svg",
        "/robots.txt",
        "/manifest.json",
    }
)

# Prefixes that *do* require a trailing slash to match. Anything matching
# one of these is treated as a static asset / sub-resource of a
# whitelisted directory.
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/health/",  # /api/health/<anything> — orchestrator probes
    "/assets/",  # vite-built JS/CSS chunks
    "/static/",  # legacy static dir, if any
)

# API endpoints that intentionally implement a separate, narrower credential
# contract. Native bootstrap is loopback/origin/token restricted; relay-ticket
# and interactions require a scoped WebBridge bearer. Keep this list exact.
_CUSTOM_AUTH_EXACT: frozenset[str] = frozenset(
    {
        "/api/team/webbridge/pairing/native",
        "/api/team/webbridge/relay-ticket",
        "/api/team/webbridge/interactions",
        "/api/team/webbridge/bindings",
        "/api/team/webbridge/sessions",
        "/api/team/webbridge/models",
        "/api/team/webbridge/appearance",
        "/api/team/webbridge/teach-drafts",
    }
)
_CUSTOM_AUTH_PREFIXES: tuple[str, ...] = (
    "/api/team/webbridge/bindings/",
    "/api/team/webbridge/sessions/",
)

# Query-string param name used by clients that cannot carry an Authorization
# header. We strip this *after* extraction so downstream middleware (access
# logs, metrics) don't see the secret. The external WebBridge agent WebSocket
# also uses it; the browser-extension relay uses pairing tickets instead.
_QS_TOKEN_PARAM = "_token"


def expected_desktop_token() -> str:
    """The configured desktop token, or ``""`` when token auth is disabled.

    Resolution order: ``EVOFLUX_DESKTOP_TOKEN`` (set by the Tauri shell),
    then ``EVOFLUX_ACCESS_KEY``, then ``server.access_key`` from runtime
    settings. Resolved fresh on each call so WS endpoints, which have no
    middleware of their own, can authenticate per connection.
    """
    return (
        os.environ.get(_ENV_VAR, "")
        or os.environ.get(_ACCESS_KEY_ENV_VAR, "")
        or (load_runtime_settings().server.access_key or "")
    )


def desktop_token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time check of a caller-supplied token against *expected*."""
    return bool(provided) and bool(expected) and hmac.compare_digest(provided, expected)


def _path_is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _path_is_exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return True
    # Non-API paths are SPA shell routes — let them through; the UI will
    # then attach the token to its API/SSE calls.
    return not _path_is_api(path)


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value.strip()
    # Query-string fallback for things browsers cannot send custom
    # headers with: ``<a href="/api/...?_token=...">`` downloads, embedded
    # ``<img src>`` previews, etc.
    qs_token = request.query_params.get(_QS_TOKEN_PARAM)
    if qs_token:
        return qs_token
    return None


def _strip_token_from_scope(request: Request) -> None:
    """Remove ``?_token=…`` from the scope so downstream middleware can't log it.

    Starlette stores the raw query string as bytes in ``scope["query_string"]``
    and the parsed mapping in ``scope["query_params"]`` is lazily derived
    from it. Rewriting the bytes is sufficient — any downstream code that
    re-parses sees the cleaned version.
    """
    raw = request.scope.get("query_string") or b""
    if not raw or _QS_TOKEN_PARAM.encode() not in raw:
        return
    from urllib.parse import parse_qsl, urlencode

    kept = [
        (k, v)
        for k, v in parse_qsl(raw.decode("latin-1"), keep_blank_values=True)
        if k != _QS_TOKEN_PARAM
    ]
    request.scope["query_string"] = urlencode(kept).encode("latin-1")


# Headers injected by Tailscale Serve on tailnet HTTPS requests. A non-empty
# Tailscale-User-Login marks a remote session; desktop loopback requests
# never carry these (tailscaled sets them only on the Serve frontend).
REMOTE_USER_LOGIN_HEADER = "Tailscale-User-Login"
REMOTE_DEVICE_LABEL_HEADER = "X-EvoFlux-Device-Label"
REMOTE_PROXY_MARKER_HEADER = "X-EvoFlux-Remote-Proxy"
REMOTE_PROXY_TOKEN_HEADER = "X-EvoFlux-Remote-Token"
REMOTE_PROXY_MARKER = "tsnet"
_EMBEDDED_REMOTE_PROXY_SECRET = os.urandom(32).hex()


def embedded_remote_proxy_secret() -> str:
    """Per-process secret shared only with the bundled tsnet child."""
    return _EMBEDDED_REMOTE_PROXY_SECRET


def _embedded_proxy_required() -> bool:
    provider = os.environ.get("EVOFLUX_REMOTE_USE_PROVIDER", "").strip().lower()
    return provider != "external" and bool(os.environ.get("EVOFLUX_TSNET_BIN"))


def _trusted_remote_proxy_headers(marker: str, provided: str) -> bool:
    if marker == REMOTE_PROXY_MARKER:
        return hmac.compare_digest(
            provided.encode("utf-8"),
            _EMBEDDED_REMOTE_PROXY_SECRET.encode("utf-8"),
        )
    return not _embedded_proxy_required()


def remote_session_login(request: Request) -> str | None:
    """Tailnet login attributed to this request by the identity hook.

    Attribution happens once in :meth:`DesktopTokenMiddleware.dispatch` — the
    only boundary that trusts the Serve identity header — so routes read the
    result here instead of re-parsing headers.
    """
    return getattr(request.state, "remote_user_login", None)


class DesktopTokenMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated API requests when a desktop token is configured.

    The expected token is read **once** at construction time so a leaked
    env var on a child process cannot bypass the check later, and so
    middleware behaviour is stable for the lifetime of the server.
    """

    def __init__(self, app: ASGIApp, *, expected_token: str | None = None) -> None:
        super().__init__(app)
        self._token = (
            expected_token if expected_token is not None else expected_desktop_token()
        )
        self._enabled = bool(self._token)
        if self._enabled:
            logger.info("desktop_token_auth_enabled token_len={}", len(self._token))

    async def dispatch(self, request: Request, call_next):
        remote_login = request.headers.get(REMOTE_USER_LOGIN_HEADER, "").strip()
        if remote_login:
            marker = request.headers.get(REMOTE_PROXY_MARKER_HEADER, "").strip()
            provided = request.headers.get(REMOTE_PROXY_TOKEN_HEADER, "")
            if not _trusted_remote_proxy_headers(marker, provided):
                logger.warning("remote_proxy_identity_rejected")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Untrusted tailnet identity."},
                )
            return await self._dispatch_remote(request, call_next, remote_login)
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if _path_is_exempt(path):
            return await call_next(request)
        if path in _CUSTOM_AUTH_EXACT or any(
            path.startswith(prefix) for prefix in _CUSTOM_AUTH_PREFIXES
        ):
            return await call_next(request)

        token = _extract_token(request)
        if not desktop_token_matches(token, self._token):
            logger.warning(
                "desktop_token_rejected path={} has_token={}",
                path,
                bool(token),
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized — EvoFlux access key required."},
            )
        # Scrub the QS-param token so it never reaches access logs,
        # metrics, or downstream handlers (which can log full URLs).
        _strip_token_from_scope(request)
        return await call_next(request)

    async def _dispatch_remote(self, request: Request, call_next, remote_login: str):
        """Attribute a tailnet-served request and gate it on the session lock.

        Minimal clean mechanism for the transparent lock claim: the claim
        lives here (middleware-lite inside the identity hook) so no API route
        can forget it and routes stay thin. The claim is a short DB call made
        outside any transaction; a conflicting live session short-circuits
        with HTTP 409 before the handler runs.
        """
        from app.services.remote_use_service import RemoteUseConflict, claim

        request.state.remote_user_login = remote_login
        if _path_is_api(request.url.path):
            device_label = request.headers.get(REMOTE_DEVICE_LABEL_HEADER)
            if device_label is None:
                device_label = request.headers.get("user-agent")
            try:
                await claim(remote_login, device_label)
            except RemoteUseConflict as conflict:
                logger.info(
                    "remote_lock_conflict blocked_login={} held_by={}",
                    remote_login,
                    conflict.current.user_login,
                )
                return JSONResponse(status_code=409, content=conflict.body())
        # The tailnet identity header is the authorization for Serve traffic;
        # the desktop bearer-token tiers above stay untouched for every
        # other request.
        return await call_next(request)


def trusted_local_origin(value: str | None) -> bool:
    """Whether an ``Origin`` header belongs to a caller we trust locally.

    A missing ``Origin`` means a non-browser client — a CLI, a test, the
    Tauri shell — which cannot be a drive-by. Browsers always send one on a
    WebSocket handshake, and a page served from anywhere but loopback has no
    business opening a socket into the desktop app.
    """
    if not value:
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return parsed.hostname.casefold() == "localhost"


async def websocket_authorized(ws: WebSocket) -> bool:
    """Authenticate a WebSocket the way the middleware authenticates HTTP.

    :class:`DesktopTokenMiddleware` derives from ``BaseHTTPMiddleware``,
    which Starlette runs for ``http`` scopes only — every WebSocket route
    passes it untouched. So each socket has to ask for itself, before
    ``accept()``, and close with 4401 rather than running handler logic on
    an unauthenticated connection.

    With a token configured (the packaged desktop shell sets one per
    launch) the ``?_token=`` query param must match. Without one — the
    open-loopback CLI tier — the origin check is what stops any page the
    user happens to be visiting from reaching 127.0.0.1: WebSocket
    handshakes are not subject to CORS, so the browser will make the
    connection and hand the page a live socket unless we refuse it here.
    """
    remote_login = ws.headers.get(REMOTE_USER_LOGIN_HEADER, "").strip()
    if remote_login:
        marker = ws.headers.get(REMOTE_PROXY_MARKER_HEADER, "").strip()
        provided = ws.headers.get(REMOTE_PROXY_TOKEN_HEADER, "")
        if not _trusted_remote_proxy_headers(marker, provided):
            logger.warning("ws_remote_proxy_identity_rejected path={}", ws.url.path)
            await ws.close(code=4401)
            return False
        from app.services.remote_use_service import RemoteUseConflict, claim

        device_label = ws.headers.get(REMOTE_DEVICE_LABEL_HEADER)
        if device_label is None:
            device_label = ws.headers.get("user-agent")
        try:
            await claim(remote_login, device_label)
        except RemoteUseConflict as conflict:
            logger.info(
                "ws_remote_lock_conflict blocked_login={} held_by={}",
                remote_login,
                conflict.current.user_login,
            )
            await ws.close(code=4409)
            return False
        return True

    expected = expected_desktop_token()
    if not expected:
        if trusted_local_origin(ws.headers.get("origin")):
            return True
        logger.warning("ws_origin_rejected path={}", ws.url.path)
        await ws.close(code=4401)
        return False
    if desktop_token_matches(ws.query_params.get(_QS_TOKEN_PARAM), expected):
        return True
    logger.warning("ws_token_rejected path={}", ws.url.path)
    await ws.close(code=4401)
    return False
