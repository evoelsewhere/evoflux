from __future__ import annotations

import os
import struct
import time
import zipfile
from pathlib import Path

import pytest

from app.services.document_preview import service as preview
from app.services.document_preview import security as preview_security


def _minimal_ooxml(
    path: Path,
    *,
    suffix: str = ".docx",
    extra_parts: tuple[tuple[str, bytes], ...] = (),
    content_types: bytes = b"<Types></Types>",
) -> None:
    main_part = {
        ".docx": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".pptx": "ppt/presentation.xml",
    }[suffix]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", b"<Relationships></Relationships>")
        archive.writestr(main_part, b"<root></root>")
        for name, payload in extra_parts:
            archive.writestr(name, payload)


def test_ooxml_preflight_accepts_bounded_package(tmp_path: Path) -> None:
    source = tmp_path / "safe.docx"
    _minimal_ooxml(source)

    preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_excessive_entry_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "parts.docx"
    _minimal_ooxml(source, extra_parts=(("word/extra.xml", b"<extra/>"),))
    monkeypatch.setattr(preview_security, "MAX_OOXML_ARCHIVE_ENTRIES", 3)

    with pytest.raises(
        preview.DocumentPreviewUnsupportedError,
        match="too many parts",
    ):
        preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_expanded_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "expanded.docx"
    _minimal_ooxml(source, extra_parts=(("word/large.xml", b"x" * 64),))
    monkeypatch.setattr(preview_security, "MAX_OOXML_EXPANDED_BYTES", 32)

    with pytest.raises(
        preview.DocumentPreviewUnsupportedError,
        match="expands beyond",
    ):
        preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_compression_bomb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "compressed.docx"
    _minimal_ooxml(
        source,
        extra_parts=(("word/repeated.xml", b"x" * (256 * 1024)),),
    )
    monkeypatch.setattr(preview_security, "MAX_OOXML_COMPRESSION_RATIO", 10.0)

    with pytest.raises(
        preview.DocumentPreviewUnsupportedError,
        match="unsafe compression ratio",
    ):
        preview_security.preflight_ooxml_package(source)


@pytest.mark.parametrize(
    ("part_name", "message"),
    [
        ("../escape.xml", "unsafe part name"),
        ("word/vbaProject.bin", "macros or active controls"),
        ("word/embeddings/payload.exe", "executable embedded content"),
    ],
)
def test_ooxml_preflight_rejects_unsafe_or_active_parts(
    part_name: str,
    message: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe.docx"
    _minimal_ooxml(source, extra_parts=((part_name, b"payload"),))

    with pytest.raises(preview.DocumentPreviewUnsupportedError, match=message):
        preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_active_content_type(tmp_path: Path) -> None:
    source = tmp_path / "macro.docx"
    _minimal_ooxml(
        source,
        content_types=(
            b'<Types><Default ContentType="application/vnd.ms-office.'
            b'vbaProject"/></Types>'
        ),
    )

    with pytest.raises(
        preview.DocumentPreviewUnsupportedError,
        match="macros, OLE objects, or active controls",
    ):
        preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_encrypted_member(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.docx"
    _minimal_ooxml(source)
    payload = bytearray(source.read_bytes())
    central_header = payload.find(b"PK\x01\x02")
    assert central_header >= 0
    flag_offset = central_header + 8
    flags = struct.unpack_from("<H", payload, flag_offset)[0]
    struct.pack_into("<H", payload, flag_offset, flags | 0x1)
    source.write_bytes(payload)

    with pytest.raises(
        preview.DocumentPreviewUnsupportedError,
        match="Encrypted OpenXML",
    ):
        preview_security.preflight_ooxml_package(source)


def test_ooxml_preflight_rejects_invalid_container(tmp_path: Path) -> None:
    source = tmp_path / "broken.pptx"
    source.write_bytes(b"not a zip package")

    with pytest.raises(preview.DocumentPreviewError, match="Could not render"):
        preview_security.preflight_ooxml_package(source)


def test_document_preview_cache_evicts_oldest_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(preview_security, "MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES", 2)
    monkeypatch.setattr(
        preview_security,
        "MAX_DOCUMENT_PREVIEW_CACHE_BYTES",
        1024 * 1024,
    )
    monkeypatch.setattr(
        preview,
        "_render_source",
        lambda source: f"<!doctype html><title>{source.name}</title>",
    )
    sources = [tmp_path / f"source-{index}.pdf" for index in range(3)]
    for index, source in enumerate(sources):
        source.write_bytes(f"payload-{index}".encode())

    first = preview.render_document_preview(sources[0])
    second = preview.render_document_preview(sources[1])
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))
    third = preview.render_document_preview(sources[2])

    assert not first.exists()
    assert second.is_file()
    assert third.is_file()


def test_document_preview_cache_enforces_total_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(preview_security, "MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES", 10)
    monkeypatch.setattr(preview_security, "MAX_DOCUMENT_PREVIEW_CACHE_BYTES", 12)
    monkeypatch.setattr(preview, "_render_source", lambda _source: "x" * 8)
    first_source = tmp_path / "first.pdf"
    second_source = tmp_path / "second.pdf"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")

    first = preview.render_document_preview(first_source)
    os.utime(first, (1, 1))
    second = preview.render_document_preview(second_source)

    assert not first.exists()
    assert second.is_file()


def test_document_preview_removes_legacy_generated_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    legacy = cache_root / "office-previews"
    legacy.mkdir(parents=True)
    (legacy / "old.html").write_text("generated", encoding="utf-8")
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(preview, "_render_source", lambda _source: "<!doctype html>")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    preview.render_document_preview(source)

    assert not legacy.exists()


def test_document_preview_cleanup_does_not_follow_legacy_cache_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    victim = tmp_path / "keep"
    victim.mkdir()
    marker = victim / "important.txt"
    marker.write_text("keep", encoding="utf-8")
    legacy = cache_root / "office-previews"
    legacy.symlink_to(victim, target_is_directory=True)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(preview, "_render_source", lambda _source: "<!doctype html>")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    preview.render_document_preview(source)

    assert not legacy.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_document_preview_cleanup_removes_only_stale_owned_transients(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_directory = tmp_path / "cache" / "document-previews"
    cache_directory.mkdir(parents=True)
    stale_pages = cache_directory / ("a" * 64 + "-pages")
    stale_pages.mkdir()
    (stale_pages / "page.png").write_bytes(b"generated")
    unrelated = cache_directory / "keep-me"
    unrelated.mkdir()
    old = time.time() - preview_security.STALE_DOCUMENT_PREVIEW_TEMP_SECONDS - 1
    os.utime(stale_pages, (old, old))
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(preview, "_render_source", lambda _source: "<!doctype html>")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    preview.render_document_preview(source)

    assert not stale_pages.exists()
    assert unrelated.is_dir()


def test_document_preview_cache_replaces_symlink_without_touching_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(preview, "_render_source", lambda _source: "safe preview")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    output = preview._cache_path(source)
    output.parent.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("unchanged", encoding="utf-8")
    output.symlink_to(victim)

    rendered = preview.render_document_preview(source)

    assert rendered.read_text(encoding="utf-8") == "safe preview"
    assert not rendered.is_symlink()
    assert victim.read_text(encoding="utf-8") == "unchanged"
