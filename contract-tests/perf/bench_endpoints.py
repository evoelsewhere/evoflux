"""Measure cold start, idle memory and endpoint latency; write or compare a baseline.

    uv run --group contract python contract-tests/perf/bench_endpoints.py record \
        --target python --machine "<machine name>"
    uv run --group contract python contract-tests/perf/bench_endpoints.py compare \
        --target gateway --area health

``record`` measures the python backend ``NOISE_RUNS`` times, each on fresh
backends. The baseline holds the median of every figure plus its *measured noise
floor*, the spread (max - min) of that figure across the repeats (workflow 5.3,
python against python). ``compare`` exits 1 when an endpoint's p99 exceeds
``max(1.1 x baseline, baseline + its measured floor)``, or, for ``--area all``,
when cold start, idle memory or first-event latency exceed the same limit. This
replaces a flat 10 % limit, which timer noise on 3 ms endpoints would trip
(orchestrator decision, recorded in the baseline's ``notes``). Areas are path
prefixes: ``health`` -> ``/api/health/``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
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
from mock_provider.server import MockProvider  # noqa: E402

MOCK_MODEL = "mock-model"  # same id the contract conftest registers

BASELINE = Path(__file__).with_name("baseline-v3.1.1.json")
SAMPLES = 200
WARMUP = 10
COLD_START_RUNS = 3
NOISE_RUNS = 5
SSE_TURNS = 10
SAMPLE_BUDGET_S = 12.0  # per endpoint; at least 30 samples are always taken
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
            result = sample(client, path, count=SAMPLES, budget_s=SAMPLE_BUDGET_S)
            if result.errors:
                raise SystemExit(f"{path}: {result.errors}/{result.count} non-200")
            endpoints[path] = {
                "p50_ms": round(result.p50_ms, 2),
                "p99_ms": round(result.p99_ms, 2),
            }
        time.sleep(2.0)  # let lazy startup work settle before reading memory
        rss = _rss_mb(backend.pid)
        first_event = _sse_first_event_ms(backend, client)
    return {
        "cold_start_ms": round(percentile(cold, 50), 1),
        "idle_rss_mb": round(rss, 1),
        "endpoints": endpoints,
        "sse_first_event_ms": first_event,
    }


def _sse_first_event_ms(backend: Backend, client: httpx.Client) -> float:
    """Median time from posting a chat message to the first SSE event of its turn.

    The model is the replaying mock provider, so this is the backend's own
    latency. It runs last because seeding the bundled agents changes settings.
    """
    mock = MockProvider()
    try:
        mock.load("openai_text_hello")
        client.put(
            "/api/settings/providers/router9",
            json={
                "api_key": "mock-key",
                "extra": {"ROUTER9_BASE_URL": f"{mock.base_url}/v1"},
            },
        ).raise_for_status()
        client.post(
            "/api/settings/seed", json={"provider_model": f"router9:{MOCK_MODEL}"}
        ).raise_for_status()
        times: list[float] = []
        for _ in range(SSE_TURNS):
            started = time.perf_counter()
            sent = client.post("/api/team/chat", data={"message": "say hello"})
            sent.raise_for_status()
            url = f"/api/team/{sent.json()['session_id']}/stream"
            with client.stream(
                "GET", url, headers={"Accept": "text/event-stream"}
            ) as stream:
                for line in stream.iter_lines():
                    if line.startswith(("event:", "data:")):
                        times.append((time.perf_counter() - started) * 1000)
                        break
                else:
                    raise SystemExit("SSE stream ended without an event")
        return round(percentile(times, 50), 2)
    finally:
        mock.close()


def _machine(name: str) -> dict:
    return {
        "name": name,
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def aggregate(runs: list[dict]) -> dict:
    """Median of every figure across ``runs`` plus its spread as the noise floor."""
    endpoints = {
        path: {
            "p50_ms": round(
                statistics.median(r["endpoints"][path]["p50_ms"] for r in runs), 2
            ),
            "p99_ms": round(
                statistics.median(r["endpoints"][path]["p99_ms"] for r in runs), 2
            ),
            "floor_ms": round(
                _spread([r["endpoints"][path]["p99_ms"] for r in runs]), 2
            ),
        }
        for path in runs[0]["endpoints"]
    }
    out: dict = {}
    for key, floor_key in FIGURES:
        values = [r[key] for r in runs]
        out[key] = round(statistics.median(values), 2)
        out[floor_key] = round(_spread(values), 2)
    out["endpoints"] = endpoints
    return out


def _spread(values: list[float]) -> float:
    return max(values) - min(values)


FIGURES = (
    ("cold_start_ms", "cold_start_floor_ms"),
    ("idle_rss_mb", "idle_rss_floor_mb"),
    ("sse_first_event_ms", "sse_first_event_floor_ms"),
)

NOTES = (
    "Median of {runs} python-v3.1.1 runs, each on fresh backends. floor_ms (and "
    "the *_floor_* fields) is the spread of that figure across the runs: the "
    "python-vs-python noise baseline (workflow 5.3). The compare limit is "
    "max(1.1 x p99, p99 + floor_ms), a measured per-endpoint floor in place of "
    "the plan's flat 10 % (orchestrator decision). sse_first_event_ms is "
    "chat POST to first SSE event, with the replaying mock provider."
)


def record(args: argparse.Namespace) -> int:
    runs = [measure(args.target) for _ in range(NOISE_RUNS)]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    data = {
        "notes": NOTES.format(runs=NOISE_RUNS),
        "version": "3.1.1",
        "target": args.target,
        "machine": _machine(args.machine),
        "git_commit": commit,
        "samples_per_endpoint": f"up to {SAMPLES} (at least 30, {SAMPLE_BUDGET_S:.0f} s budget)",
        "noise_runs": NOISE_RUNS,
        **aggregate(runs),
    }
    Path(args.out).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {args.out} ({len(data['endpoints'])} endpoints)")
    return 0


def _limit(base: float, floor: float) -> float:
    return max(base * RATIO_LIMIT, base + floor)


def regressions(baseline: dict, current: dict, area: str) -> list[str]:
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
        limit = _limit(base["p99_ms"], base["floor_ms"])
        if now["p99_ms"] > limit:
            out.append(
                f"{path}: p99 {now['p99_ms']} ms vs baseline {base['p99_ms']} ms "
                f"(limit {limit:.1f} ms)"
            )
    if area == "all":
        for key, floor_key in FIGURES:
            limit = _limit(baseline[key], baseline[floor_key])
            if current[key] > limit:
                out.append(
                    f"{key}: {current[key]} vs baseline {baseline[key]} "
                    f"(limit {limit:.1f})"
                )
    return out


def compare(args: argparse.Namespace) -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    # Median of the same number of runs as the baseline, so run-to-run drift
    # cancels the way it does there.
    current = aggregate([measure(args.target) for _ in range(args.runs)])
    problems = regressions(baseline, current, args.area)
    if problems:
        # Host load between sessions can exceed the spread inside one recording
        # (python against python tripped 5 of 30 endpoints), so a regression
        # counts only when a second, fresh measurement exceeds the limit too.
        print(f"{len(problems)} over the limit; re-measuring to confirm", flush=True)
        again = {
            line.split(":")[0]
            for line in regressions(
                baseline,
                aggregate([measure(args.target) for _ in range(args.runs)]),
                args.area,
            )
        }
        problems = [line for line in problems if line.split(":")[0] in again]
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
    cmp_.add_argument("--runs", type=int, default=NOISE_RUNS)
    cmp_.set_defaults(func=compare)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
