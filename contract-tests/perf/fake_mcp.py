"""Stdlib-only stdio MCP server used by the responsiveness scenarios.

``slow``  completes the handshake, advertises one tool ``work`` and sleeps
          ``arguments.seconds`` (default 8) inside ``tools/call``.
``hang``  reads requests and never answers, like a wedged server.
"""

from __future__ import annotations

import json
import sys
import time


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main(mode: str) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        if mode == "hang" or request_id is None:
            continue
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": request["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "perf-fake", "version": "0"},
                    },
                }
            )
        elif method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "work",
                                "description": "Sleeps for arguments.seconds.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"seconds": {"type": "number"}},
                                },
                            }
                        ]
                    },
                }
            )
        elif method == "tools/call":
            seconds = float(request["params"].get("arguments", {}).get("seconds", 8))
            time.sleep(seconds)
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "done"}]},
                }
            )
        else:
            _send({"jsonrpc": "2.0", "id": request_id, "result": {}})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "slow")
