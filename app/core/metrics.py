"""Prometheus metrics registry + ASGI middleware.

Exposes a ``/metrics`` endpoint (text/plain in Prometheus exposition format)
and an ``HTTPMetricsMiddleware`` that records per-request duration + status
histograms.

Metric naming follows the Prometheus convention ``{namespace}_{subsystem}_
{name}_{unit}``.  Namespace is always ``EvoFlux``.

Usage::

    from app.core.metrics import (
        HTTPMetricsMiddleware,
        metrics_endpoint,
        SPANS_DROPPED,
        TURNS_TOTAL,
    )

    app.add_middleware(HTTPMetricsMiddleware)
    app.add_route("/metrics", metrics_endpoint)

    SPANS_DROPPED.inc()
    TURNS_TOTAL.labels(status="ok").inc()
"""

from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.routing import Match

# ── Registry ──────────────────────────────────────────────────────────────────
# Single process — use a dedicated registry so tests can reset it without
# touching the global default_registry (which would nuke other tests).

REGISTRY: CollectorRegistry = CollectorRegistry()

# ── HTTP metrics ──────────────────────────────────────────────────────────────

HTTP_REQUESTS = Counter(
    "EVOFLUX_http_requests_total",
    "Total HTTP requests grouped by method, route template, and status class.",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "EVOFLUX_http_request_duration_seconds",
    "HTTP request duration in seconds grouped by method and route template.",
    labelnames=("method", "route"),
    # Buckets tuned for API traffic: 1ms → 30s.
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        30.0,
    ),
    registry=REGISTRY,
)

# ─── Database metrics ───────────────────────────────────────────────

DB_POOL_CHECKED_OUT = Gauge(
    "EVOFLUX_db_pool_checked_out",
    "Connections currently checked out, split by the read/write lane.",
    labelnames=("lane",),
    registry=REGISTRY,
)

DB_POOL_WAIT = Histogram(
    "EVOFLUX_db_pool_wait_seconds",
    "Time spent acquiring a database connection, split by lane and route.",
    labelnames=("lane", "route"),
    buckets=(
        0.0005,
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
    ),
    registry=REGISTRY,
)

DB_POOL_TIMEOUTS = Counter(
    "EVOFLUX_db_pool_timeouts_total",
    "Database connection acquisition timeouts, split by lane and route.",
    labelnames=("lane", "route"),
    registry=REGISTRY,
)

DB_QUERY_DURATION = Histogram(
    "EVOFLUX_db_query_duration_seconds",
    "Database cursor execution duration, excluding pool checkout wait.",
    labelnames=("lane", "operation"),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)

DB_TRANSACTION_DURATION = Histogram(
    "EVOFLUX_db_transaction_duration_seconds",
    "Database transaction duration from begin through commit or rollback.",
    labelnames=("lane", "outcome"),
    buckets=(
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
        30,
    ),
    registry=REGISTRY,
)

# ── Agent / turn metrics ──────────────────────────────────────────────────────

TURNS_TOTAL = Counter(
    "EVOFLUX_turns_total",
    "Total agent turns completed, grouped by status (ok|error|cancelled).",
    labelnames=("status",),
    registry=REGISTRY,
)

TURN_DURATION = Histogram(
    "EVOFLUX_turn_duration_seconds",
    "End-to-end turn duration in seconds.",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)

TEAM_RESOLUTION_DURATION = Histogram(
    "EVOFLUX_team_resolution_duration_seconds",
    "Time to resolve a cached or cold team before message ingress.",
    labelnames=("mode", "result"),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)

# ── Coding navigation metrics ────────────────────────────────────────────────

CODE_NAVIGATION_TURNS = Counter(
    "EVOFLUX_code_navigation_turns_total",
    "Coding turns grouped by the first symbol-navigation strategy used.",
    labelnames=("strategy",),
    registry=REGISTRY,
)

CODE_CONTEXT_QUERIES = Counter(
    "EVOFLUX_code_context_queries_total",
    "Code-context queries grouped by tool and execution status.",
    labelnames=("tool", "status"),
    registry=REGISTRY,
)

CODE_CONTEXT_QUERY_DURATION = Histogram(
    "EVOFLUX_code_context_query_duration_seconds",
    "End-to-end code-context tool latency, including the freshness barrier.",
    labelnames=("tool",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)

CODE_CONTEXT_RESULT_TOKENS = Counter(
    "EVOFLUX_code_context_result_tokens_total",
    "Estimated tokens returned by code-context tools (UTF-8 bytes divided by four).",
    labelnames=("tool",),
    registry=REGISTRY,
)

CODE_NAVIGATION_TOOL_CALLS = Counter(
    "EVOFLUX_code_navigation_tool_calls_total",
    "Navigation calls grouped by tool, including graph and source fallbacks.",
    labelnames=("tool",),
    registry=REGISTRY,
)

CODE_NAVIGATION_DUPLICATE_CALLS = Counter(
    "EVOFLUX_code_navigation_duplicate_calls_total",
    "Repeated navigation calls with identical arguments inside one agent turn.",
    labelnames=("tool",),
    registry=REGISTRY,
)

CODE_NAVIGATION_CALLS_PER_TURN = Histogram(
    "EVOFLUX_code_navigation_calls_per_turn",
    "Actual graph and fallback navigation calls completed in one agent turn.",
    labelnames=("kind",),
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 34),
    registry=REGISTRY,
)

CODE_CONTEXT_RESULT_TOKENS_PER_TURN = Histogram(
    "EVOFLUX_code_context_result_tokens_per_turn",
    "Actual code-context result tokens returned in one agent turn.",
    buckets=(0, 256, 512, 1_024, 2_048, 4_096, 8_192, 12_288),
    registry=REGISTRY,
)

CODE_CONTEXT_ROUTING = Counter(
    "EVOFLUX_code_context_routing_total",
    "Symbol graph calls grouped by traversal strategy and freshness.",
    labelnames=("strategy", "freshness"),
    registry=REGISTRY,
)

# ── Observability plumbing metrics ────────────────────────────────────────────

SPANS_DROPPED = Counter(
    "EVOFLUX_otel_spans_dropped_total",
    "Spans dropped by the JSONL writer due to backpressure.",
    registry=REGISTRY,
)

SPANS_WRITTEN = Counter(
    "EVOFLUX_otel_spans_written_total",
    "Spans successfully flushed to the JSONL writer.",
    registry=REGISTRY,
)


# ── Middleware ────────────────────────────────────────────────────────────────


def _route_template(request: Request) -> str:
    """Return a stable route template ('/api/team/{sid}') for label cardinality.

    Falls back to the raw path when no route matches (404, /metrics, etc).
    """
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return request.url.path


def _status_class(status_code: int) -> str:
    """Reduce cardinality: group status codes into 2xx/3xx/4xx/5xx."""
    return f"{status_code // 100}xx"


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """Record per-request duration + status counter."""

    async def dispatch(self, request: Request, call_next):
        # Skip the /metrics endpoint itself — otherwise every scrape would
        # bump the counter and the histogram would drown in self-traffic.
        if request.url.path == "/metrics":
            return await call_next(request)

        from app.core.request_context import (
            bind_request_context,
            reset_request_context,
        )

        route = _route_template(request)
        context_tokens = bind_request_context(request.method, route)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            elapsed = time.perf_counter() - start
            HTTP_REQUESTS.labels(method=request.method, route=route, status="5xx").inc()
            HTTP_REQUEST_DURATION.labels(method=request.method, route=route).observe(
                elapsed
            )
            raise
        finally:
            reset_request_context(context_tokens)

        elapsed = time.perf_counter() - start
        HTTP_REQUESTS.labels(
            method=request.method, route=route, status=_status_class(status_code)
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, route=route).observe(
            elapsed
        )
        return response


# ── /metrics endpoint ─────────────────────────────────────────────────────────


async def metrics_endpoint(_request: Request) -> Response:
    """Expose the registry in Prometheus exposition format."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
