"""Low-cardinality request context shared by observability boundaries.

Database work frequently continues in background tasks after an HTTP request
returns.  Context variables give those tasks a stable origin label without
passing ``Request`` through the service and agent layers.
"""

from __future__ import annotations

from contextvars import ContextVar, Token


_REQUEST_METHOD: ContextVar[str] = ContextVar(
    "evoflux_request_method", default="BACKGROUND"
)
_REQUEST_ROUTE: ContextVar[str] = ContextVar(
    "evoflux_request_route", default="background"
)


def bind_request_context(method: str, route: str) -> tuple[Token[str], Token[str]]:
    """Bind one HTTP request's stable method and route template."""

    return _REQUEST_METHOD.set(method), _REQUEST_ROUTE.set(route)


def reset_request_context(tokens: tuple[Token[str], Token[str]]) -> None:
    """Restore the context that preceded :func:`bind_request_context`."""

    method_token, route_token = tokens
    _REQUEST_METHOD.reset(method_token)
    _REQUEST_ROUTE.reset(route_token)


def request_origin() -> tuple[str, str]:
    """Return ``(method, route)`` for logs and bounded metric labels."""

    return _REQUEST_METHOD.get(), _REQUEST_ROUTE.get()


__all__ = ["bind_request_context", "request_origin", "reset_request_context"]
