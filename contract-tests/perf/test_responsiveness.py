"""Responsiveness gate (design §8): the app must not freeze under heavy load.

Under every scenario in ``FREEZE_SCENARIOS``:

* ``/api/health/live`` p99 stays under 50 ms, and
* a session history page p99 stays within 2x its idle p99.

Scenarios that stall v3.1.1 are ``xfail(strict=True)`` for ``TARGET=python``
only and must pass for ``rust`` and ``gateway``.
"""

from __future__ import annotations

import os

import httpx
import pytest

from perf_measure import sample, wait_ready
from scenarios import FREEZE_SCENARIOS, HISTORY_PATH, V3_STALLS

HEALTH_P99_LIMIT_MS = 50.0
HISTORY_RATIO_LIMIT = 2.0
IDLE_HISTORY_SAMPLES = 100
LOAD_SECONDS = 10.0
COLD_START_SECONDS = 8.0
WARMUP = 5

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
    assert set(V3_STALLS) <= set(FREEZE_SCENARIOS)


def test_cold_start_health_live_p99(backend, client: httpx.Client) -> None:
    """``cold_start`` is its own scenario: probe straight after the handshake.

    No ``wait_ready`` here. v3.1.1 imports the MCP SDK on the event loop while
    optional services start, which is the stall the other scenarios must not
    inherit (they call ``wait_ready`` first).
    """
    live = sample(
        client, "/api/health/live", seconds=COLD_START_SECONDS, interval_s=0.02
    )
    assert live.errors == 0, f"/api/health/live failed {live.errors}/{live.count}"
    assert live.p99_ms < HEALTH_P99_LIMIT_MS, (
        f"cold_start: /api/health/live p99 {live.p99_ms:.1f} ms >= {HEALTH_P99_LIMIT_MS} ms"
    )


def test_percentile_is_nearest_rank() -> None:
    from perf_measure import percentile

    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 99) == 10
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert percentile([7.0], 99) == 7.0


@pytest.mark.parametrize("scenario", _params())
def test_health_live_p99_under_load(
    scenario: str, backend, client: httpx.Client
) -> None:
    wait_ready(backend)
    sample(client, HISTORY_PATH, count=WARMUP)
    idle = sample(client, HISTORY_PATH, count=IDLE_HISTORY_SAMPLES)
    assert idle.errors == 0, "idle history page must succeed"

    with FREEZE_SCENARIOS[scenario](backend):
        # Separate connections so one slow keep-alive socket cannot hide a stall.
        with httpx.Client(
            base_url=backend.base_url,
            headers={"Authorization": f"Bearer {backend.token}"},
            timeout=30.0,
        ) as probe:
            live = sample(
                probe, "/api/health/live", seconds=LOAD_SECONDS, interval_s=0.02
            )
            history = sample(probe, HISTORY_PATH, seconds=LOAD_SECONDS)

    assert live.errors == 0, f"/api/health/live failed {live.errors}/{live.count}"
    assert live.p99_ms < HEALTH_P99_LIMIT_MS, (
        f"{scenario}: /api/health/live p99 {live.p99_ms:.1f} ms >= {HEALTH_P99_LIMIT_MS} ms"
    )
    assert history.errors == 0, f"history failed {history.errors}/{history.count}"
    assert history.p99_ms <= HISTORY_RATIO_LIMIT * idle.p99_ms, (
        f"{scenario}: history p99 {history.p99_ms:.0f} ms > "
        f"{HISTORY_RATIO_LIMIT}x idle p99 {idle.p99_ms:.0f} ms"
    )
