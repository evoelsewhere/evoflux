"""Tests for the dream scheduler — focuses on the reload-during-fire path
which used to hang the FastAPI worker (A1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.dream_scheduler import DreamScheduler


@pytest.fixture
def _dream_md(tmp_path: Path, monkeypatch):
    """Write enabled Dream settings and point settings at the tmp dir."""
    from app.core.config import settings
    from app.core.runtime_settings import (
        DreamSettings,
        RuntimeSettings,
        save_runtime_settings,
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings(
            dream=DreamSettings(
                enabled=True,
                model="mock:model",
                schedule="* * * * *",
            )
        )
    )
    yield config_dir


def _fake_db_factory():
    """Stub db factory — never actually used because we patch run_dream."""

    class _Ctx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_):
            return False

    def _factory():
        return _Ctx()

    return _factory


@pytest.mark.asyncio
async def test_reload_during_fire_does_not_block(_dream_md: Path):
    """``reload()`` arriving while a dream fire is in progress must return
    promptly (does NOT await the in-progress fire) — A1.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    fire_started = asyncio.Event()
    fire_release = asyncio.Event()

    async def _slow_run_dream(_db) -> dict:
        fire_started.set()
        # Simulate a long-running synthesis.
        await fire_release.wait()
        return {
            "sessions_processed": 0,
            "notes_processed": 0,
            "remaining": 0,
            "failed": 0,
        }

    # Patch the source module — the scheduler does a lazy import inside
    # ``_fire``, so we must replace the attribute on ``app.services.dream``.
    with patch("app.services.dream.run_dream", _slow_run_dream):
        # Skip the cron sleep by mocking ``asyncio.sleep`` to return
        # immediately for the scheduler's first wait, then let subsequent
        # sleeps work normally so we don't burn CPU.
        original_sleep = asyncio.sleep
        sleep_calls = {"count": 0}

        async def _fast_first_sleep(seconds: float, *args, **kwargs):
            sleep_calls["count"] += 1
            if sleep_calls["count"] == 1:
                # First sleep is the cron wait — collapse it.
                await original_sleep(0)
                return
            await original_sleep(min(seconds, 0.01))

        with patch("app.services.dream_scheduler.asyncio.sleep", _fast_first_sleep):
            await scheduler.start()
            try:
                # Wait for the fire to start.
                await asyncio.wait_for(fire_started.wait(), timeout=2.0)

                # Reload MUST return promptly even though the fire is wedged.
                reload_done = asyncio.get_running_loop().create_future()

                async def _do_reload():
                    await scheduler.reload()
                    reload_done.set_result(True)

                reload_task = asyncio.create_task(_do_reload())

                # If A1 is fixed, reload completes within ~1s.  If broken,
                # it would hang until ``fire_release`` is set.
                try:
                    await asyncio.wait_for(reload_done, timeout=2.0)
                except asyncio.TimeoutError:
                    fire_release.set()
                    reload_task.cancel()
                    pytest.fail("reload() blocked on in-progress fire — A1 regression")
            finally:
                # Release the wedged fire so background tasks finish cleanly.
                fire_release.set()
                await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_during_sleep_returns_quickly(_dream_md: Path):
    """``stop()`` called while the scheduler is sleeping returns immediately."""
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    await scheduler.start()
    # The scheduler is sleeping until the next cron tick (up to 60s).
    # stop() must not block on that sleep.
    await asyncio.wait_for(scheduler.stop(), timeout=2.0)


# ── S6: start() is idempotent ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_is_idempotent(_dream_md: Path):
    """A second ``start()`` while already running must not leak the first
    scheduler task (S6).  Before the fix, the second call overwrote
    ``self._task`` and the first task ran forever as an orphan.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    await scheduler.start()
    first_task = scheduler._task
    assert first_task is not None

    await scheduler.start()
    # Same task — not a new one.
    assert scheduler._task is first_task

    await scheduler.stop()


# ── S3: concurrent reload() calls do not leak scheduler tasks ────────────────


@pytest.mark.asyncio
async def test_concurrent_reloads_do_not_leak(_dream_md: Path):
    """Two ``reload()`` calls firing concurrently must serialise through the
    lifecycle lock so only one fresh scheduler task survives (S3).
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    await scheduler.start()
    initial = scheduler._task
    assert initial is not None

    # Both reloads should funnel through the lifecycle lock.
    await asyncio.gather(scheduler.reload(), scheduler.reload())

    # Exactly one new task — and it differs from the initial.
    new_task = scheduler._task
    assert new_task is not None
    assert new_task is not initial
    # Initial task is cancelled or done.
    assert initial.done() or initial.cancelled()

    await scheduler.stop()


# ── DS6: _fire logs exceptions with full traceback ───────────────────────────


@pytest.mark.asyncio
async def test_fire_logs_exception_with_traceback(_dream_md: Path):
    """A bug inside ``run_dream`` must surface with a full traceback via
    ``logger.exception`` instead of being silently swallowed (DS6).
    """
    from loguru import logger

    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    async def _boom(_db) -> dict:
        raise RuntimeError("simulated bug")

    captured: list[str] = []
    handler_id = logger.add(lambda msg: captured.append(str(msg)), level="ERROR")

    try:
        with patch("app.services.dream.run_dream", _boom):
            # Drive _fire directly rather than spinning up the cron loop.
            await scheduler._fire()
    finally:
        logger.remove(handler_id)

    # Must have logged the failure AND included the traceback (loguru
    # ``logger.exception`` prefixes the formatted record with the traceback).
    assert any("dream_scheduler_fire_failed" in c for c in captured)
    assert any("RuntimeError" in c and "simulated bug" in c for c in captured)


# ── Coverage gap: reload() with no prior start is a no-op ────────────────────


@pytest.mark.asyncio
async def test_reload_without_prior_start_is_safe(_dream_md: Path):
    """Calling ``reload()`` before ``start()`` must not raise (the API
    routes call it unconditionally after ``PUT /api/dream/config``).
    It should also leave the scheduler in a started state if Dream settings
    is enabled.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    # No start() yet.
    assert scheduler._task is None
    await scheduler.reload()
    # reload calls _start_unlocked which spawns a fresh loop task because
    # Dream is enabled in this fixture.
    assert scheduler._task is not None
    assert not scheduler._task.done()

    await scheduler.stop()


# ── Coverage gap: reload() picks up enabled=false → stops firing ─────────────


@pytest.mark.asyncio
async def test_reload_with_disabled_dream_md_stops_scheduler(_dream_md: Path):
    """When Dream flips ``enabled: true`` → ``enabled: false`` and the
    user calls ``PUT /api/dream/config``, the scheduler must NOT spawn a
    new loop task.  Otherwise disabling dream via the UI would have no
    effect until restart.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())
    await scheduler.start()
    assert scheduler._task is not None

    from app.core.runtime_settings import (
        DreamSettings,
        RuntimeSettings,
        save_runtime_settings,
    )

    save_runtime_settings(RuntimeSettings(dream=DreamSettings(enabled=False)))

    await scheduler.reload()
    # After reload, the loop task should be gone (disabled config = no task).
    assert scheduler._task is None


# ── Coverage gap: stop() while a fire is running waits for it ────────────────


@pytest.mark.asyncio
async def test_stop_waits_for_running_fire(_dream_md: Path):
    """``stop()``'s documented contract: it BLOCKS until the in-flight
    fire completes (shield protects synthesis from mid-run cancellation).
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    fire_started = asyncio.Event()
    fire_release = asyncio.Event()

    async def _slow_run_dream(_db) -> dict:
        fire_started.set()
        await fire_release.wait()
        return {
            "sessions_processed": 0,
            "notes_processed": 0,
            "remaining": 0,
            "failed": 0,
        }

    original_sleep = asyncio.sleep
    sleep_count = {"n": 0}

    async def _fast_first_sleep(seconds: float, *args, **kwargs):
        sleep_count["n"] += 1
        if sleep_count["n"] == 1:
            await original_sleep(0)
            return
        await original_sleep(min(seconds, 0.01))

    with patch("app.services.dream.run_dream", _slow_run_dream):
        with patch("app.services.dream_scheduler.asyncio.sleep", _fast_first_sleep):
            await scheduler.start()
            await asyncio.wait_for(fire_started.wait(), timeout=2.0)

            # stop() should NOT complete while the fire is held.
            stop_task = asyncio.create_task(scheduler.stop())
            await asyncio.sleep(0.1)
            assert not stop_task.done(), "stop() returned before fire completed"

            # Release the fire; stop should then unblock.
            fire_release.set()
            await asyncio.wait_for(stop_task, timeout=2.0)
            assert scheduler._task is None
            assert scheduler._fire_task is None


# ── Coverage gap: start() with default settings is a clean no-op ─────────────


@pytest.mark.asyncio
async def test_start_no_dream_md_does_not_spawn_task(tmp_path: Path, monkeypatch):
    """When Dream settings are absent, ``start()`` should silently leave
    ``self._task`` as None — no orphaned scheduler task hanging around.
    """
    from app.core.config import settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))

    scheduler = DreamScheduler(db_factory=_fake_db_factory())
    await scheduler.start()
    assert scheduler._task is None


@pytest.mark.asyncio
async def test_start_disabled_dream_md_does_not_spawn_task(tmp_path: Path, monkeypatch):
    """`enabled: false` in settings → start() exits without spawning."""
    from app.core.config import settings
    from app.core.runtime_settings import (
        DreamSettings,
        RuntimeSettings,
        save_runtime_settings,
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(RuntimeSettings(dream=DreamSettings(enabled=False)))

    scheduler = DreamScheduler(db_factory=_fake_db_factory())
    await scheduler.start()
    assert scheduler._task is None


# ── Coverage gap: start() with malformed settings degrades gracefully ────────


@pytest.mark.asyncio
async def test_start_malformed_dream_md_logs_and_skips(tmp_path: Path, monkeypatch):
    """Bad YAML in settings.yaml must not crash startup; the scheduler logs and
    leaves itself off so the rest of the server still boots.
    """
    from app.core.config import settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(": : malformed :\n", encoding="utf-8")
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))

    scheduler = DreamScheduler(db_factory=_fake_db_factory())
    # Must not raise.
    await scheduler.start()
    assert scheduler._task is None


# ── Coverage gap: _fire CancelledError is not swallowed ──────────────────────


# ── #3: filesystem edits to settings are picked up without a reload call ────


@pytest.mark.asyncio
async def test_loop_picks_up_filesystem_edit(_dream_md: Path):
    """Writing a new ``enabled: false`` value directly to settings (without
    going through ``PUT /api/dream/config``) must cause the running loop
    to exit on its next iteration.

    This used to require either a server restart or a ``reload()`` call —
    surprising for users who edited the file with their editor of choice.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    original_sleep = asyncio.sleep
    sleep_count = {"n": 0}

    async def _fast_sleep(seconds: float, *args, **kwargs):
        sleep_count["n"] += 1
        # Collapse first sleep (cron wait); for the second, give the test
        # time to rewrite the file before the loop wakes again.
        if sleep_count["n"] <= 1:
            await original_sleep(0)
            return
        await original_sleep(0.05)

    async def _noop_fire(_self) -> None:
        return None

    with patch.object(DreamScheduler, "_fire", _noop_fire):
        with patch("app.services.dream_scheduler.asyncio.sleep", _fast_sleep):
            await scheduler.start()
            try:
                # Wait until the loop has fired at least once.
                for _ in range(50):
                    if sleep_count["n"] >= 1:
                        break
                    await original_sleep(0.01)

                from app.core.runtime_settings import (
                    DreamSettings,
                    RuntimeSettings,
                    runtime_settings_path,
                    save_runtime_settings,
                )

                # Rewrite the file with enabled: false — this is the
                # filesystem-edit path we want the loop to honour.
                settings_path = runtime_settings_path()
                original_stat = settings_path.stat()
                save_runtime_settings(
                    RuntimeSettings(dream=DreamSettings(enabled=False))
                )
                # Metadata-only change detection is not reliable on every
                # filesystem. Preserve the original timestamps to model a
                # same-metadata atomic rewrite deterministically.
                settings_path.touch()
                import os

                os.utime(
                    settings_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )

                # The loop should exit on its own once it re-parses
                # enabled=false. Wait up to 2s.
                loop_task = scheduler._task
                assert loop_task is not None
                try:
                    await asyncio.wait_for(loop_task, timeout=2.0)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    pytest.fail("Loop did not exit after Dream was disabled on disk")
            finally:
                await scheduler.stop()


@pytest.mark.asyncio
async def test_fire_propagates_cancelled_error(_dream_md: Path):
    """``_fire`` catches Exception but MUST re-raise CancelledError so the
    loop's shield/cancel semantics work correctly.
    """
    scheduler = DreamScheduler(db_factory=_fake_db_factory())

    async def _cancel_inside(_db) -> dict:
        raise asyncio.CancelledError()

    with patch("app.services.dream.run_dream", _cancel_inside):
        with pytest.raises(asyncio.CancelledError):
            await scheduler._fire()
