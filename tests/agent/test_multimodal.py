"""Tests for app/agent/multimodal.py — build_parts_from_metas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent.multimodal import build_parts_from_metas
from app.agent.schemas.chat import ImageDataBlock, TextBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _att_text(text: str, name: str = "file.txt") -> dict:
    return {"converted_text": text, "original_name": name, "category": "text"}


def _att_image(path: str, name: str = "photo.jpg", mime: str = "image/jpeg") -> dict:
    return {
        "path": path,
        "filename": name,
        "original_name": name,
        "category": "image",
        "media_type": mime,
    }


def _att_no_path(name: str = "mystery.jpg") -> dict:
    """Attachment with category=image but no path key (triggers warning path)."""
    return {"original_name": name, "category": "image", "media_type": "image/jpeg"}


# ---------------------------------------------------------------------------
# fast path — converted_text present
# ---------------------------------------------------------------------------


def test_converted_text_produces_text_block():
    parts = build_parts_from_metas("hello", [_att_text("file content")])
    # First part is the file TextBlock, last is the user message
    assert len(parts) == 2
    assert isinstance(parts[0], TextBlock)
    assert "file content" in parts[0].text
    assert isinstance(parts[-1], TextBlock)
    assert parts[-1].text == "hello"


def test_converted_text_label_text_category():
    att = {
        "converted_text": "csv data",
        "original_name": "data.csv",
        "category": "text",
    }
    parts = build_parts_from_metas("msg", [att])
    assert parts[0].text.startswith("[File: data.csv]")


def test_converted_text_label_document_category():
    att = {
        "converted_text": "doc text",
        "original_name": "report.pdf",
        "category": "document",
    }
    parts = build_parts_from_metas("msg", [att])
    assert parts[0].text.startswith("[Document: report.pdf]")


def test_converted_text_block_is_fenced_with_close_tag():
    """Attachment content is wrapped in matched open + close tags so the
    model knows where the file ends and stops re-Reading inlined files."""
    file_att = {
        "converted_text": "hello world",
        "original_name": "notes.txt",
        "category": "text",
    }
    file_parts = build_parts_from_metas("msg", [file_att])
    assert file_parts[0].text == (
        "[File: notes.txt]\nhello world\n[End file: notes.txt]"
    )

    doc_att = {
        "converted_text": "report body",
        "original_name": "spec.pdf",
        "category": "document",
    }
    doc_parts = build_parts_from_metas("msg", [doc_att])
    assert doc_parts[0].text == (
        "[Document: spec.pdf]\nreport body\n[End document: spec.pdf]"
    )


def test_line_reference_attachment_tells_model_not_to_read_again():
    parts = build_parts_from_metas(
        "show me this",
        [_att_text("line 7\nline 8", name="commands/pr.md#L7-L8")],
    )
    assert parts[0].text == (
        "[File: commands/pr.md#L7-L8 — selected lines already loaded; "
        "use this block directly instead of reading the same range]\n"
        "line 7\nline 8\n"
        "[End file: commands/pr.md#L7-L8]"
    )


# ---------------------------------------------------------------------------
# slow path — image read from disk via stored ``path``
# ---------------------------------------------------------------------------


def test_image_read_from_disk(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)  # minimal JPEG-like bytes
    parts = build_parts_from_metas("describe", [_att_image(str(img))])
    # [path-hint TextBlock, ImageDataBlock, user-message TextBlock]
    assert len(parts) == 3
    assert isinstance(parts[0], TextBlock)
    assert parts[0].text == (
        f"[Attached image saved at {img}; render in markdown as uploads/photo.jpg]"
    )
    assert isinstance(parts[1], ImageDataBlock)
    assert parts[1].media_type == "image/jpeg"


def test_image_media_type_passed_through(tmp_path):
    img = tmp_path / "image.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    att = {
        "path": str(img),
        "filename": "image.png",
        "original_name": "image.png",
        "category": "image",
        "media_type": "image/png",
    }
    parts = build_parts_from_metas("x", [att])
    # path-hint precedes the ImageDataBlock
    assert parts[1].media_type == "image/png"


def test_image_path_hint_uses_absolute_path(tmp_path):
    """The path hint must reference the absolute saved path agents can pass
    directly to tools."""
    img = tmp_path / "abc123.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    att = {
        "path": str(img),
        "filename": "abc123.png",  # stored UUID name
        "original_name": "My Photo (1).png",  # raw user name
        "category": "image",
        "media_type": "image/png",
    }
    parts = build_parts_from_metas("describe", [att])
    hint = parts[0]
    assert isinstance(hint, TextBlock)
    assert hint.text == (
        f"[Attached image saved at {img}; render in markdown as uploads/abc123.png]"
    )
    # The raw user name must NOT leak into the path hint.
    assert "My Photo" not in hint.text


def test_text_attachment_has_no_path_hint():
    """The path hint is image-only — text attachments are inlined as
    ``[File: name]\\ncontent`` in the fast path; adding a path hint there
    would invite the model to re-read the file via ``read``."""
    parts = build_parts_from_metas("msg", [_att_text("hello", name="notes.txt")])
    assert len(parts) == 2  # one TextBlock + trailing user message
    assert "Attached image saved at" not in parts[0].text


def test_document_with_converted_text_has_no_path_hint():
    """Documents that markitdown-converted successfully use the fast path
    and must not get a path hint either."""
    att = {
        "converted_text": "PDF text content",
        "original_name": "report.pdf",
        "category": "document",
    }
    parts = build_parts_from_metas("msg", [att])
    assert len(parts) == 2
    assert "Attached image saved at" not in parts[0].text


# ---------------------------------------------------------------------------
# workspace fallback — unsupported/native-unknown files stay tool-readable
# ---------------------------------------------------------------------------


def test_workspace_delivery_emits_read_only_tool_instructions(tmp_path):
    binary = tmp_path / "archive.bin"
    binary.write_bytes(b"\x00\x01\x02")
    att = {
        "path": str(binary),
        "filename": "stored.bin",
        "original_name": "customer-format.xyz",
        "category": "binary",
        "media_type": "application/octet-stream",
        "size": 3,
        "delivery": "workspace",
    }

    parts = build_parts_from_metas("inspect this", [att])

    assert len(parts) == 2
    assert isinstance(parts[0], TextBlock)
    assert f"Read-only workspace path: {binary}" in parts[0].text
    assert "Use the Read tool first" in parts[0].text
    assert "Do not install OCR" in parts[0].text
    assert "do not execute it directly" in parts[0].text
    assert parts[-1].text == "inspect this"


def test_nonvision_image_workspace_delivery_does_not_embed_bytes(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    att = {
        "path": str(image),
        "original_name": "photo.png",
        "category": "image",
        "media_type": "image/png",
        "size": 8,
        "delivery": "workspace",
    }

    parts = build_parts_from_metas("inspect", [att])

    assert len(parts) == 2
    assert all(not isinstance(part, ImageDataBlock) for part in parts)
    assert f"Read-only workspace path: {image}" in parts[0].text


def test_native_audio_uses_generic_inline_media_block(tmp_path):
    audio = tmp_path / "recording.mp3"
    audio.write_bytes(b"audio")
    att = {
        "path": str(audio),
        "original_name": "recording.mp3",
        "category": "audio",
        "media_type": "audio/mpeg",
        "size": 5,
        "delivery": "native",
    }

    parts = build_parts_from_metas("transcribe", [att])

    assert len(parts) == 2
    assert isinstance(parts[0], ImageDataBlock)
    assert parts[0].media_type == "audio/mpeg"


# ---------------------------------------------------------------------------
# slow path — missing path key — emits ``[File not found: ...]`` placeholder
# ---------------------------------------------------------------------------


def test_missing_path_emits_file_not_found_placeholder():
    """Attachment with category=image but no path key emits a placeholder
    TextBlock so the LLM sees explicit context loss instead of silent drop."""
    parts = build_parts_from_metas("msg", [_att_no_path("mystery.jpg")])
    assert len(parts) == 2
    assert isinstance(parts[0], TextBlock)
    assert parts[0].text == "[File not found: mystery.jpg]"
    assert parts[-1].text == "msg"


# ---------------------------------------------------------------------------
# slow path — file missing on disk (OSError) — emits placeholder
# ---------------------------------------------------------------------------


def test_missing_file_on_disk_emits_file_not_found_placeholder(tmp_path):
    """If the image file is absent from disk, emit a ``[File not found:
    <name>]`` TextBlock instead of silently dropping the attachment."""
    att = {
        "path": str(tmp_path / "nonexistent.jpg"),
        "filename": "nonexistent.jpg",
        "original_name": "nonexistent.jpg",
        "category": "image",
        "media_type": "image/jpeg",
    }
    parts = build_parts_from_metas("msg", [att])
    assert len(parts) == 2
    assert isinstance(parts[0], TextBlock)
    assert parts[0].text == "[File not found: nonexistent.jpg]"
    assert parts[-1].text == "msg"


# ---------------------------------------------------------------------------
# multiple attachments + user message always last
# ---------------------------------------------------------------------------


def test_user_message_always_last(tmp_path):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"\xff\xd8" + b"\x00" * 8)
    parts = build_parts_from_metas(
        "user question",
        [_att_text("some text"), _att_image(str(img))],
    )
    assert parts[-1].text == "user question"
    assert isinstance(parts[-1], TextBlock)


def test_no_attachments_returns_single_text_block():
    parts = build_parts_from_metas("only message", [])
    assert len(parts) == 1
    assert parts[0].text == "only message"


def test_deleted_and_expired_browser_artifacts_are_not_rehydrated(tmp_path):
    image = tmp_path / "browser.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    base = _att_image(str(image), name="browser.png", mime="image/png")
    deleted = {**base, "deleted_at": datetime.now(timezone.utc).isoformat()}
    expired = {
        **base,
        "webbridge_artifact": {
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat()
        },
    }
    parts = build_parts_from_metas("question", [deleted, expired])
    assert len(parts) == 1
    assert parts[0].text == "question"
