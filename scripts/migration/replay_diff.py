#!/usr/bin/env python3
"""Compare deterministic unit requests on isolated Python and Rust backends."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contract-tests"))
sys.path.insert(0, str(ROOT / "scripts" / "migration"))

from check_board import load_routing, owner_for  # noqa: E402
from normalize import normalize  # noqa: E402


def recorded_gets(directory: Path, unit: str) -> list[dict]:
    routing = load_routing(ROOT / "server/routing.toml")
    rows = []
    for file in sorted(directory.glob("*.jsonl")):
        file_rows = []
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            path = row.get("path", "")
            if (
                row.get("method") == "GET"
                and "<removed>" not in path
                and owner_for(routing, path.split("?", 1)[0]) == unit
            ):
                blocked = {
                    "host",
                    "authorization",
                    "proxy-authorization",
                    "cookie",
                    "content-length",
                    "connection",
                }
                row["headers"] = {
                    k: v
                    for k, v in row.get("request_headers", {}).items()
                    if k.lower() not in blocked and "<removed>" not in v
                }
                file_rows.append(row)
        rows.extend(sorted(file_rows, key=lambda row: row.get("seq", 0)))
    return rows


def response_body(response):
    try:
        return response.json()
    except ValueError:
        return response.text


def compare_requests(requests, left, right, known, output):
    count = 0
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for request in requests:
            method, path = request["method"], request["path"]
            kwargs = {
                key: request[key]
                for key in ("json", "content", "headers")
                if key in request
            }
            a, b = (
                left.request(method, path, **kwargs),
                right.request(method, path, **kwargs),
            )

            def response_value(response):
                value = {
                    "status": response.status_code,
                    "body": response_body(response),
                }
                if hasattr(response, "headers"):
                    value["media_type"] = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                return normalize(value)

            av = response_value(a)
            bv = response_value(b)
            if av != bv:
                explained = (
                    method,
                    path.split("?", 1)[0],
                    json.dumps(av, sort_keys=True),
                    json.dumps(bv, sort_keys=True),
                ) in known
                stream.write(
                    json.dumps(
                        {
                            "method": method,
                            "path": path,
                            "python": av,
                            "rust": bv,
                            "known": explained,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += not explained
    return int(count > 0)


def known_differences(path: Path, unit: str) -> set[tuple[str, str, str, str]]:
    """Approved table rows: unit | method | path | python JSON | rust JSON | reason."""
    approved = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] != unit or not cells[5]:
            continue
        try:
            approved.add(
                (
                    cells[1].upper(),
                    cells[2],
                    json.dumps(json.loads(cells[3]), sort_keys=True),
                    json.dumps(json.loads(cells[4]), sort_keys=True),
                )
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid approved difference: {line}") from exc
    return approved


def contract_lanes(unit: str) -> list[Path]:
    from check_board import parse_board

    rows = parse_board((ROOT / "server/MIGRATION_BOARD.md").read_text(encoding="utf-8"))
    return [
        ROOT / "contract-tests" / row["lane"]
        for row in rows
        if row["unit"] == unit and (ROOT / "contract-tests" / row["lane"]).is_dir()
    ]


def require_non_get_coverage(unit: str, requests: list[dict]) -> None:
    import re

    routing = load_routing(ROOT / "server/routing.toml")
    paths = json.loads(
        (ROOT / "contract-tests/openapi/python-v3.1.1.json").read_text(encoding="utf-8")
    )["paths"]
    missing = []
    for path, operations in paths.items():
        if owner_for(routing, path) != unit:
            continue
        pattern = re.sub(r"\\\{[^{}]+\\\}", r".+", re.escape(path))
        for method in (
            key.upper()
            for key in operations
            if key.lower()
            in {"post", "put", "patch", "delete", "head", "options", "trace"}
        ):
            if not any(
                row.get("method") == method
                and re.fullmatch(pattern, row.get("path", "").split("?", 1)[0])
                for row in requests
            ):
                missing.append(f"{method} {path}")
    if missing:
        raise ValueError("contract requests missing: " + ", ".join(missing))


def run_contracts(
    lanes: list[Path], target: str, transcript: Path, unit: str
) -> tuple[list[dict], int]:
    import os
    import subprocess

    env = os.environ.copy()
    env.update(
        TARGET=target,
        EVOFLUX_REPLAY_TRANSCRIPT=str(transcript),
        EVOFLUX_REPLAY_UNIT=unit,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *map(str, lanes), "-q", "--no-cov"],
        cwd=ROOT,
        env=env,
        check=False,
    )
    if not transcript.exists():
        raise RuntimeError(
            f"{target} contract tests captured no requests (exit {result.returncode})"
        )
    return (
        [
            json.loads(line)
            for line in transcript.read_text(encoding="utf-8").splitlines()
        ],
        result.returncode,
    )


def compare_transcripts(
    left: list[dict], right: list[dict], unit: str, known: set, stream
) -> tuple[int, int, int]:
    from itertools import zip_longest

    routing = load_routing(ROOT / "server/routing.toml")

    def selected(rows):
        return [
            row
            for row in rows
            if owner_for(routing, row["path"].split("?", 1)[0]) == unit
        ]

    left, right = selected(left), selected(right)
    compared = equal = differences = 0
    for a, b in zip_longest(left, right):
        compared += 1
        if a is None or b is None:
            stream.write(json.dumps({"python": a, "rust": b, "known": False}) + "\n")
            differences += 1
            continue
        request_a = normalize(
            {
                k: a[k]
                for k in ("test", "method", "path", "request_headers", "request_body")
            }
        )
        request_b = normalize(
            {
                k: b[k]
                for k in ("test", "method", "path", "request_headers", "request_body")
            }
        )
        response_a = normalize(
            {
                "status": a["status"],
                "media_type": a.get("media_type", ""),
                "body": a["body"],
            }
        )
        response_b = normalize(
            {
                "status": b["status"],
                "media_type": b.get("media_type", ""),
                "body": b["body"],
            }
        )
        if request_a == request_b and response_a == response_b:
            equal += 1
            continue
        key = (
            a["method"],
            a["path"].split("?", 1)[0],
            json.dumps(response_a, sort_keys=True),
            json.dumps(response_b, sort_keys=True),
        )
        explained = request_a == request_b and key in known
        stream.write(
            json.dumps(
                {
                    "request_python": request_a,
                    "request_rust": request_b,
                    "python": response_a,
                    "rust": response_b,
                    "known": explained,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        differences += not explained
    return compared, equal, differences


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile
    import httpx
    from backends import start_backend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit")
    parser.add_argument("--recordings", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--noise", action="store_true")
    args = parser.parse_args(argv)
    routing = load_routing(ROOT / "server/routing.toml")
    if args.unit not in {entry.name for entry in routing}:
        parser.error(f"unknown unit {args.unit!r}")
    if args.recordings and not args.recordings.is_dir():
        parser.error("recordings directory does not exist")
    args.out.mkdir(parents=True, exist_ok=True)
    known = (
        set()
        if args.noise
        else known_differences(ROOT / "server/KNOWN_DIFFERENCES.md", args.unit)
    )
    lanes = contract_lanes(args.unit)
    gets = recorded_gets(args.recordings, args.unit) if args.recordings else []
    if not lanes and not gets:
        parser.error("no contract request sets or recorded GET requests for unit")
    target = "python" if args.noise else "rust"
    with tempfile.TemporaryDirectory(prefix="evoflux-replay-") as temp:
        temp = Path(temp)
        left, left_code = (
            run_contracts(lanes, "python", temp / "python.jsonl", args.unit)
            if lanes
            else ([], 0)
        )
        right, right_code = (
            run_contracts(lanes, target, temp / "other.jsonl", args.unit)
            if lanes
            else ([], 0)
        )
        require_non_get_coverage(args.unit, left)
        require_non_get_coverage(args.unit, right)
        output = args.out / f"{args.unit}-replay.jsonl"
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            compared, equal, diff = compare_transcripts(
                left, right, args.unit, known, stream
            )
        if gets:
            fixture = ROOT / "contract-tests/fixtures/upgrade/v3.0.0"
            first = start_backend(
                "python",
                temp / "left",
                fixture / "evoflux.db",
                config_fixture=fixture / "config",
            )
            try:
                second = start_backend(
                    target,
                    temp / "right",
                    fixture / "evoflux.db",
                    config_fixture=fixture / "config",
                    extra_env={"EVOFLUX_ROUTE_OVERRIDE": f"{args.unit}=rust"}
                    if target == "rust"
                    else None,
                )
                try:
                    with (
                        httpx.Client(
                            base_url=first.base_url,
                            headers={"Authorization": f"Bearer {first.token}"},
                            timeout=30,
                        ) as a,
                        httpx.Client(
                            base_url=second.base_url,
                            headers={"Authorization": f"Bearer {second.token}"},
                            timeout=30,
                        ) as b,
                    ):
                        other = temp / "get-diffs.jsonl"
                        compare_requests(gets, a, b, known, other)
                        rows = other.read_text(encoding="utf-8").splitlines()
                        with output.open("a", encoding="utf-8") as stream:
                            for row in rows:
                                stream.write(row + "\n")
                        compared += len(gets)
                        equal += len(gets) - len(rows)
                        diff += sum(not json.loads(row)["known"] for row in rows)
                finally:
                    second.stop()
            finally:
                first.stop()
        diff_count = len(output.read_text(encoding="utf-8").splitlines())
        print(f"compared={compared} equal={equal} diff={diff_count}")
        if not compared:
            raise RuntimeError("no requests from the selected unit were compared")
        return int(diff != 0 or left_code != 0 or right_code != 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"replay-diff: {exc}", file=sys.stderr)
        sys.exit(2)
