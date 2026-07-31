"""Custom ASGI middlewares for EvoFlux.

Add to the FastAPI app via ``app.add_middleware(...)`` in the application factory.

Usage::

    from app.core.middlewares import RequestSizeLimitMiddleware, SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=4 * 1024 * 1024)
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Default: 100 MB. Large local artifact uploads are supported, while the
# middleware still prevents unbounded request bodies from exhausting memory.
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024

# ── Security headers ─────────────────────────────────────────────────────────
# EvoFlux is an on-machine single-owner app.  The bundled web UI is served
# as static assets from the same origin, so a strict same-origin CSP is
# sufficient and no third-party embedding is expected.
#
# - `connect-src` allows ws:/wss: for future SSE fallback clients; SSE itself
#   uses plain HTTP which is already covered by `default-src 'self'`.
# - `style-src` allows `'unsafe-inline'` because Vite injects critical CSS and
#   Tailwind's JIT occasionally emits inline styles.  A stricter nonce-based
#   policy would require rewriting index.html at request time.
# - `img-src` allows `data:` and `blob:` for user-uploaded previews and
#   assistant-rendered canvases.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

_DEFAULT_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Content-Security-Policy": _DEFAULT_CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach defensive security headers to every response.

    Defaults are tuned for a same-origin, on-machine SPA + API.  HSTS is
    enabled only when ``enable_hsts=True`` because forcing HTTPS on a loopback
    install (``http://localhost:4082``) would make the site unreachable.

    Callers can override any individual header by passing ``extra_headers`` —
    values there win over the defaults.  Pass an empty string as the value to
    remove a default header entirely.

    Args:
        app: The ASGI application to wrap.
        extra_headers: Header overrides / additions.  Keys are
            case-insensitive; values take precedence over defaults.
        enable_hsts: If ``True``, adds a 1-year ``Strict-Transport-Security``
            header with ``includeSubDomains``.  Only enable behind TLS.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        extra_headers: dict[str, str] | None = None,
        enable_hsts: bool = False,
    ) -> None:
        super().__init__(app)
        headers = dict(_DEFAULT_SECURITY_HEADERS)
        if enable_hsts:
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if extra_headers:
            for k, v in extra_headers.items():
                headers[k] = v
        # Drop keys explicitly cleared by caller (empty string value).
        self._headers = {k: v for k, v in headers.items() if v != ""}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in self._headers.items():
            # Do not overwrite headers the route explicitly set.
            if name not in response.headers:
                response.headers[name] = value
        return response


class RequestSizeLimitMiddleware:
    """Reject request bodies that exceed ``max_bytes``.

    A valid ``Content-Length`` is rejected before the body is read. Chunked and
    otherwise streamed bodies are counted as the application consumes them, so
    omitting the header cannot bypass the limit.

    Args:
        app: The ASGI application to wrap.
        max_bytes: Maximum allowed content length in bytes. Defaults to 100 MB.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if content_lengths:
            try:
                parsed_lengths = {int(value) for value in content_lengths}
            except ValueError:
                await self._send_error(
                    scope, receive, send, 400, "Invalid Content-Length."
                )
                return

            if len(parsed_lengths) != 1 or next(iter(parsed_lengths)) < 0:
                await self._send_error(
                    scope, receive, send, 400, "Invalid Content-Length."
                )
                return

            content_length = next(iter(parsed_lengths))
            if content_length > self._max_bytes:
                logger.warning(
                    "request_too_large content_length={} limit={}",
                    content_length,
                    self._max_bytes,
                )
                await self._send_error(
                    scope,
                    receive,
                    send,
                    413,
                    "Request body too large.",
                )
                return

        received_bytes = 0
        buffered_messages: list[Message] = []
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_bytes:
                    logger.warning(
                        "request_too_large streamed_bytes={} limit={}",
                        received_bytes,
                        self._max_bytes,
                    )
                    await self._send_error(
                        scope,
                        receive,
                        send,
                        413,
                        "Request body too large.",
                    )
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def replay_receive() -> Message:
            if buffered_messages:
                return buffered_messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)
