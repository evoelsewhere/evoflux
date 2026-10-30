"""Latency sampling shared by the responsiveness gate and ``bench_endpoints``."""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx


def percentile(samples: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True)
class Latency:
    count: int
    errors: int
    p50_ms: float
    p99_ms: float
    max_ms: float


def sample(
    client: httpx.Client,
    path: str,
    *,
    count: int | None = None,
    seconds: float | None = None,
    interval_s: float = 0.0,
    expect_status: int = 200,
    budget_s: float | None = None,
    min_count: int = 30,
) -> Latency:
    """Time sequential GETs for ``count`` requests or ``seconds``, whichever is set.

    A non-``expect_status`` answer or a transport error counts as an error and
    is recorded at its elapsed time, so a hang shows up as latency, not as a gap.
    """
    assert (count is None) != (seconds is None)
    # ``budget_s`` ends a ``count`` run early (after ``min_count`` samples) so an
    # endpoint that takes a second per call cannot dominate the whole recording.
    budget_end = None if budget_s is None else time.perf_counter() + budget_s
    latencies: list[float] = []
    errors = 0
    deadline = None if seconds is None else time.perf_counter() + seconds
    while True:
        if deadline is None:
            if len(latencies) >= (count or 0):
                break
            if (
                budget_end is not None
                and len(latencies) >= min_count
                and time.perf_counter() >= budget_end
            ):
                break
        elif time.perf_counter() >= deadline:
            break
        started = time.perf_counter()
        try:
            ok = client.get(path).status_code == expect_status
        except httpx.HTTPError:
            ok = False
        latencies.append((time.perf_counter() - started) * 1000)
        errors += 0 if ok else 1
        if interval_s:
            time.sleep(interval_s)
    return _summary(latencies, errors)


def _summary(latencies: list[float], errors: int) -> Latency:
    return Latency(
        len(latencies),
        errors,
        percentile(latencies, 50),
        percentile(latencies, 99),
        max(latencies),
    )


def probe_open_loop(
    backend,
    path: str,
    *,
    seconds: float,
    rate_hz: float,
    expect_status: int = 200,
) -> Latency:
    """GET ``path`` at a fixed rate; latency runs from each probe's *scheduled* time.

    A closed loop (send, wait, send) turns a one-second event-loop block into one
    slow sample (coordinated omission). Here probes keep being scheduled while the
    server is stuck, each on its own thread and connection, and every one is
    charged the time since it was due, so a 1 s freeze shows up as ~``rate_hz``
    slow samples.
    """
    interval = 1.0 / rate_hz
    local = threading.local()
    clients: list[httpx.Client] = []
    results: list[tuple[float, bool]] = []

    def fire(scheduled: float) -> None:
        http = getattr(local, "http", None)
        if http is None:
            http = httpx.Client(
                base_url=backend.base_url,
                headers={"Authorization": f"Bearer {backend.token}"},
                timeout=30.0,
            )
            local.http = http
            clients.append(http)
        try:
            ok = http.get(path).status_code == expect_status
        except httpx.HTTPError:
            ok = False
        results.append(((time.perf_counter() - scheduled) * 1000, ok))

    start = time.perf_counter() + 0.05
    with ThreadPoolExecutor(max_workers=128) as pool:
        for i in range(int(seconds * rate_hz)):
            scheduled = start + i * interval
            delay = scheduled - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            pool.submit(fire, scheduled)
    for http in clients:
        http.close()
    return _summary([ms for ms, _ in results], sum(1 for _, ok in results if not ok))


def wait_ready(backend, timeout_s: float = 60.0) -> None:
    """Block until startup work (optional services, MCP import) has finished.

    Python logs ``optional_services_ready``; a backend that never logs it (Rust,
    gateway) falls back to ``/api/health/ready``. Either way a short settle
    follows, so the startup stall lands on no scenario.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if "optional_services_ready" in backend.log_tail():
            break
        time.sleep(0.25)
    else:
        with httpx.Client(base_url=backend.base_url, timeout=10.0) as http:
            http.get(
                "/api/health/ready",
                headers={"Authorization": f"Bearer {backend.token}"},
            ).raise_for_status()
    time.sleep(2.0)
