"""Responsiveness gate (design §8): the app must not freeze under heavy load.

Under every scenario in ``FREEZE_SCENARIOS``:

* ``/api/health/live`` p99 stays under 50 ms, and
* a session history page p99 stays within 2x its idle p99, and
* no probe of either takes 1 s or more.

Latency is measured from each probe's scheduled send time on a fixed-rate
schedule (see ``perf_measure.probe_open_loop``), so a stall cannot hide.

Scenarios that stall v3.1.1 are ``xfail(strict=True)`` for ``TARGET=python``
only and must pass for ``rust`` and ``gateway``.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from perf_measure import probe_open_loop, wait_ready
from scenarios import FREEZE_SCENARIOS, HISTORY_PATH, V3_STALLS

HEALTH_P99_LIMIT_MS = 50.0
HISTORY_RATIO_LIMIT = 2.0
MAX_LIMIT_MS = 1000.0
LIVE_RATE_HZ = 50.0
HISTORY_RATE_HZ = 10.0
LOAD_SECONDS = 10.0
COLD_START_SECONDS = 8.0

_TARGET = os.environ.get("TARGET", "python")


def _params() -> list:
    out = []
    for name in FREEZE_SCENARIOS:
        marks = []
        if _TARGET == "python" and name in V3_STALLS:
            marks.append(pytest.mark.xfail(strict=True, reason=V3_STALLS[name]))
        out.append(pytest.param(name, id=name, marks=marks))
    return out


def test_scenarios_are_registered() -> None:
    expected = {
        "large_repo_open",
        "long_tool_run",
        "large_history_page",
        "concurrent_history_reads",
        "hung_mcp_server",
    }
    assert expected <= set(FREEZE_SCENARIOS)
    assert set(V3_STALLS) <= set(FREEZE_SCENARIOS) | {"cold_start"}


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            "cold_start",
            marks=[pytest.mark.xfail(strict=True, reason=V3_STALLS["cold_start"])]
            if _TARGET == "python"
            else [],
        )
    ],
)
def test_cold_start_health_live_p99(scenario: str, backend) -> None:
    """``cold_start`` is its own scenario: probe straight after the handshake.

    No ``wait_ready`` here. v3.1.1 imports the MCP SDK on the event loop while
    optional services start (T1 measured 1.1-1.4 s), which is the stall the
    other scenarios must not inherit (they call ``wait_ready`` first).
    """
    live = probe_open_loop(
        backend, "/api/health/live", seconds=COLD_START_SECONDS, rate_hz=LIVE_RATE_HZ
    )
    _assert_live(live, scenario)


def _assert_live(live, scenario: str) -> None:
    assert live.errors == 0, f"/api/health/live failed {live.errors}/{live.count}"
    assert live.p99_ms < HEALTH_P99_LIMIT_MS, (
        f"{scenario}: /api/health/live p99 {live.p99_ms:.1f} ms >= {HEALTH_P99_LIMIT_MS} ms"
    )
    assert live.max_ms < MAX_LIMIT_MS, (
        f"{scenario}: /api/health/live max {live.max_ms:.0f} ms >= {MAX_LIMIT_MS} ms"
    )


def test_percentile_is_nearest_rank() -> None:
    from perf_measure import percentile

    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 99) == 10
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert percentile([7.0], 99) == 7.0


@pytest.mark.parametrize("scenario", _params())
def test_health_live_p99_under_load(scenario: str, backend) -> None:
    wait_ready(backend)
    idle = probe_open_loop(
        backend, HISTORY_PATH, seconds=LOAD_SECONDS, rate_hz=HISTORY_RATE_HZ
    )
    assert idle.errors == 0, "idle history page must succeed"

    # Both probes run at once on a fixed schedule, each probe on its own
    # connection, so one stuck socket or one stalled loop cannot hide.
    with FREEZE_SCENARIOS[scenario](backend), ThreadPoolExecutor(2) as pool:
        live_future = pool.submit(
            probe_open_loop,
            backend,
            "/api/health/live",
            seconds=LOAD_SECONDS,
            rate_hz=LIVE_RATE_HZ,
        )
        history_future = pool.submit(
            probe_open_loop,
            backend,
            HISTORY_PATH,
            seconds=LOAD_SECONDS,
            rate_hz=HISTORY_RATE_HZ,
        )
        live, history = live_future.result(), history_future.result()

    _assert_live(live, scenario)
    assert history.errors == 0, f"history failed {history.errors}/{history.count}"
    assert history.max_ms < MAX_LIMIT_MS, (
        f"{scenario}: history max {history.max_ms:.0f} ms >= {MAX_LIMIT_MS} ms"
    )
    assert history.p99_ms <= HISTORY_RATIO_LIMIT * idle.p99_ms, (
        f"{scenario}: history p99 {history.p99_ms:.0f} ms > "
        f"{HISTORY_RATIO_LIMIT}x idle p99 {idle.p99_ms:.0f} ms"
    )
