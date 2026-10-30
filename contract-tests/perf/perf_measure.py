"""Latency sampling shared by the responsiveness gate and ``bench_endpoints``."""

from __future__ import annotations

import math
import time
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


def sample(
    client: httpx.Client,
    path: str,
    *,
    count: int | None = None,
    seconds: float | None = None,
    interval_s: float = 0.0,
    expect_status: int = 200,
) -> Latency:
    """Time sequential GETs for ``count`` requests or ``seconds``, whichever is set.

    A non-``expect_status`` answer or a transport error counts as an error and
    is recorded at its elapsed time, so a hang shows up as latency, not as a gap.
    """
    assert (count is None) != (seconds is None)
    latencies: list[float] = []
    errors = 0
    deadline = None if seconds is None else time.perf_counter() + seconds
    while True:
        if deadline is None:
            if len(latencies) >= (count or 0):
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
    return Latency(
        len(latencies), errors, percentile(latencies, 50), percentile(latencies, 99)
    )


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
