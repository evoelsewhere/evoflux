"""TaskScheduler — asyncio-based scheduled task engine.

Manages a set of :class:`~app.scheduler.models.ScheduledTask` rows, each
backed by a long-running ``asyncio.Task`` that sleeps until ``next_fire_at``
and then dispatches the configured prompt to the agent team.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from sqlmodel import col, select

from app.core.db import DbFactory
from app.scheduler.cron import next_fire
from app.scheduler.models import ScheduledTask

if TYPE_CHECKING:
    from app.scheduler.schemas import ScheduledTaskCreate, ScheduledTaskUpdate

_utc = timezone.utc


class TaskNotFoundError(Exception):
    """Raised when a scheduled task lookup by id has no matching row."""


class InvalidTaskTargetError(Exception):
    """Raised when a task's mode/workspace combination is invalid.

    Examples: ``mode='coding'`` with a workspace path that does not exist
    or is not a directory.
    """


class InvalidScheduleError(Exception):
    """Raised when a merged partial update would create an invalid schedule."""


def _validate_schedule_values(
    *,
    schedule_type: str,
    at_datetime: datetime | None,
    every_seconds: int | None,
    cron_expression: str | None,
    timezone_name: str,
) -> datetime | None:
    """Validate a complete schedule and normalize a naive ``at`` value."""
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise InvalidScheduleError(
            f"Unknown IANA timezone: '{timezone_name}'"
        ) from None

    if schedule_type == "at":
        if at_datetime is None:
            raise InvalidScheduleError("at_datetime is required for schedule_type='at'")
        if every_seconds is not None or cron_expression is not None:
            raise InvalidScheduleError(
                "Only at_datetime may be set for schedule_type='at'"
            )
        return (
            at_datetime.replace(tzinfo=tz)
            if at_datetime.tzinfo is None
            else at_datetime
        )

    if schedule_type == "every":
        if every_seconds is None or every_seconds <= 0:
            raise InvalidScheduleError(
                "every_seconds is required for schedule_type='every'"
            )
        if at_datetime is not None or cron_expression is not None:
            raise InvalidScheduleError(
                "Only every_seconds may be set for schedule_type='every'"
            )
        return None

    if schedule_type == "cron":
        if not cron_expression:
            raise InvalidScheduleError(
                "cron_expression is required for schedule_type='cron'"
            )
        if at_datetime is not None or every_seconds is not None:
            raise InvalidScheduleError(
                "Only cron_expression may be set for schedule_type='cron'"
            )
        from app.scheduler.cron import validate_cron

        if not validate_cron(cron_expression):
            raise InvalidScheduleError(f"Invalid cron expression: '{cron_expression}'")
        return None

    raise InvalidScheduleError(
        f"schedule_type must be 'at', 'every', or 'cron'; got '{schedule_type}'"
    )


def _validate_target(mode: str, workspace: str | None) -> None:
    """Raise :exc:`InvalidTaskTargetError` if (mode, workspace) cannot route.

    Cheap on-disk check only — no team is loaded.  Pairs with the Pydantic
    ``mode``/``workspace`` cross-field validator (which only checks
    presence) by adding the filesystem-existence check.
    """
    from app.services import team_manager

    if mode == "coding":
        if not workspace:
            raise InvalidTaskTargetError("workspace is required when mode='coding'")
        try:
            team_manager.validate_workspace(workspace)
        except ValueError as exc:
            raise InvalidTaskTargetError(str(exc)) from exc


async def _validate_session_compat(
    db_factory: DbFactory,
    *,
    session_id: str | None,
    mode: str,
    workspace: str | None,
) -> None:
    """Ensure ``session_id`` (if explicit) matches the task's (mode, workspace).

    Skipped for:

    * ``session_id is None`` — scheduler mints a new uuid per fire.
    * ``session_id == 'auto'`` — deterministic uuid5 per task; the row is
      created by the scheduler under the task's own mode/workspace, so
      mismatch is impossible by construction.
    * Explicit UUID that does not yet exist in the DB — first fire will
      create it under the task's mode/workspace.

    Raises :exc:`InvalidTaskTargetError` when an existing session row
    disagrees with the requested target.  Mirrors the workspace-mismatch
    check in ``POST /team/chat`` (``app/api/routes/team/chat.py:135-148``).
    """
    if not session_id or session_id == "auto":
        return
    try:
        sid_uuid = UUID(session_id)
    except ValueError:
        raise InvalidTaskTargetError(
            f"session_id must be a UUID or 'auto'; got {session_id!r}"
        ) from None

    # Late import — chat models import from app.core which already imports
    # scheduler indirectly, so keeping this scoped avoids a cycle.
    from app.models.chat import ChatSession

    async with db_factory() as db:
        row = await db.get(ChatSession, sid_uuid)
        if row is None:
            return  # session doesn't exist yet; first fire creates it
        if row.mode != mode:
            raise InvalidTaskTargetError(
                f"Session {session_id} has mode='{row.mode}', "
                f"but task has mode='{mode}'."
            )
        if mode == "coding" and row.workspace != workspace:
            raise InvalidTaskTargetError(
                f"Session {session_id} is bound to workspace "
                f"'{row.workspace}', but task targets '{workspace}'."
            )


class TaskScheduler:
    """Lifecycle manager for scheduled tasks.

    Instantiate once at module level and call :meth:`start` / :meth:`stop`
    from the FastAPI lifespan.
    """

    def __init__(self, db_factory: DbFactory) -> None:
        self._db = db_factory
        # task_id → running asyncio.Task
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._fire_tasks: set[asyncio.Task[None]] = set()
        self._fire_locks: dict[UUID, asyncio.Lock] = {}
        self._stopping = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Load all enabled tasks from DB and start their timer loops."""
        self._stopping = False
        tasks = await self._enabled_tasks()

        now = datetime.now(_utc)
        for task in tasks:
            if task.next_fire_at is not None and task.next_fire_at <= now:
                self._spawn_fire(
                    self._fire_overdue_and_restart(task),
                    name=f"scheduler-overdue:{task.name}",
                )
                continue

            # One-shot "at" tasks whose fire time is in the past and haven't
            # run yet should fire immediately on startup.
            if (
                task.schedule_type == "at"
                and task.at_datetime is not None
                and task.run_count == 0
                and task.at_datetime <= now
            ):
                self._spawn_fire(
                    self._fire_task(task), name=f"scheduler-fire:{task.name}"
                )
            else:
                self._start_timer(task)

        logger.info("scheduler_started tasks={}", len(tasks))

    async def _fire_overdue_and_restart(self, task: ScheduledTask) -> None:
        """Fire a persisted overdue task, then restart recurring timers."""
        await self._fire_task(task)

        async with self._db() as session:
            fresh = await session.get(ScheduledTask, task.id)

        if (
            not self._stopping
            and fresh is not None
            and fresh.enabled
            and fresh.schedule_type != "at"
        ):
            self._start_timer(fresh)

    async def has_enabled_tasks(self) -> bool:
        """Return whether the DB has any enabled scheduled tasks."""
        return bool(await self._enabled_tasks())

    async def _enabled_tasks(self) -> list[ScheduledTask]:
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(col(ScheduledTask.enabled).is_(True))
            )
            return list(result.all())

    async def stop(self) -> None:
        """Stop timers and wait for already-dispatched firings to persist."""
        self._stopping = True
        for t in list(self._tasks.values()):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self._fire_tasks:
            await asyncio.gather(*tuple(self._fire_tasks), return_exceptions=True)
        self._fire_tasks.clear()
        logger.info("scheduler_stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    async def add(self, task: ScheduledTask) -> ScheduledTask:
        """Persist *task* to DB and start its timer."""
        task.next_fire_at = next_fire(
            task.schedule_type,
            cron_expression=task.cron_expression,
            every_seconds=task.every_seconds,
            at_datetime=task.at_datetime,
            timezone=task.timezone,
            run_count=task.run_count,
        )
        async with self._db() as session:
            session.add(task)
            await session.commit()
            await session.refresh(task)

        if task.enabled:
            self._start_timer(task)
        return task

    async def create(self, body: "ScheduledTaskCreate") -> ScheduledTask:
        """Validate *body*, build a ``ScheduledTask``, persist, and start timer.

        Raises:
            InvalidTaskTargetError: If ``body.mode``/``body.workspace`` is
                not a routable target (e.g. workspace path missing), or
                if ``body.session_id`` references an existing session whose
                mode/workspace disagrees with the task.
            sqlalchemy.exc.IntegrityError: On duplicate task name.
        """
        _validate_target(body.mode, body.workspace)
        await _validate_session_compat(
            self._db,
            session_id=body.session_id,
            mode=body.mode,
            workspace=body.workspace,
        )

        task = ScheduledTask(
            name=body.name,
            mode=body.mode,
            workspace=body.workspace,
            schedule_type=body.schedule_type,
            at_datetime=body.at_datetime,
            every_seconds=body.every_seconds,
            cron_expression=body.cron_expression,
            timezone=body.timezone,
            prompt=body.prompt,
            session_id=body.session_id,
            enabled=body.enabled,
        )
        return await self.add(task)

    async def apply_update(
        self, task_id: UUID, body: "ScheduledTaskUpdate"
    ) -> ScheduledTask:
        """Apply a partial update from *body* onto an existing task.

        Re-validates the routing target if ``mode`` or ``workspace`` change.

        Raises:
            TaskNotFoundError: If *task_id* does not exist.
            InvalidTaskTargetError: If the merged (mode, workspace) is invalid.
        """
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))

        fields = body.model_fields_set
        new_mode = body.mode if "mode" in fields else task.mode
        if new_mode is None:
            raise InvalidTaskTargetError("mode cannot be null")
        new_workspace = body.workspace if "workspace" in fields else task.workspace
        # Switching a coding task back to work mode should not retain a stale
        # workspace merely because the client omitted the now-irrelevant field.
        if body.mode == "work" and "workspace" not in fields:
            new_workspace = None
        new_session_id = body.session_id if "session_id" in fields else task.session_id
        if "mode" in fields or "workspace" in fields:
            _validate_target(new_mode, new_workspace)

        # Re-validate the session pairing whenever any of (mode, workspace,
        # session_id) change.  A mode-only change can newly conflict with an
        # already-stored session_id, so we always check against the merged
        # state.
        if "mode" in fields or "workspace" in fields or "session_id" in fields:
            await _validate_session_compat(
                self._db,
                session_id=new_session_id,
                mode=new_mode,
                workspace=new_workspace,
            )

        schedule_type = (
            body.schedule_type if "schedule_type" in fields else task.schedule_type
        )
        if schedule_type is None:
            raise InvalidScheduleError("schedule_type cannot be null")
        schedule_type_changed = schedule_type != task.schedule_type
        if schedule_type_changed:
            # A type transition starts with a clean shape; values belonging to
            # the old type must never leak into the persisted new schedule.
            at_datetime = body.at_datetime if "at_datetime" in fields else None
            every_seconds = body.every_seconds if "every_seconds" in fields else None
            cron_expression = (
                body.cron_expression if "cron_expression" in fields else None
            )
        else:
            at_datetime = (
                body.at_datetime if "at_datetime" in fields else task.at_datetime
            )
            every_seconds = (
                body.every_seconds if "every_seconds" in fields else task.every_seconds
            )
            cron_expression = (
                body.cron_expression
                if "cron_expression" in fields
                else task.cron_expression
            )
        timezone_name = body.timezone if "timezone" in fields else task.timezone
        if timezone_name is None:
            raise InvalidScheduleError("timezone cannot be null")
        at_datetime = _validate_schedule_values(
            schedule_type=schedule_type,
            at_datetime=at_datetime,
            every_seconds=every_seconds,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
        )
        schedule_definition_changed = bool(
            fields
            & {
                "schedule_type",
                "at_datetime",
                "every_seconds",
                "cron_expression",
                "timezone",
            }
        )

        task.mode = new_mode
        task.workspace = new_workspace
        task.schedule_type = schedule_type
        task.at_datetime = at_datetime
        task.every_seconds = every_seconds
        task.cron_expression = cron_expression
        task.timezone = timezone_name
        if body.prompt is not None:
            task.prompt = body.prompt
        if "session_id" in fields:
            task.session_id = body.session_id
        if body.enabled is not None:
            task.enabled = body.enabled
            task.status = "pending" if body.enabled else "paused"
        elif schedule_definition_changed and task.enabled:
            task.status = "pending"

        return await self.update(
            task,
            reset_one_shot=(schedule_type == "at" and schedule_definition_changed),
        )

    async def remove(self, task_id: UUID) -> None:
        """Cancel timer and delete *task_id* from DB."""
        self._cancel_timer(task_id)
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.first()
            if task is not None:
                await session.delete(task)
                await session.commit()

    async def update(
        self, task: ScheduledTask, *, reset_one_shot: bool = False
    ) -> ScheduledTask:
        """Persist updated *task* and restart/cancel its timer."""
        self._cancel_timer(task.id)
        task.next_fire_at = next_fire(
            task.schedule_type,
            cron_expression=task.cron_expression,
            every_seconds=task.every_seconds,
            at_datetime=task.at_datetime,
            timezone=task.timezone,
            # run_count is cumulative history, but a newly defined one-shot
            # must still get one future fire even if this task ran before.
            run_count=0 if reset_one_shot else task.run_count,
        )
        async with self._db() as session:
            session.add(task)
            await session.commit()
            await session.refresh(task)

        if task.enabled:
            self._start_timer(task)
        return task

    async def pause(self, task_id: UUID) -> ScheduledTask:
        """Disable task and cancel its timer."""
        self._cancel_timer(task_id)
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.one()
            task.enabled = False
            task.status = "paused"
            session.add(task)
            await session.commit()
            await session.refresh(task)
        return task

    async def resume(self, task_id: UUID) -> ScheduledTask:
        """Re-enable task, recompute next_fire_at, and start timer."""
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.one()
            task.enabled = True
            task.status = "pending"
            if task.schedule_type != "at" or task.next_fire_at is None:
                task.next_fire_at = next_fire(
                    task.schedule_type,
                    cron_expression=task.cron_expression,
                    every_seconds=task.every_seconds,
                    at_datetime=task.at_datetime,
                    timezone=task.timezone,
                    run_count=task.run_count,
                )
            session.add(task)
            await session.commit()
            await session.refresh(task)

        self._start_timer(task)
        return task

    async def trigger(self, task_id: UUID) -> None:
        """Fire task immediately and ensure it is enabled."""
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.one()
            was_disabled = not task.enabled or task.status == "paused"
            if was_disabled:
                task.enabled = True
                task.status = "pending"
                task.next_fire_at = next_fire(
                    task.schedule_type,
                    cron_expression=task.cron_expression,
                    every_seconds=task.every_seconds,
                    at_datetime=task.at_datetime,
                    timezone=task.timezone,
                    run_count=task.run_count,
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)

        # Stop the timer before dispatching. Otherwise a one-shot whose due
        # time arrives during a manual trigger can execute twice concurrently.
        # Recurring timers are restored after the manual firing, preserving
        # their previously persisted next-fire time.
        self._cancel_timer(task.id)
        self._spawn_fire(
            self._trigger_and_restart(task), name=f"scheduler-trigger:{task.name}"
        )

    async def list_tasks(self, session_id: str | None = None) -> list[ScheduledTask]:
        async with self._db() as session:
            stmt = select(ScheduledTask)
            if session_id is not None:
                stmt = stmt.where(ScheduledTask.session_id == session_id)
            result = await session.exec(stmt)
            return list(result.all())

    async def get_task(self, task_id: UUID) -> ScheduledTask | None:
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            return result.first()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _start_timer(self, task: ScheduledTask) -> None:
        """Spawn an asyncio task for *task*'s timer loop."""
        if self._stopping:
            return
        self._cancel_timer(task.id)
        t = asyncio.create_task(self._timer_loop(task), name=f"scheduler:{task.name}")
        self._tasks[task.id] = t

    def _spawn_fire(
        self, coroutine: Coroutine[Any, Any, None], *, name: str
    ) -> asyncio.Task[None]:
        """Track non-timer firings so shutdown cannot leave rows ``running``."""
        task = asyncio.create_task(coroutine, name=name)
        self._fire_tasks.add(task)
        task.add_done_callback(self._fire_tasks.discard)
        return task

    def _cancel_timer(self, task_id: UUID) -> None:
        existing = self._tasks.pop(task_id, None)
        if existing is not None:
            existing.cancel()

    async def _timer_loop(self, task: ScheduledTask) -> None:
        """Sleep until next_fire_at, fire, repeat (or exit for one-shots)."""
        nxt = task.next_fire_at
        while True:
            if nxt is None:
                nxt = next_fire(
                    task.schedule_type,
                    cron_expression=task.cron_expression,
                    every_seconds=task.every_seconds,
                    at_datetime=task.at_datetime,
                    timezone=task.timezone,
                    run_count=task.run_count,
                )
            if nxt is None:
                # Schedule exhausted (e.g. "at" already ran)
                break

            now = datetime.now(_utc)
            delay = (nxt - now).total_seconds()
            if delay > 0:
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return

            # Keep dispatch alive if pause/update/delete cancels this timer
            # after it has already fired. The independently tracked task will
            # finish its DB bookkeeping and is awaited during shutdown.
            fire = self._spawn_fire(
                self._fire_task(task), name=f"scheduler-fire:{task.name}"
            )
            try:
                await asyncio.shield(fire)
            except asyncio.CancelledError:
                return

            # Reload task state from DB so run_count / status are fresh
            async with self._db() as session:
                result = await session.exec(
                    select(ScheduledTask).where(ScheduledTask.id == task.id)
                )
                fresh = result.first()
            if fresh is None:
                break
            task = fresh
            nxt = task.next_fire_at

            # One-shot "at" tasks exit after firing
            if task.schedule_type == "at":
                break

        # Remove ourselves from the tracking dict
        self._tasks.pop(task.id, None)

    async def _trigger_and_restart(self, task: ScheduledTask) -> None:
        """Run a manual trigger and restore recurring timer state."""
        preserved_next = task.next_fire_at
        await self._fire_task(
            task,
            manual=True,
            preserved_next_fire_at=preserved_next,
        )
        async with self._db() as session:
            fresh = await session.get(ScheduledTask, task.id)
        if (
            not self._stopping
            and fresh is not None
            and fresh.enabled
            and fresh.schedule_type != "at"
        ):
            self._start_timer(fresh)

    async def _project_extra_paths(
        self, session_id: str | None, primary_workspace: str
    ) -> list[str] | None:
        """Return a project session's non-primary repo paths, or ``None``.

        Best-effort: only resolves when the session row already exists and
        carries a ``project_id``. On the very first firing of a fresh project
        session the row may not exist yet, so multi-repo context attaches from
        the next run onward. Mirrors the derivation in POST /team/chat.
        """
        if not session_id:
            return None
        try:
            sid_uuid = UUID(session_id)
        except ValueError:
            return None

        from app.models.chat import ChatSession
        from app.services.coding_project_service import get_project_workspace_paths

        async with self._db() as db:
            row = await db.get(ChatSession, sid_uuid)
            if row is None or row.project_id is None:
                return None
            all_paths = await get_project_workspace_paths(db, row.project_id)
        extras = [p for p in all_paths if p != primary_workspace]
        return extras or None

    async def _fire_task(
        self,
        task: ScheduledTask,
        *,
        manual: bool = False,
        preserved_next_fire_at: datetime | None = None,
    ) -> None:
        """Execute one firing, serialized per scheduled task."""
        lock = self._fire_locks.setdefault(task.id, asyncio.Lock())
        async with lock:
            await self._fire_task_locked(
                task,
                manual=manual,
                preserved_next_fire_at=preserved_next_fire_at,
            )

    async def _fire_task_locked(
        self,
        task: ScheduledTask,
        *,
        manual: bool,
        preserved_next_fire_at: datetime | None,
    ) -> None:
        """Execute one scheduled firing while holding its per-task lock."""
        from app.services import team_manager
        from app.services.agent_service import NoTeamConfigured, dispatch_user_message

        now = datetime.now(_utc)

        # 1. Mark running
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task.id)
            )
            db_task = result.first()
            if db_task is None:
                return
            db_task.status = "running"
            db_task.last_run_at = now
            session.add(db_task)
            await session.commit()
            await session.refresh(db_task)
            # Always dispatch the latest persisted prompt/target rather than
            # a stale object captured by a timer before an API update.
            task = db_task
            fired_schedule = (
                task.schedule_type,
                task.at_datetime,
                task.every_seconds,
                task.cron_expression,
                task.timezone,
            )

        # 2. Resolve session_id
        # "auto" → deterministic uuid5 derived from the task name so the same
        # persistent session is reused across every firing, and it is always a
        # valid UUID (required by handle_user_message / ChatSession PK).
        raw_sid = task.session_id
        if raw_sid is None:
            resolved_sid: str | None = None  # dispatch_user_message will mint one
        elif raw_sid == "auto":
            resolved_sid = str(uuid5(NAMESPACE_URL, f"scheduler:{task.name}"))
        else:
            resolved_sid = raw_sid

        # 3. Dispatch — route to the lead of the matching team.
        error: str | None = None
        fired_sid: str | None = None
        try:
            if task.mode == "coding":
                if not task.workspace:
                    raise NoTeamConfigured(
                        "Task has mode='coding' but no workspace configured."
                    )
                # If this scheduled session belongs to a multi-repo project,
                # pass the project's other repos so the agent gets full
                # multi-repo context (installs MultiRepoContextHook), mirroring
                # POST /team/chat.
                extra_ws_paths = await self._project_extra_paths(
                    resolved_sid, task.workspace
                )
                team = await team_manager.get_or_start_coding_team(
                    task.workspace,
                    f"scheduler:{task.id}",
                    extra_workspace_paths=extra_ws_paths,
                )
            else:
                team = await team_manager.get_or_start_team()
                if team is None:
                    raise NoTeamConfigured("No team configured.")
            fired_sid, _ = await dispatch_user_message(
                team,
                content=f"[Scheduled Task: {task.name}]\n{task.prompt}",
                session_id=resolved_sid,
                mode=task.mode,
                workspace=task.workspace,
            )
        except NoTeamConfigured as exc:
            error = str(exc)
            logger.warning(
                "scheduler_no_team task_id={} name={} mode={} error={}",
                task.id,
                task.name,
                task.mode,
                exc,
            )
        except Exception as exc:
            error = str(exc)
            logger.error(
                "scheduler_fire_error task_id={} name={} error={}",
                task.id,
                task.name,
                exc,
            )

        # 3b. Stamp the chat session so it's identifiable as scheduler-created.
        # fired_sid is always a valid UUID string at this point:
        #   None     → dispatch_user_message mints a uuid7
        #   "auto"   → resolved to uuid5(NAMESPACE_URL, "scheduler:<name>") above
        #   explicit → caller-supplied UUID string passed through unchanged
        if fired_sid and not error:
            from app.models.chat import ChatSession

            try:
                async with self._db() as db:
                    chat_row = await db.get(ChatSession, UUID(fired_sid))
                    if chat_row is not None:
                        chat_row.scheduled_task_name = task.name
                        db.add(chat_row)
                        await db.commit()
            except Exception as stamp_exc:
                logger.warning(
                    "scheduler_stamp_failed task_id={} sid={} error={}",
                    task.id,
                    fired_sid,
                    stamp_exc,
                )

        # 4. Update stats
        async with self._db() as session:
            result = await session.exec(
                select(ScheduledTask).where(ScheduledTask.id == task.id)
            )
            db_task = result.first()
            if db_task is None:
                return
            db_task.run_count += 1
            db_task.last_error = error
            current_schedule = (
                db_task.schedule_type,
                db_task.at_datetime,
                db_task.every_seconds,
                db_task.cron_expression,
                db_task.timezone,
            )
            if current_schedule == fired_schedule:
                if manual and db_task.schedule_type != "at":
                    db_task.next_fire_at = preserved_next_fire_at
                else:
                    db_task.next_fire_at = next_fire(
                        db_task.schedule_type,
                        cron_expression=db_task.cron_expression,
                        every_seconds=db_task.every_seconds,
                        at_datetime=db_task.at_datetime,
                        timezone=db_task.timezone,
                        after=datetime.now(_utc),
                        run_count=db_task.run_count,
                    )
            # If the schedule was edited while dispatch was in flight, keep
            # update()'s newly persisted next_fire_at instead of overwriting
            # it with a calculation for the old firing.
            if not db_task.enabled:
                db_task.status = "paused"
            elif error:
                db_task.status = "failed"
            elif db_task.schedule_type == "at":
                db_task.status = "completed"
            else:
                db_task.status = "pending"
            session.add(db_task)
            await session.commit()

        logger.info(
            "scheduler_fired task_id={} name={} run_count={} error={}",
            task.id,
            task.name,
            task.run_count + 1,
            error,
        )


# ── Module-level singleton ────────────────────────────────────────────────────

from app.core.db import async_session_factory  # noqa: E402

task_scheduler = TaskScheduler(db_factory=async_session_factory)
