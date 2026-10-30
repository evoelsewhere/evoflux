"""Measure cold start, idle memory and endpoint latency; write or compare a baseline.

    uv run --group contract python contract-tests/perf/bench_endpoints.py record \
        --target python --machine "<machine name>"
    uv run --group contract python contract-tests/perf/bench_endpoints.py compare \
        --target gateway --area health

``compare`` exits 1 when any endpoint of the area has a p99 more than 10 % above
the baseline (and more than ``--floor-ms`` above it, so timer noise on 3 ms
endpoints cannot fail a build), or, for ``--area all``, when cold start or idle
memory regress by more than the same ratio. Areas are path prefixes:
``health`` -> ``/api/health/``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backends import Backend, start_backend  # noqa: E402
from perf_measure import percentile, sample, wait_ready  # noqa: E402
from perf_seed import BIG_SESSION_ID, seed_database  # noqa: E402

BASELINE = Path(__file__).with_name("baseline-v3.1.1.json")
SAMPLES = 200
WARMUP = 10
COLD_START_RUNS = 3
RATIO_LIMIT = 1.10

# The UI's boot and session-open request sequence (T15 recordings replace this
# list once they exist). Every entry must answer 200 on a freshly seeded v3.1.1.
ENDPOINTS: list[str] = [
    "/api/health/live",
    "/api/health/ready",
    "/api/health/diagnostics",
    "/api/agents",
    "/api/skills",
    "/api/commands",
    "/api/mcp/servers",
    "/api/plugins",
    "/api/settings/providers",
    "/api/settings/context",
    "/api/settings/sandbox",
    "/api/settings/version-control",
    "/api/settings/response-style",
    "/api/settings/follow-up",
    "/api/settings/team-spawn",
    "/api/settings/background-tasks",
    "/api/scheduler/tasks",
    "/api/team/leads",
    "/api/team/sessions",
    "/api/team/session-folders",
    "/api/team/projects",
    "/api/team/processes",
    "/api/team/office-runtime/status",
    "/api/team/reviews/connections",
    "/api/team/webbridge/status",
    "/api/observability/summary",
    "/api/wiki/tree",
    f"/api/team/{BIG_SESSION_ID}/history",
    f"/api/team/sessions/{BIG_SESSION_ID}",
    f"/api/team/{BIG_SESSION_ID}/goal",
]

AREA_PREFIXES = {
    "health": "/api/health/",
    "agents": "/api/agents",
    "skills": "/api/skills",
    "commands": "/api/commands",
    "mcp": "/api/mcp/",
    "plugins": "/api/plugins",
    "settings": "/api/settings/",
    "scheduler": "/api/scheduler/",
    "team": "/api/team/",
    "observability": "/api/observability/",
    "wiki": "/api/wiki/",
}


def _rss_mb(pid: int) -> float:
    """Resident memory of ``pid`` and its descendants, in MiB."""
    import psutil

    root = psutil.Process(pid)
    total = 0
    for proc in [root, *root.children(recursive=True)]:
        try:
            total += proc.memory_info().rss
        except psutil.Error:
            pass
    return total / (1024 * 1024)


def _build_seeded_db(workdir: Path) -> Path:
    base = workdir / "schema"
    base.mkdir()
    start_backend("python", base).stop()
    db = base / "data" / "evoflux.db"
    seed_database(db)
    return db


def measure(target: str) -> dict:
    workdir = Path(tempfile.mkdtemp(prefix="evoflux-perf-seed-"))
    runs: list[Path] = []
    try:
        db = _build_seeded_db(workdir)
        cold: list[float] = []
        backend: Backend | None = None
        for run in range(COLD_START_RUNS + 1):  # the first start is discarded
            if backend is not None:
                backend.stop()
            base = Path(tempfile.mkdtemp(prefix="evoflux-perf-run-"))
            runs.append(base)
            started = time.perf_counter()
            backend = start_backend(target, base, db)  # type: ignore[arg-type]
            if run:
                cold.append((time.perf_counter() - started) * 1000)
        assert backend is not None
        try:
            return _measure_running(backend, cold)
        finally:
            backend.stop()
    finally:
        for path in [workdir, *runs]:
            shutil.rmtree(path, ignore_errors=True)


def _measure_running(backend: Backend, cold: list[float]) -> dict:
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": f"Bearer {backend.token}"},
        timeout=60.0,
    ) as client:
        wait_ready(backend)  # cold start is timed above, never mixed into latency
        endpoints: dict[str, dict[str, float]] = {}
        for path in ENDPOINTS:
            sample(client, path, count=WARMUP)
            result = sample(client, path, count=SAMPLES)
            if result.errors:
                raise SystemExit(f"{path}: {result.errors}/{result.count} non-200")
            endpoints[path] = {
                "p50_ms": round(result.p50_ms, 2),
                "p99_ms": round(result.p99_ms, 2),
            }
        time.sleep(2.0)  # let lazy startup work settle before reading memory
        rss = _rss_mb(backend.pid)
        opens: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            with client.stream("GET", f"/api/team/{BIG_SESSION_ID}/stream") as resp:
                resp.read()
            opens.append((time.perf_counter() - started) * 1000)
    return {
        "cold_start_ms": round(percentile(cold, 50), 1),
        "idle_rss_mb": round(rss, 1),
        "endpoints": endpoints,
        # With no model no turn can be in flight, so an idle stream answers and
        # closes without an event. First-event latency needs the T5 mock
        # provider; until then the open-and-close time is recorded instead.
        "sse_first_event_ms": None,
        "sse_idle_open_ms": round(percentile(opens, 50), 2),
    }


def _machine(name: str) -> dict:
    return {
        "name": name,
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def record(args: argparse.Namespace) -> int:
    measured = measure(args.target)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    data = {
        "version": "3.1.1",
        "target": args.target,
        "machine": _machine(args.machine),
        "git_commit": commit,
        "samples_per_endpoint": SAMPLES,
        **measured,
    }
    Path(args.out).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {args.out} ({len(data['endpoints'])} endpoints)")
    return 0


def regressions(baseline: dict, current: dict, area: str, floor_ms: float) -> list[str]:
    """Human-readable regressions of ``current`` against ``baseline``."""
    prefix = AREA_PREFIXES.get(area, area)
    out: list[str] = []
    for path, base in baseline["endpoints"].items():
        if area != "all" and not path.startswith(prefix):
            continue
        now = current["endpoints"].get(path)
        if now is None:
            out.append(f"{path}: not measured")
            continue
        limit = max(base["p99_ms"] * RATIO_LIMIT, base["p99_ms"] + floor_ms)
        if now["p99_ms"] > limit:
            out.append(
                f"{path}: p99 {now['p99_ms']} ms vs baseline {base['p99_ms']} ms "
                f"(limit {limit:.1f} ms)"
            )
    if area == "all":
        for key in ("cold_start_ms", "idle_rss_mb"):
            if current[key] > baseline[key] * RATIO_LIMIT:
                out.append(f"{key}: {current[key]} vs baseline {baseline[key]}")
    return out


def compare(args: argparse.Namespace) -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = measure(args.target)
    problems = regressions(baseline, current, args.area, args.floor_ms)
    for line in problems:
        print("REGRESSION", line)
    if not problems:
        print(f"perf ok: area={args.area} target={args.target}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--target", default="python")
    rec.add_argument("--out", default=str(BASELINE))
    rec.add_argument("--machine", required=True, help="reference machine name")
    rec.set_defaults(func=record)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--target", default="python")
    cmp_.add_argument("--area", default="all")
    cmp_.add_argument("--floor-ms", type=float, default=5.0)
    cmp_.set_defaults(func=compare)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
