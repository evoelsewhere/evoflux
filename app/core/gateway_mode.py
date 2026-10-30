"""Opt-in startup switches for running behind the Rust ``evoflux-server`` gateway.

The v4 gateway owns the UI-facing port and starts this sidecar as a child on a
private loopback port. It sets the environment variables below; with none of
them set the sidecar behaves exactly like v3.

- ``EVOFLUX_GATEWAY_SECRET``: every HTTP and WebSocket request must carry
  ``X-EvoFlux-Gateway: <secret>`` or it is refused with 403. No path is exempt.
- ``EVOFLUX_REMOTE_PROXY_SECRET``: replaces the random per-process secret that
  authenticates the tailnet identity headers (see ``desktop_auth``).
- ``EVOFLUX_TSNET_TARGET_PORT``: port the tailnet helper forwards to (the
  gateway's) instead of this sidecar's own.
- ``EVOFLUX_DISABLE_SERVICES``: comma list of background services that must not
  start here because their cutover unit now runs in Rust.
"""

from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

GATEWAY_HEADER = "X-EvoFlux-Gateway"

_SECRET_ENV = "EVOFLUX_GATEWAY_SECRET"
_REMOTE_PROXY_SECRET_ENV = "EVOFLUX_REMOTE_PROXY_SECRET"
_TSNET_PORT_ENV = "EVOFLUX_TSNET_TARGET_PORT"
_DISABLE_ENV = "EVOFLUX_DISABLE_SERVICES"

SERVICE_NAMES: frozenset[str] = frozenset(
    {
        "otel_retention",
        "model_registry_refresh",
        "mcp",
        "plugin_mcp",
        "conductor",
        "agents_validation",
        "scheduler",
        "dream_scheduler",
        "memory_backfill",
        "standalone_coding_purge",
        "webbridge_cleanup",
        "webbridge_artifact_cleanup",
    }
)

_GATEWAY_HEADER_BYTES = GATEWAY_HEADER.lower().encode("latin-1")


def gateway_secret() -> str:
    """The configured gateway secret, or ``""`` when gateway mode is off."""
    return os.environ.get(_SECRET_ENV, "").strip()


def remote_proxy_secret() -> str | None:
    """The gateway-provided tailnet proxy secret, or ``None`` to use a random one."""
    return os.environ.get(_REMOTE_PROXY_SECRET_ENV, "").strip() or None


def tsnet_target_port() -> int | None:
    """Port the tailnet helper should target instead of this sidecar's own."""
    raw = os.environ.get(_TSNET_PORT_ENV, "").strip()
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if 0 < port < 65536 else None


def disabled_services() -> frozenset[str]:
    """Background services disabled by ``EVOFLUX_DISABLE_SERVICES``.

    Raises ``ValueError`` for a name outside :data:`SERVICE_NAMES`, so a typo in
    the gateway's configuration fails startup instead of running a service in
    both processes.
    """
    names = {
        part.strip()
        for part in os.environ.get(_DISABLE_ENV, "").split(",")
        if part.strip()
    }
    unknown = sorted(names - SERVICE_NAMES)
    if unknown:
        raise ValueError(
            f"{_DISABLE_ENV} has unknown service name(s): {', '.join(unknown)}. "
            f"Valid names: {', '.join(sorted(SERVICE_NAMES))}"
        )
    return frozenset(names)


class GatewaySecretMiddleware:
    """Refuse any request that did not come through the gateway.

    Pure ASGI so it covers WebSockets as well as HTTP, and registered outermost
    so the check runs before metrics, auth and CORS. The secret is read once at
    construction; with no secret the middleware is a no-op.
    """

    def __init__(self, app: ASGIApp, *, secret: str | None = None) -> None:
        self.app = app
        self._secret = (secret if secret is not None else gateway_secret()).encode(
            "utf-8"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._secret or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        provided = b""
        for name, value in scope.get("headers", ()):
            if name == _GATEWAY_HEADER_BYTES:
                provided = value
                break
        if hmac.compare_digest(provided, self._secret):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # Closing before accept answers the handshake with HTTP 403.
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            status_code=403, content={"detail": "Direct backend access is not allowed."}
        )
        await response(scope, receive, send)
