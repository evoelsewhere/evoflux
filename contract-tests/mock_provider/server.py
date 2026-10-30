"""Replaying model provider for deterministic agent-loop contract tests.

Speaks the OpenAI Chat Completions and Anthropic Messages streaming wire
formats. A recording is a JSONL file; each line is one of:

* ``{"response": n}``: starts the n-th response. The k-th request to the
  provider gets response k (the last one repeats). A file without a marker is
  one response.
* ``{"delay_ms": n}``: sleep before the next line.
* ``{"event": "name", "data": {...}}``: one SSE event (``event:`` line is
  omitted when ``event`` is absent, as OpenAI does). ``data`` may be a string
  such as ``"[DONE]"``.
* ``{"status": 429, "headers": {...}, "body": {...}}``: a plain JSON error
  response instead of a stream.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RECORDINGS = Path(__file__).parent / "recordings"

OPENAI_PATH = "/v1/chat/completions"
ANTHROPIC_PATH = "/v1/messages"
MODELS_PATH = "/v1/models"


_OPENAI_SIDE_REPLY = {
    "id": "chatcmpl-mock-side",
    "object": "chat.completion",
    "created": 1,
    "model": "mock-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Mock title"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
}
_ANTHROPIC_SIDE_REPLY = {
    "id": "msg_mock_side",
    "type": "message",
    "role": "assistant",
    "model": "mock-model",
    "content": [{"type": "text", "text": "Mock title"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 2},
}


class MockProvider:
    """A provider on ``127.0.0.1`` with an OS-assigned port."""

    def __init__(self, model_ids: tuple[str, ...] = ("mock-model",)) -> None:
        self._lock = threading.Lock()
        self._responses: list[list[dict[str, Any]]] = []
        self._served = 0
        self._model_ids = model_ids
        #: Streamed (agent-turn) requests, in arrival order.
        self.requests: list[dict[str, Any]] = []
        #: Non-streamed requests (title generation and the like). They get a
        #: fixed reply and never consume the recording.
        self.side_requests: list[dict[str, Any]] = []
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="mock-provider", daemon=True
        )
        self._thread.start()

    def load(self, recording: str) -> None:
        """Replace the current script with ``recordings/<recording>.jsonl``."""
        lines = (RECORDINGS / f"{recording}.jsonl").read_text(encoding="utf-8")
        responses: list[list[dict[str, Any]]] = []
        for raw in lines.splitlines():
            if not raw.strip():
                continue
            entry = json.loads(raw)
            if "response" in entry or not responses:
                responses.append([])
                if "response" in entry:
                    continue
            responses[-1].append(entry)
        with self._lock:
            self._responses = responses
            self._served = 0
            self.requests.clear()
            self.side_requests.clear()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # -- used by the handler ------------------------------------------------

    def _next_response(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            self.requests.append(request)
            if not self._responses:
                return [{"status": 500, "body": {"error": "no recording loaded"}}]
            index = min(self._served, len(self._responses) - 1)
            self._served += 1
            return self._responses[index]

    def _side_request(self, request: dict[str, Any]) -> None:
        with self._lock:
            self.side_requests.append(request)

    def _models_body(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "created": 0, "owned_by": "mock"}
                for m in self._model_ids
            ],
        }


def _make_handler(provider: MockProvider) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _json(self, status: int, body: Any, headers: dict[str, str] | None = None):
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0].rstrip("/") in (MODELS_PATH, "/models"):
                self._json(200, provider._models_body())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            path = self.path.split("?")[0]
            if not path.endswith(("/chat/completions", "/messages")):
                self._json(404, {"error": "not found"})
                return
            if not payload.get("stream"):
                provider._side_request(payload)
                if path.endswith("/messages"):
                    self._json(200, _ANTHROPIC_SIDE_REPLY)
                else:
                    self._json(200, _OPENAI_SIDE_REPLY)
                return
            entries = provider._next_response(payload)
            if entries and "status" in entries[0]:
                self._json(
                    int(entries[0]["status"]),
                    entries[0].get("body", {}),
                    entries[0].get("headers"),
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for entry in entries:
                    if "delay_ms" in entry:
                        time.sleep(entry["delay_ms"] / 1000)
                        continue
                    data = entry["data"]
                    if not isinstance(data, str):
                        data = json.dumps(data, separators=(",", ":"))
                    frame = ""
                    if "event" in entry:
                        frame += f"event: {entry['event']}\n"
                    frame += f"data: {data}\n\n"
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler
