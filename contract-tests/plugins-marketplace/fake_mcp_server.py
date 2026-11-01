"""A tiny stdio MCP server for the plugin contract tests (stdlib only).

Speaks newline-delimited JSON-RPC: ``initialize``, ``tools/list``, ``tools/call``
and ``ping``. At start-up it writes ``{"argv", "cwd", "env"}`` to the file named
by ``FAKE_MCP_RECORD`` (or ``$PLUGIN_DATA/started.json``) so a test can see
exactly what the host passed to the process.
"""

import json
import os
import sys


def record() -> None:
    target = os.environ.get("FAKE_MCP_RECORD")
    if not target:
        data = os.environ.get("PLUGIN_DATA")
        if not data:
            return
        target = os.path.join(data, "started.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(
            {"pid": os.getpid(), "argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)},
            handle,
        )


def reply(message_id, result) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}) + "\n"
    )
    sys.stdout.flush()


def main() -> None:
    record()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        message_id = message.get("id")
        if message_id is None:
            continue
        if method == "initialize":
            reply(
                message_id,
                {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "0"},
                },
            )
        elif method == "tools/list":
            reply(
                message_id,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo the text.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            text = message["params"].get("arguments", {}).get("text", "")
            reply(message_id, {"content": [{"type": "text", "text": text}]})
        else:
            reply(message_id, {})


if __name__ == "__main__":
    main()
