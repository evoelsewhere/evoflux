"""Cancellable iMessage polling with watermark and bounded backoff."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.remote.imessage.provider import IMessageProvider

MessageHandler = Callable[[dict[str, object]], Awaitable[None]]
WatermarkLoader = Callable[[], Awaitable[str | None]]
WatermarkSaver = Callable[[str], Awaitable[None]]


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
        self._seen: set[str] = set()

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
                messages = await self._provider.query_messages(after=self._watermark)
                for message in messages:
                    source_key = message.get("guid") or message.get("id")
                    if (
                        not isinstance(source_key, str)
                        or source_key <= (self._watermark or "")
                        or source_key in self._seen
                    ):
                        continue
                    self._seen.add(source_key)
                    await self._on_message(dict(message))
                    self._watermark = source_key
                    await self._save_watermark(source_key)
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
