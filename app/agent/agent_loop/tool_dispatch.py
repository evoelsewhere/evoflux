"""Parallel tool dispatch with mid-flight interrupt support.

``Agent.run`` schedules every tool call for an iteration as a coroutine
and hands the bundle to :func:`gather_or_cancel`.  If no interrupt
event is supplied (or it never fires) this behaves exactly like
``asyncio.gather(..., return_exceptions=True)``.

When the interrupt fires mid-execution:

1. All still-pending tasks are cancelled.
2. Already-completed tasks keep their real results.
3. Cancelled tasks are reported as ``(tc, "Cancelled by user.")``
   so the caller can post a stub :class:`ToolMessage` and exit the
   loop cleanly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall


async def gather_or_cancel(
    coros: list,
    interrupt_event: asyncio.Event | None,
    tc_list: list[ToolCall],
    agent_name: str,
    *,
    timeout: float | None = 300.0,
) -> list[tuple[ToolCall, str] | BaseException]:
    """Run *coros* in parallel; cancel unfinished ones on interrupt or timeout.

    Results preserve the order of *tc_list*.

    Args:
        timeout: Per-batch wall-clock timeout in seconds. ``None`` means no
            limit. Default is 300s (5 min) — generous enough for long-running
            tools but prevents indefinite hangs that block team sessions.
    """
    if not coros:
        return []

    tasks = [asyncio.ensure_future(c) for c in coros]

    if interrupt_event is None:
        # No interrupt possible — plain gather behaviour with timeout
        try:
            if timeout is not None:
                return await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
            return await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.TimeoutError:
            for t in tasks:
                if not t.done():
                    t.cancel()
            if tasks:
                await asyncio.wait(tasks)
            results: list[tuple[ToolCall, str] | BaseException] = []
            for task, tc in zip(tasks, tc_list):
                if task.cancelled():
                    results.append(
                        (tc, f"Tool timed out after {timeout:.0f}s and was cancelled.")
                    )
                    logger.warning(
                        "tool_timeout agent={} tool={} timeout={}s",
                        agent_name,
                        tc.function.name,
                        timeout,
                    )
                elif task.exception() is not None:
                    results.append(task.exception())  # type: ignore[arg-type]
                else:
                    results.append(task.result())
            return results

    # Create a waiter that fires when the interrupt event is set
    interrupt_waiter = asyncio.ensure_future(interrupt_event.wait())

    # Create a timeout waiter if configured
    deadline_task: asyncio.Future | None = None
    if timeout is not None:
        deadline_task = asyncio.ensure_future(asyncio.sleep(timeout))

    timed_out = False

    try:
        # Wait until either all tool tasks finish or the interrupt fires
        tool_set = set(tasks)
        done: set[asyncio.Future] = set()
        pending = tool_set.copy()

        while pending:
            # Wait for the first completed item among pending tools + interrupt + timeout
            wait_set = pending | {interrupt_waiter}
            if deadline_task is not None:
                wait_set = wait_set | {deadline_task}
            newly_done, _ = await asyncio.wait(
                wait_set, return_when=asyncio.FIRST_COMPLETED
            )
            done |= newly_done & tool_set
            pending = tool_set - done

            if interrupt_waiter in newly_done:
                # Interrupt fired — cancel remaining tool tasks
                for t in pending:
                    t.cancel()
                # Wait for cancellation to propagate
                if pending:
                    await asyncio.wait(pending)
                break

            if deadline_task is not None and deadline_task in newly_done:
                # Timeout — cancel remaining tool tasks
                timed_out = True
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.wait(pending)
                break
    finally:
        interrupt_waiter.cancel()
        if deadline_task is not None:
            deadline_task.cancel()
        # Suppress the CancelledError from the waiters
        try:
            await interrupt_waiter
        except (asyncio.CancelledError, Exception):
            pass
        if deadline_task is not None:
            try:
                await deadline_task
            except (asyncio.CancelledError, Exception):
                pass

    # Build results — preserve order matching tc_list
    results: list[tuple[ToolCall, str] | BaseException] = []
    for task, tc in zip(tasks, tc_list):
        if task.cancelled():
            if timed_out:
                results.append(
                    (tc, f"Tool timed out after {timeout:.0f}s and was cancelled.")
                )
                logger.warning(
                    "tool_timeout agent={} tool={} timeout={}s",
                    agent_name,
                    tc.function.name,
                    timeout,
                )
            else:
                results.append((tc, "Cancelled by user."))
                logger.info(
                    "tool_cancelled agent={} tool={}",
                    agent_name,
                    tc.function.name,
                )
        elif task.exception() is not None:
            results.append(task.exception())  # type: ignore[arg-type]
        else:
            results.append(task.result())
    return results


async def run_serially(
    coros: list,
    interrupt_event: asyncio.Event | None,
    tc_list: list["ToolCall"],
    agent_name: str,
    *,
    timeout: float | None = 300.0,
) -> list:
    """Run *coros* one at a time with interrupt and timeout support.

    Mirrors the cancellation semantics of :func:`gather_or_cancel` but
    executes tools sequentially.  For each tool:

    - If the interrupt event is already set before starting → append
      ``(tc, "Cancelled by user.")`` immediately.
    - If the interrupt fires *while* the tool is running → cancel the
      active task, append the cancellation result, then mark all
      remaining tools as cancelled too.
    - On timeout → same as interrupt but with a timeout message.

    Returns a list with the same shape as :func:`gather_or_cancel`.
    """
    results: list = []

    for idx, (coro, tc) in enumerate(zip(coros, tc_list)):
        # Pre-start interrupt check
        if interrupt_event is not None and interrupt_event.is_set():
            logger.info(
                "tool_serial_cancelled_before_start agent={} tool={}",
                agent_name,
                tc.function.name,
            )
            results.append((tc, "Cancelled by user."))
            continue

        task: asyncio.Task = asyncio.ensure_future(coro)

        # Fast-path: no interrupt monitoring needed
        if interrupt_event is None and timeout is None:
            try:
                results.append(await task)
            except BaseException as exc:  # noqa: BLE001
                results.append(exc)
            continue

        # Monitor task alongside interrupt + deadline waiters
        interrupt_waiter: asyncio.Future | None = None
        deadline_task: asyncio.Future | None = None
        timed_out = False

        if interrupt_event is not None:
            interrupt_waiter = asyncio.ensure_future(interrupt_event.wait())
        if timeout is not None:
            deadline_task = asyncio.ensure_future(asyncio.sleep(timeout))

        wait_set = {task}
        if interrupt_waiter is not None:
            wait_set.add(interrupt_waiter)
        if deadline_task is not None:
            wait_set.add(deadline_task)

        try:
            done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)

            interrupted = (
                interrupt_waiter is not None
                and interrupt_waiter in done
                and task not in done
            )
            timed_out = (
                deadline_task is not None and deadline_task in done and task not in done
            )

            if interrupted or timed_out:
                task.cancel()
                await asyncio.wait({task})
                if timed_out:
                    msg = f"Tool timed out after {timeout:.0f}s and was cancelled."
                    logger.warning(
                        "tool_timeout agent={} tool={} timeout={}s",
                        agent_name,
                        tc.function.name,
                        timeout,
                    )
                else:
                    msg = "Cancelled by user."
                    logger.info(
                        "tool_serial_cancelled agent={} tool={}",
                        agent_name,
                        tc.function.name,
                    )
                results.append((tc, msg))
            elif task.cancelled():
                results.append((tc, "Cancelled by user."))
            elif task.exception() is not None:
                results.append(task.exception())  # type: ignore[arg-type]
            else:
                results.append(task.result())
        finally:
            if interrupt_waiter is not None:
                interrupt_waiter.cancel()
                try:
                    await interrupt_waiter
                except (asyncio.CancelledError, Exception):
                    pass
            if deadline_task is not None:
                deadline_task.cancel()
                try:
                    await deadline_task
                except (asyncio.CancelledError, Exception):
                    pass

        # After the tool, if interrupted or timed out, cancel the rest
        if (interrupt_event is not None and interrupt_event.is_set()) or timed_out:
            for remaining_tc in tc_list[idx + 1 :]:
                results.append((remaining_tc, "Cancelled by user."))
            break

    return results
