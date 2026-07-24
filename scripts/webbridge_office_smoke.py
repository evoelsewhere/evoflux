#!/usr/bin/env python3
"""Authenticated WebBridge productivity-app smoke runner.

The runner talks only to a local/keyed EvoFlux agent WebSocket and never accepts
browser cookies, passwords, or OAuth tokens. Prepare a dedicated Chrome profile,
pair the extension, bind the target session/tab, then run one explicit case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import websockets


@dataclass(frozen=True)
class SmokeCase:
    name: str
    snapshot_kinds: list[str]
    read_target: dict[str, Any]
    write_target: dict[str, Any]
    change: dict[str, Any]


CASES: dict[str, SmokeCase] = {
    "google-docs": SmokeCase(
        name="Google Docs current selection replace",
        snapshot_kinds=["text", "control"],
        read_target={"kind": "active_text", "scope": "selection"},
        write_target={"kind": "active_text", "scope": "selection"},
        change={"kind": "text", "mode": "replace", "at": "caret", "text": "EvoFlux semantic smoke"},
    ),
    "google-sheets": SmokeCase(
        name="Google Sheets range matrix",
        snapshot_kinds=["grid", "control"],
        read_target={"kind": "range", "sheet": None, "address": "B2:C2"},
        write_target={"kind": "range", "sheet": None, "address": "B2:C2"},
        change={
            "kind": "matrix",
            "rows": [[
                {"kind": "value", "value": "EvoFlux"},
                {"kind": "formula", "formula": "=LEN(B2)"},
            ]],
        },
    ),
    "excel-online": SmokeCase(
        name="Excel Online range matrix",
        snapshot_kinds=["grid", "control"],
        read_target={"kind": "range", "sheet": None, "address": "B2:C2"},
        write_target={"kind": "range", "sheet": None, "address": "B2:C2"},
        change={
            "kind": "matrix",
            "rows": [[
                {"kind": "value", "value": "EvoFlux"},
                {"kind": "formula", "formula": "=LEN(B2)"},
            ]],
        },
    ),
    "powerpoint-online": SmokeCase(
        name="PowerPoint Online title replace",
        snapshot_kinds=["slide", "text", "control"],
        read_target={"kind": "slide_object", "slide_index": 2, "role": "title", "ordinal": 0},
        write_target={"kind": "slide_object", "slide_index": 2, "role": "title", "ordinal": 0},
        change={"kind": "text", "mode": "replace", "at": "caret", "text": "EvoFlux semantic smoke"},
    ),
}


async def exchange(ws: Any, action: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {"action": action, **params}
    await ws.send(json.dumps(payload))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("type") in {"response", "no_extension"}:
            return raw


async def run(args: argparse.Namespace) -> int:
    case = CASES[args.case]
    token = os.environ.get("EVOFLUX_DESKTOP_TOKEN") or os.environ.get("EVOFLUX_ACCESS_KEY")
    url = f"{args.base.rstrip('/')}/api/team/webbridge/agent/{args.session_id}"
    if token:
        from urllib.parse import quote

        url += f"?_token={quote(token, safe='')}"
    print(f"Case: {case.name}")
    print("Prerequisite: focus the intended editor/range/object in the paired browser tab.")
    async with websockets.connect(url, max_size=1_000_000) as ws:
        snapshot = await exchange(
            ws,
            "semantic_snapshot",
            {"kinds": case.snapshot_kinds, "max_items": 80, "include_values": False},
        )
        print(json.dumps({"snapshot": snapshot}, indent=2))
        if not snapshot.get("success"):
            return 2
        read_before = await exchange(ws, "semantic_read", {"target": case.read_target})
        print(json.dumps({"read_before": read_before}, indent=2))
        if args.read_only:
            return 0 if read_before.get("success") else 2
        response = input("Run the bounded write shown above? [y/N] ").strip().lower()
        if response != "y":
            return 0
        write = await exchange(
            ws,
            "semantic_write",
            {"target": case.write_target, "change": case.change, "verify": "normalized"},
        )
        print(json.dumps({"write": write}, indent=2))
        read_after = await exchange(ws, "semantic_read", {"target": case.read_target})
        print(json.dumps({"read_after": read_after}, indent=2))
        status = (write.get("data") or {}).get("status")
        return 0 if write.get("success") and status == "ok" else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run an opt-in authenticated semantic smoke against a paired productivity web app."
    )
    result.add_argument("case", choices=sorted(CASES))
    result.add_argument("session_id", help="Existing WebBridge-enabled session bound to the editor tab")
    result.add_argument("--base", default="ws://127.0.0.1:8000", help="EvoFlux WebSocket base URL")
    result.add_argument("--read-only", action="store_true", help="Probe snapshot/read only; never ask to write")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parser().parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
