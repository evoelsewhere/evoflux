"""Bounded execution lane for CPU and SQLite work owned by code-index."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import multiprocessing
import os
import threading
from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

from app.core.config import settings

_P = ParamSpec("_P")
_T = TypeVar("_T")

# Keep index work away from asyncio's shared default executor. Two workers let a
# query make progress beside one build while bounding CPU/GIL and disk pressure.
_INDEX_WORKERS = max(1, min(2, (os.cpu_count() or 2) - 1))
_INDEX_THREAD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_INDEX_WORKERS,
    thread_name_prefix="code-index",
)


class _EphemeralProcessLane:
    """One serial process queue that releases its worker when it becomes idle."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        self._pending = 0

    def submit(
        self,
        function: Callable[..., _T],
        args: tuple[object, ...],
    ) -> concurrent.futures.Future[_T]:
        with self._lock:
            if self._executor is None:
                self._executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                )
            executor = self._executor
            self._pending += 1
            try:
                future = executor.submit(function, *args)
            except BaseException:
                self._pending -= 1
                raise

        def release(_future: concurrent.futures.Future[_T]) -> None:
            retire: concurrent.futures.ProcessPoolExecutor | None = None
            with self._lock:
                if self._executor is not executor:
                    return
                self._pending -= 1
                if self._pending == 0:
                    retire = self._executor
                    self._executor = None
            if retire is not None:
                retire.shutdown(wait=False, cancel_futures=False)

        future.add_done_callback(release)
        return future

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
            self._pending = 0
        if executor is None:
            return
        processes = tuple(getattr(executor, "_processes", {}).values())
        executor.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            if process.is_alive():
                process.terminate()

    def state(self) -> tuple[int, bool]:
        with self._lock:
            return self._pending, self._executor is not None


_UPDATE_PROCESS_LANE = _EphemeralProcessLane()
_GRAPH_PROCESS_LANE = _EphemeralProcessLane()


def shutdown_index_processes() -> None:
    """Terminate rebuild/graph workers without disabling query threads."""

    _UPDATE_PROCESS_LANE.shutdown()
    _GRAPH_PROCESS_LANE.shutdown()


def index_process_queue_state() -> tuple[int, bool]:
    """Return aggregate ``(pending_jobs, worker_pool_alive)`` diagnostics."""

    update_pending, update_alive = _UPDATE_PROCESS_LANE.state()
    graph_pending, graph_alive = _GRAPH_PROCESS_LANE.state()
    return update_pending + graph_pending, update_alive or graph_alive


def _shutdown_all_index_executors() -> None:
    shutdown_index_processes()
    _INDEX_THREAD_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_all_index_executors)


def submit_index_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> concurrent.futures.Future[_T]:
    """Submit work without consuming the application's default executor."""
    return _INDEX_THREAD_EXECUTOR.submit(partial(function, *args, **kwargs))


def submit_index_update(
    thread_function: Callable[..., _T],
    thread_args: tuple[object, ...],
    *,
    process_function: Callable[..., _T],
    process_args: tuple[object, ...],
) -> concurrent.futures.Future[_T]:
    """Submit a rebuild to the configured isolated execution boundary."""

    if settings.EVOFLUX_CODE_INDEX_EXECUTION == "thread":
        return _INDEX_THREAD_EXECUTOR.submit(thread_function, *thread_args)
    return _UPDATE_PROCESS_LANE.submit(process_function, process_args)


def submit_graph_build(
    thread_function: Callable[..., _T],
    thread_args: tuple[object, ...],
    *,
    process_function: Callable[..., _T],
    process_args: tuple[object, ...],
) -> concurrent.futures.Future[_T]:
    """Submit a cold graph build outside the API process in production."""

    if settings.EVOFLUX_CODE_INDEX_EXECUTION == "thread":
        return _INDEX_THREAD_EXECUTOR.submit(thread_function, *thread_args)
    return _GRAPH_PROCESS_LANE.submit(process_function, process_args)


async def run_index_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Await bounded code-index work from any asyncio event loop."""
    future = submit_index_work(function, *args, **kwargs)
    return await asyncio.shield(asyncio.wrap_future(future))


__all__ = [
    "run_index_work",
    "index_process_queue_state",
    "shutdown_index_processes",
    "submit_index_update",
    "submit_graph_build",
    "submit_index_work",
]
