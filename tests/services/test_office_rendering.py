from __future__ import annotations

from pathlib import Path

from docx import Document

from app.services import docx_document_pipeline
from app.services.office import rendering


def test_internal_renderer_is_always_available() -> None:
    assert rendering.renderer_available() is True


def test_render_pages_creates_docx_preview_without_external_binary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "letter.docx"
    document = Document()
    document.add_heading("Portable preview", level=1)
    document.add_paragraph("No office suite is installed or launched.")
    document.save(source)

    pages, issues = rendering.render_pages(
        source, tmp_path / "previews", code_prefix="docx"
    )

    assert issues == []
    assert [path.name for path in pages] == ["page-001.png"]
    assert pages[0].stat().st_size > 0


def test_render_pages_reports_unsupported_format(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("plain text", encoding="utf-8")

    pages, issues = rendering.render_pages(
        source, tmp_path / "previews", code_prefix="document"
    )

    assert pages == []
    assert issues[0]["code"] == "document-render-failed"
    assert "unsupported render format" in issues[0]["message"]


def test_docx_pipeline_delegates_to_shared_internal_renderer(
    tmp_path: Path, monkeypatch
) -> None:
    seen: dict[str, object] = {}

    def fake_render_pages(
        source: Path, render_dir: Path, *, code_prefix: str, dpi: int = 144
    ) -> tuple[list[Path], list[dict[str, object]]]:
        seen.update({"source": source, "code_prefix": code_prefix, "dpi": dpi})
        return [render_dir / "page-001.png"], []

    monkeypatch.setattr(docx_document_pipeline, "render_pages", fake_render_pages)

    pages, issues = docx_document_pipeline.render_docx_pages(
        tmp_path / "letter.docx", tmp_path / "previews"
    )

    assert issues == []
    assert pages == [tmp_path / "previews" / "page-001.png"]
    assert seen == {
        "source": tmp_path / "letter.docx",
        "code_prefix": "docx",
        "dpi": 144,
    }
