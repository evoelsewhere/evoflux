#!/usr/bin/env python3
"""Replay recorded GET traffic of one unit through a running gateway and
print the shadow diff summary.

Usage: shadow_replay.py UNIT --recordings DIR --state-dir DIR --base-url URL [--token T]

Start the gateway first with the unit in shadow mode, for example
``EVOFLUX_ROUTE_OVERRIDE=<unit>=shadow EVOFLUX_GATEWAY_STATE_DIR=<state-dir>``
(``make shadow`` passes the same values). Every recorded ``GET`` whose path
belongs to UNIT in ``server/routing.toml`` is sent to the gateway; Python
answers and the gateway appends differences to ``<state-dir>/shadow/UNIT.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_board import load_routing, owner_for  # noqa: E402

ROUTING = Path(__file__).resolve().parents[2] / "server" / "routing.toml"
REMOVED = "<removed>"


def recorded_gets(directory: Path, unit: str) -> list[str]:
    units = load_routing(ROUTING)
    paths: list[str] = []
    for file in sorted(directory.glob("*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            path = row.get("path", "")
            if row.get("method") != "GET" or REMOVED in path:
                continue
            if owner_for(units, path.split("?", 1)[0]) == unit and path not in paths:
                paths.append(path)
    return paths


def replay(base_url: str, token: str, paths: list[str]) -> Counter[int]:
    statuses: Counter[int] = Counter()
    for path in paths:
        request = urllib.request.Request(base_url.rstrip("/") + path)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
                statuses[response.status] += 1
        except urllib.error.HTTPError as error:
            statuses[error.code] += 1
        except OSError:
            statuses[0] += 1
    return statuses


def summarize(state_dir: Path, unit: str, requests: int) -> int:
    diffs = state_dir / "shadow" / f"{unit}.jsonl"
    rows = []
    if diffs.is_file():
        rows = [
            json.loads(x) for x in diffs.read_text(encoding="utf-8").splitlines() if x
        ]
    kinds = Counter(row.get("kind") for row in rows)
    print(f"unit {unit}: replayed {requests} GET requests, {len(rows)} diff entries")
    for kind, count in sorted(kinds.items(), key=lambda item: str(item[0])):
        print(f"  {kind}: {count}")
    by_path = Counter(row.get("path", "").split("?", 1)[0] for row in rows)
    for path, count in by_path.most_common(10):
        print(f"  {count:4d}  {path}")
    return sum(count for kind, count in kinds.items() if kind != "noise")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("unit")
    parser.add_argument("--recordings", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)
    paths = recorded_gets(args.recordings, args.unit)
    if not paths:
        print(f"no recorded GET requests for unit {args.unit}", file=sys.stderr)
        return 2
    replay(args.base_url, args.token, paths)
    time.sleep(2)  # diffs are written after the client has its answer
    return 1 if summarize(args.state_dir, args.unit, len(paths)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
