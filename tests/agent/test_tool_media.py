from __future__ import annotations

import base64

import pytest

from app.agent.schemas.chat import ImageDataBlock, ImageUrlBlock, TextBlock
from app.agent.tool_media import materialize_tool_attachments


@pytest.mark.asyncio
async def test_materializes_inline_images_without_exposing_base64(
    tmp_path, monkeypatch
):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr("app.agent.tool_media.uploads_dir", lambda _sid: uploads)
    encoded = base64.b64encode(b"png bytes").decode("ascii")

    attachments = await materialize_tool_attachments(
        [
            TextBlock(text="Screenshot"),
            ImageDataBlock(data=encoded, media_type="image/png"),
        ],
        session_id="session-1",
        tool_name="browser_use",
    )

    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment["category"] == "image"
    assert attachment["media_type"] == "image/png"
    assert attachment["url"].startswith("/api/team/session-1/uploads/tool-media-")
    assert encoded not in str(attachment)
    assert (uploads / attachment["filename"]).read_bytes() == b"png bytes"


@pytest.mark.asyncio
async def test_keeps_remote_image_url_without_downloading(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr("app.agent.tool_media.uploads_dir", lambda _sid: uploads)

    attachments = await materialize_tool_attachments(
        [
            ImageUrlBlock(
                url="https://example.com/chart.webp",
                media_type="image/webp",
            )
        ],
        session_id="session-1",
        tool_name="chart",
    )

    assert attachments == [
        {
            "original_name": "Chart image 1.webp",
            "media_type": "image/webp",
            "category": "image",
            "url": "https://example.com/chart.webp",
        }
    ]
    assert not uploads.exists()


@pytest.mark.asyncio
async def test_materializes_data_url_instead_of_forwarding_it(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr("app.agent.tool_media.uploads_dir", lambda _sid: uploads)
    encoded = base64.b64encode(b"jpeg bytes").decode("ascii")

    attachments = await materialize_tool_attachments(
        [ImageUrlBlock(url=f"data:image/jpeg;base64,{encoded}")],
        session_id="session-1",
        tool_name="screenshot",
    )

    assert len(attachments) == 1
    assert attachments[0]["url"].startswith("/api/team/session-1/uploads/")
    assert "data:" not in str(attachments[0])
    assert (uploads / attachments[0]["filename"]).read_bytes() == b"jpeg bytes"
