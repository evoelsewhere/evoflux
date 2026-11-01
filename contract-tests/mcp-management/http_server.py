"""A tiny local MCP Streamable HTTP server for the contract tests (stdlib only).

It answers ``initialize``, ``tools/list`` and ``tools/call`` with plain JSON
bodies and records the headers of every request, so a test can see which
headers Python sent. ``require_token`` makes it answer ``401`` unless the
``Authorization`` header equals ``Bearer <token>``. ``well_known`` is served as
the body of ``GET /.well-known/oauth-authorization-server`` (404 when ``None``).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeHttpMcp:
    def __init__(
        self,
        tools: list[str] | None = None,
        require_token: str | None = None,
        well_known: dict[str, Any] | None = None,
    ):
        self.tools = tools or ["ping"]
        self.require_token = require_token
        self.well_known = well_known
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                owner.requests.append(
                    {"method": "GET", "path": self.path, "headers": dict(self.headers)}
                )
                if self.path == "/.well-known/oauth-authorization-server":
                    if owner.well_known is None:
                        self._send(404)
                    else:
                        self._send(
                            200,
                            json.dumps(owner.well_known).encode(),
                            {"Content-Type": "application/json"},
                        )
                    return
                self._send(405)

            def do_DELETE(self) -> None:
                owner.requests.append({"method": "DELETE", "path": self.path, "headers": dict(self.headers)})
                self._send(200)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                message = json.loads(raw or b"{}")
                owner.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "headers": dict(self.headers),
                        "rpc": message.get("method"),
                    }
                )
                if owner.require_token is not None and (
                    self.headers.get("Authorization") != f"Bearer {owner.require_token}"
                ):
                    self._send(401, b'{"error":"unauthorized"}', {"Content-Type": "application/json"})
                    return
                ident = message.get("id")
                if ident is None:
                    self._send(202)
                    return
                method = message.get("method")
                if method == "initialize":
                    result: dict[str, Any] = {
                        "protocolVersion": message["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-http", "version": "1.0"},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": name,
                                "description": name,
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                            for name in owner.tools
                        ]
                    }
                elif method == "tools/call":
                    params = message["params"]
                    result = {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {"tool": params["name"], "arguments": params.get("arguments")},
                                    sort_keys=True,
                                ),
                            }
                        ]
                    }
                else:
                    result = {}
                body = json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}).encode()
                self._send(
                    200,
                    body,
                    {"Content-Type": "application/json", "Mcp-Session-Id": "fixture-session"},
                )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/mcp"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
