"""Provider-capability based remote streaming strategy selection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum

from app.remote.contracts import RemoteAdapterKind

_MAX_BLOCK_LENGTH = 4096


class StreamingStrategyKind(StrEnum):
    DRAFT = "draft"
    EDIT = "edit"
    BLOCK = "block"


def chunk_text(text: str, *, limit: int = _MAX_BLOCK_LENGTH) -> list[str]:
    """Split text without breaking Unicode code points or dropping content."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return [text[index : index + limit] for index in range(0, len(text), limit)] or []


class BlockStreaming:
    """Provider-neutral bounded delivery for transports without message edits."""

    def __init__(self, send: Callable[[str], Awaitable[None]]) -> None:
        self._send = send
        self._buffer = ""
        self._finished = False

    async def append(self, delta: str) -> None:
        if self._finished:
            raise RuntimeError("stream already finished")
        self._buffer += delta
        blocks = chunk_text(self._buffer)
        while len(blocks) > 1:
            await self._send(blocks.pop(0))
        self._buffer = blocks[0] if blocks else ""

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._buffer:
            await self._send(self._buffer)
            self._buffer = ""


def select_streaming_strategy(
    *, adapter: RemoteAdapterKind | str, provider: str | None = None
) -> StreamingStrategyKind:
    adapter_kind = RemoteAdapterKind(adapter)
    if adapter_kind is RemoteAdapterKind.IMESSAGE:
        return StreamingStrategyKind.BLOCK
    if adapter_kind is RemoteAdapterKind.TELEGRAM and provider == "private_draft":
        return StreamingStrategyKind.DRAFT
    return StreamingStrategyKind.EDIT


__all__ = [
    "BlockStreaming",
    "StreamingStrategyKind",
    "chunk_text",
    "select_streaming_strategy",
]
