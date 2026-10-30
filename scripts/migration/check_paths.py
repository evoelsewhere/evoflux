#!/usr/bin/env python3
"""Check migration PR paths against the area ownership board."""

from __future__ import annotations

import difflib
import fnmatch
import subprocess
import sys
from pathlib import Path


def allowed_path(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def valid_changelog(before: str, after: str) -> bool:
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    try:
        start = next(
            i for i, line in enumerate(old) if line.rstrip() == "## [Unreleased]"
        )
    except StopIteration:
        return False
    end = next(
        (i for i in range(start + 1, len(old)) if old[i].startswith("## ")), len(old)
    )
    changes = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    for tag, i1, _i2, j1, j2 in changes:
        if tag == "equal":
            continue
        if tag != "insert" or not (start < i1 <= end):
            return False
        if any(line.startswith("## ") for line in new[j1:j2]):
            return False
    return True


def valid_board_change(before: str, after: str, area: str) -> bool:
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    changes = [
        op
        for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if len(changes) != 1:
        return False
    tag, i1, i2, j1, j2 = changes[0]
    if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
        return False

    def lane(line: str) -> str:
        if not line.lstrip().startswith("|"):
            return ""
        return line.strip().strip("|").split("|")[0].strip().strip("`")

    return lane(old[i1]) == area and lane(new[j1]) == area


def unit_call_sites(text: str, unit: str) -> list[str] | None:
    """Globs from the unit table's ``adapter_call_sites`` cell; None if no such unit."""
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif "unit" in header and "adapter_call_sites" in header:
            if cells[header.index("unit")].strip("`") == unit:
                raw = cells[header.index("adapter_call_sites")]
                return [
                    g.strip().strip("`")
                    for g in raw.split(",")
                    if g.strip().strip("`") not in ("", "-")
                ]
    return None


def cutover_allowed(path: str, unit: str, call_sites: list[str]) -> bool:
    return (
        path
        in ("server/routing.toml", f"app/core/rust_bridge/{unit.replace('-', '_')}.py")
        or fnmatch.fnmatchcase(path, f"contract-tests/{unit}/*")
        or allowed_path(path, call_sites)
    )


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_paths.py <area>")
    area = sys.argv[1]
    base = "origin/migrate/rust-v4"
    paths = git("diff", "--name-only", f"{base}...HEAD").splitlines()
    if "CHANGELOG.md" in paths and not valid_changelog(
        git("show", f"{base}:CHANGELOG.md"), git("show", "HEAD:CHANGELOG.md")
    ):
        raise SystemExit("CHANGELOG.md must contain only additions under [Unreleased]")
    if area == "shared":
        print("Shared PR paths:")
        print("\n".join(paths) or "(none)")
        return 0
    if area.startswith("cutover-"):
        unit = area.removeprefix("cutover-")
        sites = unit_call_sites(
            Path("server/CUTOVER_UNITS.md").read_text(encoding="utf-8"), unit
        )
        if sites is None:
            raise SystemExit(
                f"Unknown cutover unit {unit!r} in server/CUTOVER_UNITS.md"
            )
        outside = [
            p
            for p in paths
            if p != "CHANGELOG.md" and not cutover_allowed(p, unit, sites)
        ]
        if outside:
            print(
                "Paths outside the cutover allow-list:\n" + "\n".join(outside),
                file=sys.stderr,
            )
            return 1
        return 0
    board = Path("server/MIGRATION_BOARD.md")
    if not board.is_file():
        raise SystemExit("Migration board is missing; cannot check ownership")
    from check_board import parse_board

    rows = [
        row
        for row in parse_board(board.read_text(encoding="utf-8"))
        if row["lane"] == area
    ]
    if len(rows) != 1:
        raise SystemExit(f"Expected one board row for {area}, found {len(rows)}")
    patterns = [
        part.strip().strip("`")
        for part in rows[0]["owned_paths"].split(",")
        if part.strip()
    ]
    outside = []
    for path in paths:
        if path == "CHANGELOG.md":
            continue
        if path == "server/MIGRATION_BOARD.md":
            if valid_board_change(
                git("show", f"{base}:{path}"), git("show", f"HEAD:{path}"), area
            ):
                continue
        elif allowed_path(path, patterns):
            continue
        outside.append(path)
    if outside:
        print("Paths outside area ownership:\n" + "\n".join(outside), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
