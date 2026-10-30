"""Stand-in for the Python sidecar behind the gateway, standard library only.

The gateway starts it exactly like the real sidecar (bootstrap, then
``serve --host 127.0.0.1 --port 0 --handshake``) and reads the same
``EVOFLUX_HANDSHAKE`` line. Like ``app/core/gateway_mode.py`` it answers 403
unless ``X-EvoFlux-Gateway`` carries ``EVOFLUX_GATEWAY_SECRET``.

Routes:

- ``GET /fake/headers``: the request headers as a JSON object (lower-case names).
- ``GET /fake/sse``: event ``one``, a 1 s pause, event ``two``, then a ``tick``
  every 100 ms for up to 30 s; the time the client went away is recorded.
- ``GET /fake/sse-status``: ``{"disconnected_at": <unix time or null>}``.
- ``POST /fake/upload``: reads the body (length or chunked), answers ``{"bytes": n}``.
- ``GET /fake/env``: its ``EVOFLUX_*`` environment variables.
- ``GET /fake/child``: ``{"pid": n}`` of a sleeping child process it started.
- anything else: 404 ``{"detail": "Not Found"}``.
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_SECRET = os.environ.get("EVOFLUX_GATEWAY_SECRET", "").encode()
_STATE: dict[str, float | None] = {"disconnected_at": None}
_CHILD = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(3600)"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write("fake_upstream " + (format % args) + "\n")

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        provided = self.headers.get("X-EvoFlux-Gateway", "").encode()
        if _SECRET and not hmac.compare_digest(provided, _SECRET):
            self._json(403, {"detail": "Forbidden"})
            return False
        return True

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path == "/fake/headers":
            self._json(200, {k.lower(): v for k, v in self.headers.items()})
        elif self.path == "/fake/sse-status":
            self._json(200, dict(_STATE))
        elif self.path == "/fake/env":
            self._json(
                200, {k: v for k, v in os.environ.items() if k.startswith("EVOFLUX_")}
            )
        elif self.path == "/fake/counter":
            # A different answer on every request: shadow noise.
            _STATE["counter"] = _STATE.get("counter", 0) + 1
            self._json(200, {"n": _STATE["counter"]})
        elif self.path == "/fake/child":
            self._json(200, {"pid": _CHILD.pid})
        elif self.path == "/fake/sse":
            self._sse()
        else:
            self._json(404, {"detail": "Not Found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if self.path != "/fake/upload":
            self._json(404, {"detail": "Not Found"})
            return
        total = 0
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                size = int(self.rfile.readline().split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    break
                remaining = size
                while remaining:
                    got = len(self.rfile.read(min(remaining, 1 << 20)))
                    if not got:
                        raise ConnectionError("body ended early")
                    remaining -= got
                    total += got
                self.rfile.readline()
        else:
            remaining = int(self.headers.get("Content-Length", "0"))
            while remaining:
                got = len(self.rfile.read(min(remaining, 1 << 20)))
                if not got:
                    raise ConnectionError("body ended early")
                remaining -= got
                total += got
        self._json(200, {"bytes": total})

    def _sse(self) -> None:
        _STATE["disconnected_at"] = None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self._chunk(b"event: message\ndata: one\n\n")
            time.sleep(1.0)
            self._chunk(b"event: message\ndata: two\n\n")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                time.sleep(0.1)
                self._chunk(b"event: tick\ndata: t\n\n")
            self._chunk(b"")
        except OSError:
            _STATE["disconnected_at"] = time.time()
            self.close_connection = True


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["serve"]:
        args = args[1:]
    host, port = "127.0.0.1", 0
    for flag, value in zip(args, args[1:]):
        if flag == "--host":
            host = value
        elif flag == "--port":
            port = int(value)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    payload = {
        "port": server.server_address[1],
        "pid": os.getpid(),
        "version": "fake",
        "token": os.environ.get("EVOFLUX_DESKTOP_TOKEN", ""),
    }
    print("fake_upstream starting", flush=True)
    print("EVOFLUX_HANDSHAKE " + json.dumps(payload), flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    finally:
        _CHILD.kill()


if __name__ == "__main__":
    main()
