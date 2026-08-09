"""Bounded execution lane for CPU and SQLite work owned by code-index."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")

# Keep index work away from asyncio's shared default executor. Two workers let a
# query make progress beside one build while bounding CPU/GIL and disk pressure.
_INDEX_WORKERS = max(1, min(2, (os.cpu_count() or 2) - 1))
_INDEX_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_INDEX_WORKERS,
    thread_name_prefix="code-index",
)


def submit_index_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> concurrent.futures.Future[_T]:
    """Submit work without consuming the application's default executor."""
    return _INDEX_EXECUTOR.submit(partial(function, *args, **kwargs))


async def run_index_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Await bounded code-index work from any asyncio event loop."""
    future = submit_index_work(function, *args, **kwargs)
    return await asyncio.shield(asyncio.wrap_future(future))


__all__ = ["run_index_work", "submit_index_work"]
