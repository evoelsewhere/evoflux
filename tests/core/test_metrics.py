"""Tests for app/core/metrics.py — Prometheus registry + middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from app.core.metrics import (
    HTTPMetricsMiddleware,
    HTTP_REQUESTS,
    REGISTRY,
    SPANS_DROPPED,
    metrics_endpoint,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(HTTPMetricsMiddleware)
    app.add_route("/metrics", metrics_endpoint, methods=["GET"])

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/fail")
    async def fail():
        raise RuntimeError("boom")

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        return {"id": item_id}

    return app


class TestMetricsEndpoint:
    def test_method_not_allowed_logs_route_template_and_allow_header(self):
        captured: list[str] = []
        sink_id = logger.add(
            lambda message: captured.append(str(message)), level="WARNING"
        )
        try:
            response = TestClient(_make_app()).post("/items/private-id")
        finally:
            logger.remove(sink_id)

        assert response.status_code == 405
        assert any(
            "http_method_not_allowed" in message
            and "method=POST" in message
            and "route=/items/{item_id}" in message
            and "allow=GET, HEAD" in message
            and "private-id" not in message
            for message in captured
        )

    def test_serves_prometheus_text(self):
        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "EVOFLUX_http_requests_total" in resp.text

    def test_request_counter_increments(self):
        client = TestClient(_make_app())
        before = _counter_value(
            "EVOFLUX_http_requests_total", method="GET", route="/ok", status="2xx"
        )
        client.get("/ok")
        client.get("/ok")
        after = _counter_value(
            "EVOFLUX_http_requests_total", method="GET", route="/ok", status="2xx"
        )
        assert after - before == 2

    def test_5xx_recorded_on_exception(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        before = _counter_value(
            "EVOFLUX_http_requests_total", method="GET", route="/fail", status="5xx"
        )
        client.get("/fail")
        after = _counter_value(
            "EVOFLUX_http_requests_total", method="GET", route="/fail", status="5xx"
        )
        assert after - before == 1

    def test_route_template_used_not_raw_path(self):
        """Cardinality guard: /items/123 and /items/456 share a label."""
        client = TestClient(_make_app())
        before = _counter_value(
            "EVOFLUX_http_requests_total",
            method="GET",
            route="/items/{item_id}",
            status="2xx",
        )
        client.get("/items/abc")
        client.get("/items/xyz")
        after = _counter_value(
            "EVOFLUX_http_requests_total",
            method="GET",
            route="/items/{item_id}",
            status="2xx",
        )
        assert after - before == 2

    def test_metrics_endpoint_does_not_self_count(self):
        client = TestClient(_make_app())
        before = _counter_value(
            "EVOFLUX_http_requests_total",
            method="GET",
            route="/metrics",
            status="2xx",
        )
        client.get("/metrics")
        after = _counter_value(
            "EVOFLUX_http_requests_total",
            method="GET",
            route="/metrics",
            status="2xx",
        )
        assert after == before


def test_spans_dropped_counter_exists():
    # Just assert it's importable and incrementable.
    before = _get_counter_value(SPANS_DROPPED)
    SPANS_DROPPED.inc()
    after = _get_counter_value(SPANS_DROPPED)
    assert after - before == 1


# ── helpers ───────────────────────────────────────────────────────────────────


def _get_counter_value(counter) -> float:  # noqa: ANN001
    # Counter exposes `.collect()` returning MetricFamily objects.
    total = 0.0
    for m in counter.collect():
        for s in m.samples:
            if s.name.endswith("_total"):
                total += s.value
    return total


def _counter_value(metric_name: str, **labels: str) -> float:
    """Read a specific labeled counter value from the global registry."""
    for metric in REGISTRY.collect():
        if metric.name != metric_name.removesuffix("_total"):
            continue
        for sample in metric.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return 0.0


def test_http_requests_counter_registered():
    # Sanity: counter is wired to our dedicated registry.
    assert any(m.name == "EVOFLUX_http_requests" for m in REGISTRY.collect())
    assert HTTP_REQUESTS is not None
