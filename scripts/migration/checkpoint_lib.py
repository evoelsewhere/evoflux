"""Pure helpers for ``e2e.sh --rust-forward`` and ``checkpoint.sh`` (design 9a).

``override`` prints the ``EVOFLUX_ROUTE_OVERRIDE`` string for the units in
``server/rust-ready.toml``; ``report`` writes the checkpoint report from the
step logs and exits non-zero when any step failed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READY = ROOT / "server" / "rust-ready.toml"
NO_UNITS = "no Rust-ready units yet"
_UNIT = re.compile(r"^[A-Za-z0-9_.-]+$")


def read_rust_ready(path: Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    units = data.get("units")
    if not isinstance(units, list) or not all(isinstance(u, str) for u in units):
        raise ValueError(f'{path}: expected units = ["..."]')
    return units


def build_override(units: list[str], explicit: str | None = None) -> str:
    """Rust-ready units first; an explicit override is appended last so it wins."""
    for unit in units:
        if not _UNIT.match(unit):
            raise ValueError(f"invalid unit name {unit!r}")
    parts = [f"{unit}=rust" for unit in units]
    if explicit:
        parts.append(explicit)
    return ",".join(parts)


def _pytest_counts(text: str) -> dict[str, int]:
    summary = [ln for ln in text.splitlines() if re.search(r"\d+ (passed|failed)", ln)]
    if summary:
        return {
            key: int(m[1]) if (m := re.search(rf"(\d+) {key}\b", summary[-1])) else 0
            for key in ("passed", "failed", "skipped")
        }
    # `-q` configs can drop the summary line: count the progress characters.
    marks = "".join(
        ln.split()[0]
        for ln in text.splitlines()
        if re.fullmatch(r"[.FEsxX]+(\s+\[\s*\d+%\])?", ln.strip())
    )
    return {
        "passed": marks.count("."),
        "failed": marks.count("F") + marks.count("E"),
        "skipped": marks.count("s"),
    }


def parse_counts(kind: str, text: str) -> dict[str, int]:
    if kind != "playwright":
        return _pytest_counts(text)
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for key in counts:
        match = re.search(rf"^\s*(\d+) {key}\b", text, re.M)
        if match:
            counts[key] = int(match.group(1))
    return counts


def extract_failures(kind: str, text: str) -> list[str]:
    if kind == "playwright":
        return [
            line.strip()
            for line in text.splitlines()
            if re.match(r"^\s+x\s+\d+ ", line)
        ]
    return [line.strip() for line in text.splitlines() if line.startswith("FAILED ")]


_STEP = re.compile(r"^(.*?):(\d+):(playwright|pytest):(.+)$")


def parse_step(spec: str) -> tuple[str, int, str, str]:
    """``name:exit:kind:logfile``; the name and the path may contain colons."""
    match = _STEP.match(spec)
    if not match:
        raise ValueError(f"bad --step {spec!r}; expected name:exit:kind:logfile")
    return match[1], int(match[2]), match[3], match[4]


def overall_exit(steps: list[dict]) -> int:
    return 1 if any(step["exit_code"] != 0 for step in steps) else 0


def render_report(
    phase: str,
    commit: str,
    date: str,
    units: list[str],
    steps: list[dict],
) -> str:
    on_rust = ", ".join(f"`{u}`" for u in units) if units else f"none ({NO_UNITS})"
    rows = [
        f"| {s['name']} | {'PASS' if s['exit_code'] == 0 else 'FAIL'} "
        f"| {s['passed']} | {s['failed']} | {s['skipped']} |"
        for s in steps
    ]
    failures = [(s["name"], f) for s in steps for f in s["failures"]]
    lines = [
        f"# Checkpoint {phase} ({date})",
        "",
        "**Label:** automated: not owner use. This is automated evidence only; it is not the owner's daily use and not owner approval.",
        "",
        f"- **Commit:** `{commit}`",
        f"- **Units on Rust:** {on_rust}",
        f"- **Result: {'FAIL' if overall_exit(steps) else 'PASS'}**",
        "",
        "| Step | Result | Passed | Failed | Skipped |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "## Failures",
        "",
    ]
    if failures:
        lines += [f"- {name}: `{item}`" for name, item in failures]
    else:
        lines.append("No failures.")
    return "\n".join(lines) + "\n"


def _cmd_override(args: argparse.Namespace) -> int:
    units = read_rust_ready(Path(args.ready))
    if not units:
        print(f"{NO_UNITS}; running the default routing", file=sys.stderr)
    sys.stdout.write(build_override(units, args.explicit))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    steps = []
    for spec in args.step:
        name, code, kind, log = parse_step(spec)
        text = Path(log).read_text(encoding="utf-8", errors="replace")
        steps.append(
            {
                "name": name,
                "exit_code": code,
                **parse_counts(kind, text),
                "failures": extract_failures(kind, text),
            }
        )
    units = [u for u in args.units.split(",") if u]
    Path(args.out).write_text(
        render_report(args.phase, args.commit, args.date, units, steps),
        encoding="utf-8",
        newline="\n",
    )
    return overall_exit(steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    over = sub.add_parser("override")
    over.add_argument(
        "--ready", default=os.environ.get("EVOFLUX_RUST_READY_FILE", str(READY))
    )
    over.add_argument("--explicit", default=None)
    over.set_defaults(func=_cmd_override)
    rep = sub.add_parser("report")
    rep.add_argument("--phase", required=True)
    rep.add_argument("--commit", required=True)
    rep.add_argument("--date", required=True)
    rep.add_argument("--units", default="")
    rep.add_argument("--out", required=True)
    rep.add_argument(
        "--step", action="append", default=[], help="name:exit:kind:logfile"
    )
    rep.set_defaults(func=_cmd_report)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
