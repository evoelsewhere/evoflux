"""Bounded PDF rasterization used only by the read-only document viewer."""

from __future__ import annotations

import math
from pathlib import Path

import pypdfium2 as pdfium


def count_pdf_pages(source: Path) -> int:
    """Return a PDF page count without rasterizing any page."""

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


__all__ = ["count_pdf_pages", "render_pdf_pages"]
