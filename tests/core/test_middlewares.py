"""Tests for app/core/middlewares.py — RequestSizeLimitMiddleware + SecurityHeadersMiddleware."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from sse_starlette.sse import EventSourceResponse

from app.core.middlewares import RequestSizeLimitMiddleware, SecurityHeadersMiddleware


def _make_app(max_bytes: int = 100) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/upload")
    async def upload():
        return {"ok": True}

    return app


class TestRequestSizeLimitMiddleware:
    def test_request_within_limit_passes_through(self):
        client = TestClient(_make_app(max_bytes=100))
        resp = client.post(
            "/upload",
            content=b"x" * 50,
            headers={"Content-Length": "50"},
        )
        assert resp.status_code == 200

    def test_request_exactly_at_limit_passes_through(self):
        client = TestClient(_make_app(max_bytes=100))
        resp = client.post(
            "/upload",
            content=b"x" * 100,
            headers={"Content-Length": "100"},
        )
        assert resp.status_code == 200

    def test_request_exceeding_limit_returns_413(self):
        client = TestClient(_make_app(max_bytes=100))
        resp = client.post(
            "/upload",
            content=b"x" * 101,
            headers={"Content-Length": "101"},
        )
        assert resp.status_code == 413

    def test_413_body_contains_detail(self):
        client = TestClient(_make_app(max_bytes=10))
        resp = client.post(
            "/upload",
            content=b"x" * 20,
            headers={"Content-Length": "20"},
        )
        assert resp.json() == {"detail": "Request body too large."}

    def test_no_content_length_header_passes_through(self):
        """Requests without Content-Length (chunked) are allowed."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10)

        @app.post("/upload")
        async def upload():
            return {"ok": True}

        client = TestClient(app)
        # Send without explicit Content-Length by using params-based body
        resp = client.post("/upload")
        assert resp.status_code == 200

    def test_default_max_bytes_is_100mb(self):
        middleware = RequestSizeLimitMiddleware(app=FastAPI())
        assert middleware._max_bytes == 100 * 1024 * 1024

    def test_custom_max_bytes_stored(self):
        middleware = RequestSizeLimitMiddleware(app=FastAPI(), max_bytes=1024)
        assert middleware._max_bytes == 1024

    def test_oversized_streamed_body_without_content_length_returns_413(self):
        """A chunked body over the limit must not bypass the check."""

        def _chunks():
            for _ in range(4):
                yield b"x" * 40

        client = TestClient(_make_app(max_bytes=100))
        resp = client.post("/upload", content=_chunks())
        assert resp.status_code == 413
        assert resp.json() == {"detail": "Request body too large."}

    def test_streamed_body_within_limit_reaches_the_route(self):
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_bytes=100)

        @app.post("/echo")
        async def echo(payload: dict):
            return {"seen": payload["value"]}

        def _chunks():
            yield b'{"value":'
            yield b'"hello"}'

        client = TestClient(app)
        resp = client.post(
            "/echo",
            content=_chunks(),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"seen": "hello"}

    def test_duplicate_conflicting_content_length_is_rejected(self):
        middleware_app = _make_app(max_bytes=100)
        client = TestClient(middleware_app)
        resp = client.post(
            "/upload",
            content=b"x" * 5,
            headers=[("content-length", "5"), ("content-length", "6")],
        )
        assert resp.status_code == 400

    def test_non_numeric_content_length_is_rejected(self):
        client = TestClient(_make_app(max_bytes=100))
        resp = client.post(
            "/upload", content=b"x" * 5, headers={"content-length": "abc"}
        )
        assert resp.status_code == 400


class TestRequestSizeLimitMiddlewareStreaming:
    """The size limit must not truncate long-lived server-sent event streams."""

    @staticmethod
    def _sse_app() -> FastAPI:
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_bytes=100)

        @app.get("/events")
        async def events():
            async def _gen() -> AsyncGenerator[dict, None]:
                for index in range(3):
                    await asyncio.sleep(0.01)
                    yield {"event": "tick", "data": str(index)}

            return EventSourceResponse(_gen())

        return app

    def test_sse_stream_delivers_all_events(self):
        client = TestClient(self._sse_app())
        with client.stream("GET", "/events") as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "data: 0" in body
        assert "data: 1" in body
        assert "data: 2" in body

    def test_sse_stream_is_not_closed_before_first_event(self):
        """Regression: a fabricated ``http.disconnect`` killed every SSE stream."""
        client = TestClient(self._sse_app())
        with client.stream("GET", "/events") as resp:
            body = "".join(resp.iter_text())
        assert body.strip() != ""

    def test_websocket_passes_through_untouched(self):
        """The limiter is pure ASGI now — non-HTTP scopes must not be inspected."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10)

        @app.websocket("/ws")
        async def ws_echo(websocket: WebSocket):
            await websocket.accept()
            payload = await websocket.receive_text()
            await websocket.send_text(f"echo:{payload}")
            await websocket.close()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # Deliberately longer than max_bytes: the limit is HTTP-only.
            ws.send_text("x" * 64)
            assert ws.receive_text() == "echo:" + "x" * 64


# ── SecurityHeadersMiddleware ────────────────────────────────────────────────


def _make_secure_app(**kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, **kwargs)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/custom-csp")
    async def custom():
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"ok": True},
            headers={"Content-Security-Policy": "default-src 'none'"},
        )

    return app


class TestSecurityHeadersMiddleware:
    def test_default_headers_present(self):
        client = TestClient(_make_secure_app())
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert "geolocation=()" in resp.headers["Permissions-Policy"]
        assert resp.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert resp.headers["Cross-Origin-Resource-Policy"] == "cross-origin"
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]

    def test_hsts_disabled_by_default(self):
        client = TestClient(_make_secure_app())
        resp = client.get("/ping")
        assert "Strict-Transport-Security" not in resp.headers

    def test_hsts_enabled_on_request(self):
        client = TestClient(_make_secure_app(enable_hsts=True))
        resp = client.get("/ping")
        assert resp.headers["Strict-Transport-Security"].startswith("max-age=")
        assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]

    def test_extra_headers_override_defaults(self):
        client = TestClient(
            _make_secure_app(extra_headers={"Referrer-Policy": "same-origin"})
        )
        resp = client.get("/ping")
        assert resp.headers["Referrer-Policy"] == "same-origin"

    def test_extra_headers_empty_string_removes_default(self):
        client = TestClient(_make_secure_app(extra_headers={"X-Frame-Options": ""}))
        resp = client.get("/ping")
        assert "X-Frame-Options" not in resp.headers
        # Other defaults still there.
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_route_set_header_is_not_overwritten(self):
        """If the route already sets CSP, middleware must not clobber it."""
        client = TestClient(_make_secure_app())
        resp = client.get("/custom-csp")
        assert resp.headers["Content-Security-Policy"] == "default-src 'none'"
        # But other defaults still attached.
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
