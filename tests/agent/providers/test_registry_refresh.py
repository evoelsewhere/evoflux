from __future__ import annotations

import asyncio

import pytest

from app.agent.providers import registry_refresh


@pytest.fixture(autouse=True)
async def _stop_task():
    yield
    await registry_refresh.stop_model_registry_refresh()


async def test_first_pass_warms_the_registry_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The warm-up is the point: left to the first reader, the blocking fetch
    # inside the registry loader runs on whichever thread reads it — normally
    # an API handler on the event loop.
    threads: list[str] = []
    started = asyncio.Event()

    def _warm() -> bool:
        import threading

        threads.append(threading.current_thread().name)
        started.set()
        return False

    monkeypatch.setattr(registry_refresh, "refresh_model_registry_once", _warm)
    monkeypatch.setattr(
        registry_refresh.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", False
    )

    registry_refresh.start_model_registry_refresh()
    await asyncio.wait_for(started.wait(), timeout=5)

    assert threads
    assert threads[0] != "MainThread"


async def test_a_disabled_refresh_warms_once_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        registry_refresh,
        "refresh_model_registry_once",
        lambda: bool(calls.append(True)),
    )
    monkeypatch.setattr(
        registry_refresh.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", False
    )

    registry_refresh.start_model_registry_refresh()
    await asyncio.wait_for(registry_refresh._task, timeout=5)

    assert calls == [True]


async def test_the_loop_keeps_running_after_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passes = 0
    second_pass = asyncio.Event()

    def _refresh() -> bool:
        nonlocal passes
        passes += 1
        if passes == 1:
            raise RuntimeError("models.dev is down")
        second_pass.set()
        return False

    monkeypatch.setattr(registry_refresh, "refresh_model_registry_once", _refresh)
    monkeypatch.setattr(
        registry_refresh.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True
    )
    monkeypatch.setattr(registry_refresh, "_interval_seconds", lambda: 0.01)

    registry_refresh.start_model_registry_refresh()
    await asyncio.wait_for(second_pass.wait(), timeout=5)

    assert passes >= 2


async def test_start_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_refresh, "refresh_model_registry_once", lambda: False)
    monkeypatch.setattr(
        registry_refresh.settings, "EVOFLUX_MODEL_REGISTRY_REFRESH", True
    )
    monkeypatch.setattr(registry_refresh, "_interval_seconds", lambda: 3600.0)

    registry_refresh.start_model_registry_refresh()
    first = registry_refresh._task
    registry_refresh.start_model_registry_refresh()

    assert registry_refresh._task is first


def test_the_interval_never_drops_below_an_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_refresh.settings,
        "EVOFLUX_MODEL_REGISTRY_REFRESH_INTERVAL_HOURS",
        0,
    )
    assert registry_refresh._interval_seconds() == 3600.0
