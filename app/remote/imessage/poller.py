"""Cancellable iMessage polling with watermark and bounded backoff."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.remote.imessage.provider import IMessageProvider

MessageHandler = Callable[[dict[str, object]], Awaitable[None]]
WatermarkLoader = Callable[[], Awaitable[str | None]]
WatermarkSaver = Callable[[str], Awaitable[None]]

#: Safety bound on pages drained in one tick — guards against a provider bug
#: that reports `has_more=True` without ever advancing `next_cursor`. 25
#: pages already covers a multi-thousand-message backlog at a provider's
#: typical ~200-per-page default.
_MAX_PAGES_PER_TICK = 25


class IMessagePoller:
    def __init__(
        self,
        provider: IMessageProvider,
        *,
        on_message: MessageHandler,
        load_watermark: WatermarkLoader,
        save_watermark: WatermarkSaver,
        interval: float = 2.0,
        max_backoff: float = 60.0,
    ) -> None:
        self._provider = provider
        self._on_message = on_message
        self._load_watermark = load_watermark
        self._save_watermark = save_watermark
        self._interval = interval
        self._max_backoff = max_backoff
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._watermark: str | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._watermark = await self._load_watermark()
        await self._provider.start()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._provider.stop()

    async def _run(self) -> None:
        backoff = self._interval
        while not self._stop.is_set():
            try:
                await self._drain()
                backoff = self._interval
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    async def _drain(self) -> None:
        """Page through every message since the persisted cursor.

        Each provider owns what its cursor means and what forward-progress
        guarantee it makes (see `app/remote/imessage/provider.py`); imsg's
        exclusive `since_rowid` never re-delivers a message once its cursor
        has passed it, which is the only provider this poller is currently
        verified against.
        """
        for _ in range(_MAX_PAGES_PER_TICK):
            page = await self._provider.query_messages(since_cursor=self._watermark)
            for message in page.messages:
                await self._on_message(dict(message))
            if page.next_cursor != self._watermark:
                self._watermark = page.next_cursor
                if self._watermark is not None:
                    await self._save_watermark(self._watermark)
            elif not page.messages:
                return
            if not page.has_more:
                return
