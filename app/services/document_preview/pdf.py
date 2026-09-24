"""Bounded PDF rasterization used only by the read-only document viewer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from app.services.document_text import PDFIUM_LOCK


def count_pdf_pages(source: Path) -> int:
    """Return a PDF page count without rasterizing any page."""

    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(str(source))
        try:
            return len(document)
        finally:
            document.close()


def render_pdf_pages(
    source: Path,
    render_dir: Path,
    *,
    dpi: int = 144,
    max_pages: int | None = None,
    max_total_bytes: int | None = None,
    max_pixels_per_page: int | None = None,
) -> list[Path]:
    """Rasterize PDF pages within the viewer's resource bounds."""

    render_dir.mkdir(parents=True, exist_ok=True)
    with PDFIUM_LOCK:
        return _render_pdf_pages(
            source,
            render_dir,
            dpi=dpi,
            max_pages=max_pages,
            max_total_bytes=max_total_bytes,
            max_pixels_per_page=max_pixels_per_page,
        )


def _render_pdf_pages(
    source: Path,
    render_dir: Path,
    *,
    dpi: int,
    max_pages: int | None,
    max_total_bytes: int | None,
    max_pixels_per_page: int | None,
) -> list[Path]:
    document = pdfium.PdfDocument(str(source))
    outputs: list[Path] = []
    scale = dpi / 72
    total_bytes = 0
    try:
        page_count = len(document)
        if max_pages is not None:
            page_count = min(page_count, max(0, max_pages))
        for index in range(page_count):
            page = document[index]
            try:
                render_scale = scale
                if max_pixels_per_page is not None:
                    width, height = page.get_size()
                    pixels = width * height * render_scale * render_scale
                    if not math.isfinite(pixels) or pixels <= 0:
                        raise ValueError("PDF page has invalid dimensions")
                    if pixels > max_pixels_per_page:
                        render_scale *= math.sqrt(max_pixels_per_page / pixels)
                bitmap = page.render(scale=render_scale)
                try:
                    image = bitmap.to_pil()
                    destination = render_dir / f"page-{index + 1:03d}.png"
                    try:
                        image.save(destination)
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
            output_bytes = destination.stat().st_size
            if (
                max_total_bytes is not None
                and total_bytes + output_bytes > max_total_bytes
            ):
                destination.unlink(missing_ok=True)
                break
            total_bytes += output_bytes
            outputs.append(destination)
    finally:
        document.close()
    return outputs


@dataclass(frozen=True, slots=True)
class TextRun:
    """One positioned run of page text, in percent of the page box."""

    text: str
    left: float
    top: float
    width: float
    height: float
    #: Font size as a percentage of the page width (CSS ``cqw``).
    font_size: float


@dataclass(frozen=True, slots=True)
class TextLayer:
    width: float
    height: float
    runs: list[TextRun]


def pdf_text_layers(
    source: Path,
    *,
    max_pages: int,
    max_chars_per_page: int = 40_000,
) -> list[TextLayer | None]:
    """Extract positioned text runs so raster pages stay searchable/selectable.

    A page whose text cannot be extracted yields ``None``; the raster still
    renders, it just is not searchable.
    """
    with PDFIUM_LOCK:
        return _pdf_text_layers(
            source, max_pages=max_pages, max_chars_per_page=max_chars_per_page
        )


def _pdf_text_layers(
    source: Path, *, max_pages: int, max_chars_per_page: int
) -> list[TextLayer | None]:
    document = pdfium.PdfDocument(str(source))
    layers: list[TextLayer | None] = []
    try:
        for index in range(min(len(document), max(0, max_pages))):
            page = document[index]
            try:
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    layers.append(None)
                    continue
                textpage = page.get_textpage()
                try:
                    runs: list[TextRun] = []
                    budget = max_chars_per_page
                    for rect_index in range(textpage.count_rects()):
                        left, bottom, right, top = textpage.get_rect(rect_index)
                        text = textpage.get_text_bounded(left, bottom, right, top)
                        text = text.replace("\r", "").replace("\n", " ")
                        if not text.strip() or right <= left or top <= bottom:
                            continue
                        budget -= len(text)
                        if budget < 0:
                            break
                        box_height = top - bottom
                        runs.append(
                            TextRun(
                                text=text,
                                left=100 * left / width,
                                top=100 * (height - top) / height,
                                width=100 * (right - left) / width,
                                height=100 * box_height / height,
                                font_size=100 * box_height * 0.86 / width,
                            )
                        )
                    layers.append(TextLayer(width=width, height=height, runs=runs))
                finally:
                    textpage.close()
            except pdfium.PdfiumError:
                layers.append(None)
            finally:
                page.close()
    finally:
        document.close()
    return layers


__all__ = [
    "TextLayer",
    "TextRun",
    "count_pdf_pages",
    "pdf_text_layers",
    "render_pdf_pages",
]
