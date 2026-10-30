#!/usr/bin/env python3
"""Validate the Rust migration board, cutover units and routing table.

Checks (see ``server/AGENTS.md`` and design §3.1, §5):

* ``server/MIGRATION_BOARD.md`` parses with the exact column format, every row
  is valid, and no two rows own overlapping paths.
* Every route FastAPI registers resolves to exactly one cutover unit in
  ``server/routing.toml`` (longest prefix wins) and to a lane of that unit.
* Every lifespan service the gateway can disable is in exactly one unit.
* ``server/CUTOVER_UNITS.md`` lists the same routes and services per unit.

Usage::

    uv run python scripts/migration/check_board.py            # all checks
    uv run python scripts/migration/check_board.py --status   # lane counts
    uv run python scripts/migration/check_board.py --skip-app-routes
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
BOARD = SERVER / "MIGRATION_BOARD.md"
ROUTING = SERVER / "routing.toml"
CUTOVER_UNITS = SERVER / "CUTOVER_UNITS.md"

COLUMNS = (
    "lane",
    "unit",
    "python_sources",
    "routes",
    "owned_paths",
    "status",
    "claimed_by",
    "updated",
    "gate_report",
)
STATUSES = ("open", "claimed", "in-review", "merged", "cut-over")
OWNERS = ("python", "rust", "shadow")
CATCH_ALL = "/**"  # the packaged web UI mount
NO_UNIT = "none"  # lanes with no HTTP routes (CLI, plugin host, skill scripts)
EMPTY = "-"

# Names accepted by EVOFLUX_DISABLE_SERVICES (Phase 0 plan, Task 6).
GATEWAY_SERVICES = (
    "otel_retention",
    "model_registry_refresh",
    "mcp",
    "plugin_mcp",
    "conductor",
    "agents_validation",
    "scheduler",
    "dream_scheduler",
    "memory_backfill",
    "standalone_coding_purge",
    "webbridge_cleanup",
    "webbridge_artifact_cleanup",
)

_LANE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class BoardError(ValueError):
    """The board or routing file cannot be parsed."""


@dataclass(frozen=True)
class Unit:
    name: str
    owner: str
    routes: tuple[str, ...]
    services: tuple[str, ...]


# --- parsing -----------------------------------------------------------------


def _cells(line: str) -> list[str]:
    return [
        cell.strip().replace("`", "") for cell in line.strip().strip("|").split("|")
    ]


def _table_rows(text: str) -> list[list[str]]:
    rows = [_cells(line) for line in text.splitlines() if line.lstrip().startswith("|")]
    return [r for r in rows if not all(set(c) <= {"-", ":", " "} for c in r)]


def parse_board(text: str) -> list[dict[str, str]]:
    rows = _table_rows(text)
    if not rows or tuple(rows[0]) != COLUMNS:
        raise BoardError(f"board columns must be exactly: {' | '.join(COLUMNS)}")
    parsed = []
    for cells in rows[1:]:
        if len(cells) != len(COLUMNS):
            raise BoardError(f"board row has {len(cells)} cells: {cells}")
        parsed.append(dict(zip(COLUMNS, cells, strict=True)))
    return parsed


def load_routing(path: Path) -> list[Unit]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    units = []
    for entry in data.get("unit", []):
        units.append(
            Unit(
                name=entry["name"],
                owner=entry["owner"],
                routes=tuple(entry.get("routes", ())),
                services=tuple(entry.get("services", ())),
            )
        )
    names = [u.name for u in units]
    if len(set(names)) != len(names):
        raise BoardError("routing.toml has a duplicate unit name")
    bad = [u.name for u in units if u.owner not in OWNERS]
    if bad:
        raise BoardError(f"routing.toml units with an invalid owner: {bad}")
    return units


def registered_route_paths(app: Any) -> list[str]:
    # A Mount at "/" (the packaged web UI) reports an empty path.
    return sorted({route.path or "/" for route in app.routes})


# --- route matching ----------------------------------------------------------


def _specificity(pattern: str, path: str) -> int | None:
    """Length of the match when ``pattern`` covers ``path``, else None."""
    if pattern.endswith("/**"):
        base = pattern[:-3]
        if path == base or path.startswith(base + "/"):
            return len(base)
        return None
    return len(pattern) + 1 if path == pattern else None


def _best_match(patterns: list[tuple[str, str]], path: str) -> tuple[str, str] | None:
    best: tuple[int, str, str] | None = None
    for pattern, tag in patterns:
        score = _specificity(pattern, path)
        if score is not None and (best is None or score > best[0]):
            best = (score, tag, pattern)
    return (best[1], best[2]) if best else None


def _best(patterns: list[tuple[str, str]], path: str) -> str | None:
    match = _best_match(patterns, path)
    return match[0] if match else None


def _only_catch_all(match: tuple[str, str] | None, path: str) -> bool:
    """True when an API path is covered only by the ``/**`` web UI catch-all.

    The catch-all serves the packaged web UI; it must never hide an /api route
    that nobody assigned.
    """
    return match is not None and match[1] == CATCH_ALL and path.startswith("/api")


def owner_for(units: list[Unit], path: str) -> str | None:
    """Unit that owns ``path``: the longest matching route pattern wins."""
    return _best([(r, u.name) for u in units for r in u.routes], path)


def _pattern_base(pattern: str) -> str:
    return pattern[:-3] if pattern.endswith("/**") else pattern


# --- checks ------------------------------------------------------------------


def check_routes_assigned(units: list[Unit], paths: list[str]) -> list[str]:
    errors = []
    seen: dict[str, list[str]] = {}
    for u in units:
        for route in u.routes:
            seen.setdefault(route, []).append(u.name)
    for route, names in sorted(seen.items()):
        if len(set(names)) > 1:
            errors.append(f"route {route} is in more than one unit: {sorted(names)}")
    unit_patterns = [(r, u.name) for u in units for r in u.routes]
    for path in paths:
        match = _best_match(unit_patterns, path)
        if match is None or _only_catch_all(match, path):
            errors.append(f"route {path} has no unit in routing.toml")
    return errors


def check_services(units: list[Unit]) -> list[str]:
    errors = []
    seen: dict[str, list[str]] = {}
    for u in units:
        for service in u.services:
            seen.setdefault(service, []).append(u.name)
    for service in GATEWAY_SERVICES:
        owners = seen.get(service, [])
        if not owners:
            errors.append(f"service {service} has no unit")
        elif len(owners) > 1:
            errors.append(f"service {service} is in more than one unit: {owners}")
    for service in sorted(set(seen) - set(GATEWAY_SERVICES)):
        errors.append(f"unknown service {service} (not in the gateway service list)")
    return errors


def check_rows(rows: list[dict[str, str]], units: list[Unit]) -> list[str]:
    errors = []
    unit_names = {u.name for u in units}
    seen_lanes: set[str] = set()
    route_claims: dict[str, str] = {}
    for r in rows:
        lane = r["lane"]
        if not _LANE_RE.match(lane):
            errors.append(f"{lane}: lane must be a lowercase slug")
        if lane in seen_lanes:
            errors.append(f"{lane}: duplicate lane")
        seen_lanes.add(lane)

        status = r["status"]
        base = status.split(":", 1)[0]
        if status.startswith("blocked:"):
            if not status[len("blocked:") :].strip():
                errors.append(f"{lane}: blocked status needs a reason")
        elif status not in STATUSES:
            errors.append(
                f"{lane}: status {status!r} is not one of "
                f"{', '.join(STATUSES)} or blocked:<reason>"
            )
        if base in ("claimed", "in-review") and r["claimed_by"] == EMPTY:
            errors.append(f"{lane}: claimed_by is required while {status}")
        try:
            date.fromisoformat(r["updated"])
        except ValueError:
            errors.append(f"{lane}: updated must be an ISO date, got {r['updated']!r}")

        unit = r["unit"]
        if unit != NO_UNIT and unit not in unit_names:
            errors.append(f"{lane}: unit {unit!r} is not in routing.toml")

        owned = [g.strip() for g in r["owned_paths"].split(",") if g.strip()]
        if not owned:
            errors.append(f"{lane}: owned_paths is empty")
        for glob in owned:
            if glob.startswith("/") or ".." in glob.split("/") or " " in glob:
                errors.append(f"{lane}: invalid owned path {glob!r}")

        routes = (
            [] if r["routes"] == EMPTY else [x.strip() for x in r["routes"].split(",")]
        )
        if unit == NO_UNIT and routes:
            errors.append(f"{lane}: a lane in unit none cannot own routes")
        for route in routes:
            if route in route_claims and route_claims[route] != lane:
                errors.append(
                    f"{lane}: route {route} is also claimed by lane "
                    f"{route_claims[route]}"
                )
            route_claims.setdefault(route, lane)
            if not route.startswith("/"):
                errors.append(f"{lane}: route {route!r} must start with /")
            elif unit in unit_names and owner_for(units, _pattern_base(route)) != unit:
                errors.append(
                    f"{lane}: route {route} belongs to unit "
                    f"{owner_for(units, _pattern_base(route))}, not {unit}"
                )
    return errors


def globs_overlap(a: str, b: str) -> bool:
    sa, sb = a.split("/"), b.split("/")
    for x, y in zip(sa, sb):
        if x == "**" or y == "**":
            return True
        if not (fnmatch.fnmatchcase(x, y) or fnmatch.fnmatchcase(y, x)):
            return False
    return len(sa) == len(sb)


def check_overlaps(rows: list[dict[str, str]]) -> list[str]:
    errors = []
    owned = [
        (r["lane"], [g.strip() for g in r["owned_paths"].split(",") if g.strip()])
        for r in rows
    ]
    for i, (lane_a, globs_a) in enumerate(owned):
        for lane_b, globs_b in owned[i + 1 :]:
            if lane_a == lane_b:
                continue
            for ga in globs_a:
                for gb in globs_b:
                    if globs_overlap(ga, gb):
                        errors.append(
                            f"lanes {lane_a} and {lane_b} both own paths: "
                            f"{ga} overlaps {gb}"
                        )
    return errors


def check_lane_coverage(
    rows: list[dict[str, str]], units: list[Unit], paths: list[str]
) -> list[str]:
    patterns: list[tuple[str, str]] = []
    lane_unit = {r["lane"]: r["unit"] for r in rows}
    for r in rows:
        if r["routes"] != EMPTY:
            patterns += [(x.strip(), r["lane"]) for x in r["routes"].split(",")]
    errors = []
    for path in paths:
        match = _best_match(patterns, path)
        lane = match[0] if match else None
        if lane is None or _only_catch_all(match, path):
            errors.append(f"route {path} is not owned by any lane")
            continue
        unit = owner_for(units, path)
        if lane_unit[lane] != unit:
            errors.append(
                f"route {path} is owned by lane {lane} (unit {lane_unit[lane]}) "
                f"but routing.toml puts it in unit {unit}"
            )
    return errors


def _document_section(text: str, heading: str) -> dict[str, tuple[str, str]]:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^#{{2,3}} |\Z)", text, re.S | re.M
    )
    if not match:
        return {}
    section: dict[str, tuple[str, str]] = {}
    for cells in _table_rows(match.group(1))[1:]:
        if len(cells) >= 3:
            section[cells[0]] = (cells[1], cells[2])
    return section


def check_cutover_document(units: list[Unit], text: str) -> list[str]:
    errors = []
    for heading, kind, expected in (
        (
            "Route prefixes",
            "route",
            {r: u.name for u in units for r in u.routes},
        ),
        (
            "Lifespan services",
            "service",
            {s: u.name for u in units for s in u.services},
        ),
    ):
        documented = _document_section(text, heading)
        for key, unit in expected.items():
            if key not in documented:
                errors.append(f"CUTOVER_UNITS.md is missing {kind} {key}")
            elif documented[key][0] != unit:
                errors.append(
                    f"CUTOVER_UNITS.md puts {kind} {key} in {documented[key][0]}, "
                    f"routing.toml in {unit}"
                )
            elif not documented[key][1]:
                errors.append(f"CUTOVER_UNITS.md {kind} {key} has no 'pinned by'")
        for key in sorted(set(documented) - set(expected)):
            errors.append(
                f"CUTOVER_UNITS.md lists {kind} {key} that routing.toml lacks"
            )
    return errors


def status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return dict(Counter(r["status"].split(":", 1)[0] for r in rows))


# --- command line ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--status", action="store_true", help="print lane counts")
    parser.add_argument(
        "--skip-app-routes",
        action="store_true",
        help="do not import the FastAPI app to check registered routes",
    )
    args = parser.parse_args(argv)

    try:
        units = load_routing(ROUTING)
        rows = parse_board(BOARD.read_text(encoding="utf-8"))
    except (BoardError, OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"check_board: {exc}", file=sys.stderr)
        return 1

    if args.status:
        counts = status_counts(rows)
        for status in (*STATUSES, "blocked"):
            print(f"{status:<10} {counts.get(status, 0)}")
        print(f"{'total':<10} {len(rows)}")
        return 0

    errors = check_services(units) + check_rows(rows, units) + check_overlaps(rows)
    errors += check_cutover_document(units, CUTOVER_UNITS.read_text(encoding="utf-8"))
    if not args.skip_app_routes:
        sys.path.insert(0, str(ROOT))
        from app.api.app import create_app

        paths = registered_route_paths(create_app())
        errors += check_routes_assigned(units, paths)
        errors += check_lane_coverage(rows, units, paths)

    for error in errors:
        print(f"check_board: {error}", file=sys.stderr)
    if not errors:
        print(f"check_board: ok ({len(rows)} lanes, {len(units)} units)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
