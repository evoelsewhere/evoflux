"""Python side of the tool parity harness.

Reads ``{"workspace": str, "session_id": str, "cases": [{"tool": str, "args": {}}]}``
on stdin, runs each case through the real ``Tool.arun`` the way the agent loop
does, and prints ``[{"content": str, "is_error": bool}]`` (or the specs with
``--specs``) as JSON.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.sandbox_config import DEFAULT_DENIED_PATTERNS
from app.agent.tools.builtin.date import get_date
from app.agent.tools.builtin.filesystem.glob import glob_files
from app.agent.tools.builtin.filesystem.grep import grep_files
from app.agent.tools.builtin.filesystem.ls import list_directory
from app.agent.tools.builtin.filesystem.read import read_file

TOOLS = {
    t.name: t for t in (read_file, list_directory, glob_files, grep_files, get_date)
}


async def run_case(case: dict) -> dict:
    # Mirrors agent_loop.tool_executor: any exception becomes "Error: <msg>".
    try:
        tool = TOOLS[case["tool"]]
        result = await tool.arun(**case["args"])
        return {"content": str(result), "is_error": False}
    except Exception as exc:  # noqa: BLE001
        return {"content": f"Error: {exc}", "is_error": True}


async def main() -> None:
    if "--specs" in sys.argv:
        print(json.dumps({n: t.definition for n, t in TOOLS.items()}))
        return
    request = json.load(sys.stdin)
    set_sandbox(
        SandboxConfig(
            workspace=request["workspace"],
            denied_roots=[],
            denied_patterns=list(DEFAULT_DENIED_PATTERNS),
        )
    )
    out = [await run_case(c) for c in request["cases"]]
    sys.stdout.buffer.write(json.dumps(out).encode("utf-8"))


asyncio.run(main())
