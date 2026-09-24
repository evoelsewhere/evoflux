from __future__ import annotations

import pytest

from app.remote.imessage.streaming import BlockStreaming, chunk_text


def test_chunk_text_preserves_unicode_and_bounds() -> None:
    text = "🙂" * 4097
    blocks = chunk_text(text)
    assert [len(block) for block in blocks] == [4096, 1]
    assert "".join(blocks) == text


@pytest.mark.asyncio
async def test_block_streaming_flushes_full_blocks_and_final_once() -> None:
    sent: list[str] = []

    async def send(block: str) -> None:
        sent.append(block)

    stream = BlockStreaming(send)

    await stream.append("a" * 4096)
    await stream.append("b")
    await stream.finish()
    await stream.finish()

    assert sent == ["a" * 4096, "b"]
