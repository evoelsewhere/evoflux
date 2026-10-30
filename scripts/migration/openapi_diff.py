#!/usr/bin/env python3
"""Compare the OpenAPI surface one migration lane owns against the pinned v3.1.1 spec.

    openapi_diff.py <lane> --candidate http://127.0.0.1:PORT/openapi.json [--token T]
    openapi_diff.py <lane> --candidate path/to/rust-openapi.json

The paths a lane owns are the ``routes`` cell of its row in
``server/MIGRATION_BOARD.md`` (read with ``check_board.parse_board``);
``--routes`` overrides that. Both specs are cut down to those
paths, component references are inlined (so generated component names cannot
matter) and auto-generated ``title`` keys are dropped. The result is checked with
``oasdiff breaking`` (when installed) and a strict structural diff.

Exit status: 0 identical, 1 any difference, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PINNED = REPO_ROOT / "contract-tests" / "openapi" / "python-v3.1.1.json"
DEFAULT_BOARD = REPO_ROOT / "server" / "MIGRATION_BOARD.md"
_REF_PREFIX = "#/components/"


def lane_routes(lane: str, board: Path) -> list[str]:
    """The ``routes`` cell of the lane's row in ``server/MIGRATION_BOARD.md``."""
    from check_board import parse_board

    rows = [
        r for r in parse_board(board.read_text(encoding="utf-8")) if r["lane"] == lane
    ]
    if len(rows) != 1:
        raise SystemExit(f"error: expected one row for lane {lane!r} in {board}")
    routes = [
        part.strip().strip("`")
        for part in rows[0]["routes"].split(",")
        if part.strip().strip("`") not in ("", "-")
    ]
    if not routes:
        raise SystemExit(f"error: lane {lane!r} owns no routes in {board}")
    return routes


def owns(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif pattern.endswith("/*"):
            prefix = pattern[:-2]
            rest = path[len(prefix) + 1 :]
            if path.startswith(prefix + "/") and rest and "/" not in rest:
                return True
        elif path == pattern:
            return True
    return False


def _resolve(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith(_REF_PREFIX):
        raise SystemExit(f"error: unsupported $ref {ref!r}")
    node: Any = spec.get("components", {})
    for part in ref[len(_REF_PREFIX) :].split("/"):
        node = node[part]
    return node


# Keys whose children are user-chosen names, not schema keywords: a property
# called "title" is contract, only the schema's own "title" is generated noise.
_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions"})


def _inline(
    spec: dict[str, Any],
    node: Any,
    stack: tuple[str, ...],
    names: bool = False,
) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and not names:
            if ref in stack:
                return {"$cycle": len(stack) - stack.index(ref)}
            return _inline(spec, _resolve(spec, ref), (*stack, ref))
        return {
            key: (
                value
                if not names and key in {"default", "example", "enum"}
                else _inline(spec, value, stack, key in _NAME_MAPS and not names)
            )
            for key, value in node.items()
            if names or key != "title"
        }
    if isinstance(node, list):
        return [_inline(spec, item, stack) for item in node]
    return node


def extract(spec: dict[str, Any], patterns: list[str]) -> dict[str, Any]:
    """The owned paths with all component references inlined."""
    paths = {p: v for p, v in spec.get("paths", {}).items() if owns(p, patterns)}
    return {"paths": _inline(spec, paths, ())}


def load_spec(source: str, token: str | None) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def diff(a: Any, b: Any, path: str = "$") -> list[str]:
    if type(a) is not type(b):
        return [f"{path}: {json.dumps(a)[:80]} != {json.dumps(b)[:80]}"]
    if isinstance(a, dict):
        out: list[str] = []
        for key in sorted(a.keys() | b.keys()):
            if key not in b:
                out.append(f"{path}.{key}: only in pinned")
            elif key not in a:
                out.append(f"{path}.{key}: only in candidate")
            else:
                out.extend(diff(a[key], b[key], f"{path}.{key}"))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: list length {len(a)} != {len(b)}"]
        return [
            d
            for i, (x, y) in enumerate(zip(a, b, strict=True))
            for d in diff(x, y, f"{path}[{i}]")
        ]
    return [] if a == b else [f"{path}: {json.dumps(a)[:80]} != {json.dumps(b)[:80]}"]


def oasdiff_breaking(pinned: dict[str, Any], candidate: dict[str, Any]) -> int:
    exe = shutil.which("oasdiff")
    if exe is None:
        print(
            "warning: oasdiff not installed; relying on the strict diff",
            file=sys.stderr,
        )
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, doc in (("pinned", pinned), ("candidate", candidate)):
            full = {"openapi": "3.1.0", "info": {"title": name, "version": "0"}, **doc}
            path = Path(tmp) / f"{name}.json"
            path.write_text(json.dumps(full), encoding="utf-8")
            files.append(str(path))
        result = subprocess.run(
            [exe, "breaking", *files, "--fail-on", "INFO"],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.stdout.strip():
        print(result.stdout.strip())
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("lane", help="lane name in server/MIGRATION_BOARD.md")
    parser.add_argument(
        "--candidate", required=True, help="Rust spec: file path or URL"
    )
    parser.add_argument("--token", help="bearer token when --candidate is a URL")
    parser.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument(
        "--routes", nargs="+", help="path patterns, instead of the board"
    )
    args = parser.parse_args(argv)

    try:
        patterns = args.routes or lane_routes(args.lane, args.board)
        pinned = extract(load_spec(str(args.pinned), None), patterns)
        candidate = extract(load_spec(args.candidate, args.token), patterns)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not pinned["paths"]:
        print(f"error: pinned spec has no paths for {patterns}", file=sys.stderr)
        return 2

    differences = diff(pinned, candidate)
    breaking = oasdiff_breaking(pinned, candidate)
    for line in differences:
        print(line)
    if differences or breaking:
        print(f"FAIL: {args.lane}: {len(differences)} difference(s)")
        return 1
    print(f"OK: {args.lane}: {len(pinned['paths'])} path(s) identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
