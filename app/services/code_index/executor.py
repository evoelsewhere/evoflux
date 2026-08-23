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
_INDEX_PROCESS_EXECUTOR: concurrent.futures.ProcessPoolExecutor | None = None
_INDEX_PROCESS_LOCK = threading.Lock()


def _process_executor() -> concurrent.futures.ProcessPoolExecutor:
    global _INDEX_PROCESS_EXECUTOR
    with _INDEX_PROCESS_LOCK:
        if _INDEX_PROCESS_EXECUTOR is None:
            _INDEX_PROCESS_EXECUTOR = concurrent.futures.ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return _INDEX_PROCESS_EXECUTOR


def shutdown_index_processes() -> None:
    """Terminate rebuild workers without disabling lightweight query threads."""

    global _INDEX_PROCESS_EXECUTOR
    with _INDEX_PROCESS_LOCK:
        process_executor = _INDEX_PROCESS_EXECUTOR
        _INDEX_PROCESS_EXECUTOR = None
    if process_executor is not None:
        processes = tuple(getattr(process_executor, "_processes", {}).values())
        process_executor.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            if process.is_alive():
                process.terminate()


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
    return _process_executor().submit(process_function, *process_args)


async def run_index_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Await bounded code-index work from any asyncio event loop."""
    future = submit_index_work(function, *args, **kwargs)
    return await asyncio.shield(asyncio.wrap_future(future))


__all__ = [
    "run_index_work",
    "shutdown_index_processes",
    "submit_index_update",
    "submit_index_work",
]
