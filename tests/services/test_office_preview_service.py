from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services import office_preview_service as preview


def test_render_office_preview_uses_cache(monkeypatch, tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"fake office bytes")
    cache = tmp_path / "cache"
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(cache))
    monkeypatch.setattr(preview, "_officecli_binary", lambda: "/fake/officecli")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        output = Path(argv[-1])
        output.write_text("<html><head></head><body>preview</body></html>")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(preview.subprocess, "run", fake_run)

    first = preview.render_office_preview(source)
    second = preview.render_office_preview(source)

    assert first == second
    assert len(calls) == 1
    rendered = first.read_text()
    assert "Content-Security-Policy" in rendered
    assert "<body>preview</body>" in rendered


def test_render_office_preview_invalidates_when_source_changes(monkeypatch, tmp_path):
    source = tmp_path / "slides.pptx"
    source.write_bytes(b"first")
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(preview, "_officecli_binary", lambda: "/fake/officecli")

    def fake_run(argv, **kwargs):
        Path(argv[-1]).write_text("<html><head></head><body>preview</body></html>")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(preview.subprocess, "run", fake_run)
    first = preview.render_office_preview(source)
    source.write_bytes(b"second version")
    second = preview.render_office_preview(source)
    assert first != second


def test_render_office_preview_rejects_unsupported_file(tmp_path):
    source = tmp_path / "legacy.xls"
    source.write_bytes(b"legacy")
    with pytest.raises(preview.OfficePreviewUnsupportedError):
        preview.render_office_preview(source)


def test_render_office_preview_surfaces_renderer_error(monkeypatch, tmp_path):
    source = tmp_path / "workbook.xlsx"
    source.write_bytes(b"fake")
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(preview, "_officecli_binary", lambda: "/fake/officecli")
    monkeypatch.setattr(
        preview.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 2, stdout="", stderr="bad workbook"
        ),
    )
    with pytest.raises(preview.OfficePreviewError, match="bad workbook"):
        preview.render_office_preview(source)
