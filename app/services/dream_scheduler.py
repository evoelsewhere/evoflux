"""Dream scheduler — runs dream on a cron schedule.

Reads schedule from ``settings.yaml`` via :func:`app.services.dream.load_dream_config`.
Only starts if Dream has ``enabled: true``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from croniter import croniter
from loguru import logger


if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.db import DbFactory


# Strong-ref holder for orphaned scheduler loop / fire tasks during reload.
# CPython only weak-refs ``asyncio.Task`` objects, so without this set a
# rapid GC could collect a still-running fire mid-synthesis.  Tasks remove
# themselves via ``add_done_callback(_orphan_tasks.discard)``.
_orphan_tasks: set[asyncio.Task] = set()


class DreamScheduler:
    """Background scheduler that runs dream on a cron schedule."""

    def __init__(self, db_factory: "DbFactory") -> None:
        self._db_factory = db_factory
        self._task: asyncio.Task | None = None
        # Tracks the in-flight ``_fire()`` (if any) so ``reload()`` can detect
        # whether cancelling the loop task would block on a long-running dream
        # synthesis.  When that's the case we *don't* await the loop — we
        # just orphan it and let the shielded fire complete in the background
        # while a fresh scheduler task takes over.
        self._fire_task: asyncio.Task | None = None
        # Serialises ``start`` / ``stop`` / ``reload`` so two concurrent
        # ``PUT /api/dream/config`` requests can't both pass the suspension
        # point at ``await old_loop`` and each spawn a fresh scheduler task,
        # leaking the first one (race S3).
        self._lifecycle_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background scheduler task if Dream is enabled.

        Idempotent: a second call while already running is a no-op.  Without
        this guard a buggy caller could overwrite ``self._task`` and leak
        the previously running scheduler task.
        """
        async with self._lifecycle_lock:
            await self._start_unlocked()

    async def _start_unlocked(self) -> None:
        """Internal start that assumes ``_lifecycle_lock`` is held."""
        from app.services.dream import load_dream_config

        if self._task is not None and not self._task.done():
            logger.debug("dream_scheduler_start_skip already_running=true")
            return

        try:
            cfg = await asyncio.to_thread(load_dream_config)
        except ValueError as exc:
            logger.warning("dream_scheduler_config_error error={}", exc)
            return

        if not cfg.enabled:
            logger.debug("dream_scheduler_disabled enabled=false")
            return

        logger.info(
            "dream_scheduler_starting schedule={} model={}",
            cfg.schedule,
            cfg.model or "(none — infra-only)",
        )
        self._task = asyncio.create_task(
            self._loop(cfg.schedule), name="dream-scheduler"
        )

    async def stop(self) -> None:
        """Stop the scheduler, cancelling any pending sleep but not a running fire.

        If a ``_fire()`` is in progress, this still blocks until it completes
        because the loop's shield protects the fire from cancellation — that
        is the documented contract.  Use ``reload()`` for the non-blocking
        path.

        Implementation note: cancelling ``self._task`` only unblocks the
        loop's ``await asyncio.shield(fire_task)``; the shielded fire
        survives and continues in the background.  To honour the docstring
        we must also await the fire task itself before returning.
        """
        async with self._lifecycle_lock:
            loop_task = self._task
            fire_task = self._fire_task
            if loop_task is not None and not loop_task.done():
                loop_task.cancel()
                try:
                    await loop_task
                except asyncio.CancelledError:
                    pass
            if fire_task is not None and not fire_task.done():
                # Shield protects the fire from our cancellation; wait for
                # the synthesis to finish so callers can rely on a clean
                # post-stop state.  Swallow any error — _fire() already
                # logged it with logger.exception.
                try:
                    await fire_task
                except (asyncio.CancelledError, Exception):
                    pass
            if loop_task is not None or fire_task is not None:
                logger.info("dream_scheduler_stopped")
            self._task = None
            self._fire_task = None

    async def reload(self) -> None:
        """Reload the scheduler from the current settings without interrupting
        an in-progress dream run **and** without blocking on it.

        Behaviour:

        - If the loop is sleeping → cancel + await briefly (returns instantly).
        - If a ``_fire()`` is currently running → cancel the loop task but
          DO NOT await it.  The shielded fire continues to completion in the
          background; a fresh scheduler task takes over immediately.  The
          orphan loop exits cleanly once its shielded fire returns (it sees
          ``cancelled=True`` and re-raises ``CancelledError``).

        Serialised by ``_lifecycle_lock`` so concurrent
        ``PUT /api/dream/config`` requests can't both create fresh scheduler
        tasks and leak the loser.

        Called by ``PUT /api/dream/config`` so schedule / enabled changes take
        effect immediately without a server restart and without the HTTP
        request hanging for ``timeout_seconds * batch_size`` minutes.
        """
        async with self._lifecycle_lock:
            # Snapshot + detach references so the loop's ``finally`` clause
            # can't see a half-nilled state (S2): clear ``self._fire_task``
            # only AFTER we've decided what to do with it.
            old_loop = self._task
            old_fire = self._fire_task
            fire_in_progress = old_fire is not None and not old_fire.done()

            if old_loop is not None and not old_loop.done():
                old_loop.cancel()
                if not fire_in_progress:
                    # Safe to await — the loop is sleeping and will exit
                    # immediately after cancellation propagates.
                    try:
                        await old_loop
                    except asyncio.CancelledError:
                        pass
                    logger.info("dream_scheduler_stopped_for_reload")
                else:
                    # A fire is running.  Orphan the old loop; it will tear
                    # itself down once the shielded fire completes.  We must
                    # NOT await it here because that would block for up to
                    # ``timeout_seconds * batch_size`` minutes — defeating
                    # the point of a live reload.  Stash the orphan in a
                    # module-level set so it isn't garbage-collected before
                    # completion (CPython holds tasks via weak refs).
                    _orphan_tasks.add(old_loop)
                    old_loop.add_done_callback(_orphan_tasks.discard)
                    if old_fire is not None:
                        _orphan_tasks.add(old_fire)
                        old_fire.add_done_callback(_orphan_tasks.discard)
                    logger.info(
                        "dream_scheduler_reload_during_fire orphaned_old_loop=true"
                    )

            # Now detach (after orphaning so the old loop's finally doesn't
            # race with us on ``self._fire_task``).
            self._task = None
            self._fire_task = None
            await self._start_unlocked()
            logger.info("dream_scheduler_reloaded")

    async def run_now(self, db: "AsyncSession") -> dict:
        """Run dream immediately (for /api/dream/run)."""
        from app.services.dream import run_dream

        return await run_dream(db)

    async def _loop(self, schedule: str) -> None:
        """Main scheduler loop — sleeps until next cron fire time.

        The sleep is cancellable (so ``reload()`` / ``stop()`` take effect
        quickly), but an active ``_fire()`` call is shielded from cancellation
        so a running dream synthesis is never cut short.  If cancellation
        arrives while firing, the CancelledError is re-raised after the fire
        completes.

        On each iteration, the loop re-reads the small runtime settings file.
        This avoids missing atomic rewrites on filesystems whose timestamp
        metadata did not change, while still applying filesystem edits (e.g.
        via ``$EDITOR`` or ``manual.wiki``) without a server restart or a
        ``PUT /api/dream/config`` call. If Dream is disabled, the loop exits
        cleanly.
        """
        while True:
            try:
                new_schedule, still_enabled = await self._reparse_schedule()
                if not still_enabled:
                    logger.info("dream_scheduler_disabled_via_file_edit exiting=true")
                    return
                if new_schedule is not None and new_schedule != schedule:
                    logger.info(
                        "dream_scheduler_schedule_changed old={} new={}",
                        schedule,
                        new_schedule,
                    )
                    schedule = new_schedule

                now = datetime.now(timezone.utc)
                cron = croniter(schedule, now)
                next_fire: datetime = cron.get_next(datetime)
                sleep_seconds = (next_fire - now).total_seconds()
                logger.info(
                    "dream_scheduler_next_fire at={} sleep_seconds={:.0f}",
                    next_fire.isoformat(),
                    sleep_seconds,
                )
                await asyncio.sleep(max(sleep_seconds, 0))
            except asyncio.CancelledError:
                # Cancelled during sleep — exit cleanly without firing.
                raise

            # Fire is shielded: cancellation arriving here waits until the
            # dream run finishes, then re-raises so the loop exits.
            # ``_fire_task`` is exposed on self so ``reload()`` can detect
            # whether a fire is in progress and orphan us non-blockingly.
            cancelled = False
            fire_task = asyncio.create_task(self._fire(), name="dream-scheduler-fire")
            # Keep a local reference too — ``reload()`` may nil ``self._fire_task``
            # while we're awaiting the shield, so we cannot rely on
            # ``self._fire_task`` still being this task in the finally block (S2).
            self._fire_task = fire_task
            try:
                await asyncio.shield(fire_task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception as exc:
                logger.error("dream_scheduler_loop_error error={}", exc)
                await asyncio.sleep(60)
            finally:
                # Only clear ``self._fire_task`` if it's still pointing at
                # *our* task — ``reload()`` may have already detached it
                # and orphaned us.
                if self._fire_task is fire_task and fire_task.done():
                    self._fire_task = None

            if cancelled:
                raise asyncio.CancelledError

    async def _reparse_schedule(self) -> tuple[str | None, bool]:
        """Reparse settings to pick up a filesystem edit.

        Returns ``(new_schedule, still_enabled)``.  On parse failure the
        previous schedule is kept by returning ``(None, True)`` so a
        transient broken edit doesn't kill the loop.  The caller treats
        ``still_enabled=False`` as "exit loop".
        """
        from app.services.dream import load_dream_config

        try:
            cfg = await asyncio.to_thread(load_dream_config)
        except ValueError as exc:
            logger.warning(
                "dream_scheduler_reparse_failed error={} keeping_previous_schedule=true",
                exc,
            )
            return None, True

        return cfg.schedule, cfg.enabled

    async def _fire(self) -> None:
        """Execute one dream run.

        Exceptions are caught + logged with full traceback (via
        ``logger.exception``) so a buggy ``run_dream`` doesn't silently
        keep firing every minute hiding the root cause.  ``CancelledError``
        is NOT caught — it propagates to ``_loop``'s ``shield`` and unwinds
        the scheduler cleanly.
        """
        logger.info("dream_scheduler_firing")
        try:
            async with self._db_factory() as db:
                from app.services.dream import run_dream

                result = await run_dream(db)
                logger.info("dream_scheduler_fired result={}", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dream_scheduler_fire_failed")
