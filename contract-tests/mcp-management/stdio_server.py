"""A tiny MCP stdio server for the contract tests (stdlib only).

``stdio_server.py [--dump FILE] [--tool NAME ...] [--fail-start]``

It speaks newline-delimited JSON-RPC: ``initialize``, ``tools/list`` and
``tools/call``. With ``--dump`` it writes its argv, working directory and
environment to FILE as JSON at start-up, so a test can see exactly what Python
launched. It also puts its pid there, so a test can see that Python
stopped the process. The ``echo`` tool returns its arguments as text.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    args = sys.argv[1:]
    dump = None
    tools = []
    fail = False
    index = 0
    while index < len(args):
        if args[index] == "--dump":
            dump = args[index + 1]
            index += 2
        elif args[index] == "--tool":
            tools.append(args[index + 1])
            index += 2
        elif args[index] == "--fail-start":
            fail = True
            index += 1
        else:
            index += 1
    if dump:
        with open(dump, "w", encoding="utf-8") as handle:
            json.dump(
                {"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ), "pid": os.getpid()},
                handle,
            )
    if fail:
        sys.stderr.write("boom on start\n")
        sys.exit(3)
    tools = tools or ["echo"]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        ident = message.get("id")
        if ident is None:
            continue
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": f"{name} tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                    for name in tools
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
        elif method == "ping":
            result = {}
        else:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": ident,
                        "error": {"code": -32601, "message": "no such method"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
