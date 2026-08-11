"""Document-plugin renderers used by artifact QA and preview pipelines.

The renderers intentionally consume the same OOXML models that the authoring
engines write.  They do not shell out to LibreOffice, Poppler, Chromium, or any
other machine-wide application, so desktop and server builds behave the same.
"""

from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont
import pypdfium2 as pdfium


_FONT_ROOT = (
    Path(__file__).resolve().parents[3]
    / "builtin_skills"
    / "canvas-design"
    / "canvas-fonts"
)


def _font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "InstrumentSans-Bold.ttf" if bold else "InstrumentSans-Regular.ttf"
    try:
        return ImageFont.truetype(str(_FONT_ROOT / name), max(8, size))
    except OSError:
        return ImageFont.load_default()


def _color(value: Any, default: str = "#ffffff") -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 8:
        text = text[-6:]
    if len(text) == 6:
        try:
            ImageColor.getrgb(f"#{text}")
            return f"#{text}"
        except ValueError:
            pass
    return default


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: int,
) -> list[str]:
    if width <= 1:
        return [value]
    lines: list[str] = []
    for paragraph in value.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_text_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: str,
    *,
    color: str = "#111827",
    size: int = 18,
    bold: bool = False,
    align: str = "left",
) -> None:
    left, top, right, bottom = box
    padding = max(3, size // 5)
    font = _font(size, bold=bold)
    lines = _wrapped_lines(draw, value, font, max(1, right - left - 2 * padding))
    line_height = max(size + 3, draw.textbbox((0, 0), "Ag", font=font)[3] + 3)
    y = top + padding
    for line in lines:
        if y + line_height > bottom:
            break
        text_width = draw.textbbox((0, 0), line, font=font)[2]
        if align == "center":
            x = left + max(padding, (right - left - text_width) // 2)
        elif align == "right":
            x = right - padding - text_width
        else:
            x = left + padding
        draw.text((x, y), line, fill=color, font=font)
        y += line_height


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
    """Rasterize PDF pages with optional resource bounds.

    Artifact QA leaves the limits unset so it can inspect every page. The
    interactive preview supplies strict limits to keep untrusted documents
    from exhausting sidecar or WebView memory.
    """

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


def render_docx_pages(source: Path, render_dir: Path, *, dpi: int = 144) -> list[Path]:
    """Render a deterministic semantic DOCX preview with Pillow.

    This is deliberately an OOXML-model renderer, not an Office emulator.  It
    catches overflow, missing content, table density, and pagination regressions
    without requiring a separately installed office suite.
    """
    from docx import Document

    document = Document(str(source))
    width = int(8.27 * dpi)
    height = int(11.69 * dpi)
    margin = int(0.65 * dpi)
    pages: list[Image.Image] = []
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y = margin

    def new_page() -> None:
        nonlocal image, draw, y
        pages.append(image)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        y = margin

    def ensure(space: int) -> None:
        if y + space > height - margin:
            new_page()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            y += 10
            continue
        style_name = (paragraph.style.name if paragraph.style else "").lower()
        heading = "heading" in style_name or "title" in style_name
        size = 30 if "title" in style_name else 22 if heading else 14
        font = _font(size, bold=heading)
        lines = _wrapped_lines(draw, text, font, width - 2 * margin)
        line_height = size + 6
        ensure(max(line_height, len(lines) * line_height + 8))
        for line in lines:
            draw.text((margin, y), line, fill="#172033", font=font)
            y += line_height
        y += 8

    for table in document.tables:
        rows = len(table.rows)
        columns = max((len(row.cells) for row in table.rows), default=0)
        if rows == 0 or columns == 0:
            continue
        cell_width = (width - 2 * margin) // columns
        row_height = 42
        ensure(min(rows, 5) * row_height + 16)
        for row_index, row in enumerate(table.rows):
            ensure(row_height)
            for column_index, cell in enumerate(row.cells):
                box = (
                    margin + column_index * cell_width,
                    y,
                    margin + (column_index + 1) * cell_width,
                    y + row_height,
                )
                fill = "#e8eef7" if row_index == 0 else "#ffffff"
                draw.rectangle(box, fill=fill, outline="#aab4c3", width=1)
                _draw_text_box(
                    draw,
                    box,
                    cell.text,
                    size=11,
                    bold=row_index == 0,
                )
            y += row_height
        y += 16

    pages.append(image)
    render_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, page in enumerate(pages, start=1):
        destination = render_dir / f"page-{index:03d}.png"
        page.save(destination)
        outputs.append(destination)
    return outputs


def _xlsx_cell_color(cell: Any) -> str:
    fill = getattr(cell, "fill", None)
    foreground = getattr(fill, "fgColor", None)
    if getattr(fill, "fill_type", None) == "solid":
        return _color(getattr(foreground, "rgb", None), "#ffffff")
    return "#ffffff"


def render_xlsx_workbook(workbook: Any, render_dir: Path) -> list[Path]:
    """Render every worksheet into a bounded PNG grid."""
    from openpyxl.utils import get_column_letter

    render_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for sheet_index, sheet in enumerate(workbook.worksheets, start=1):
        max_row = max(1, min(sheet.max_row, 250))
        max_column = max(1, min(sheet.max_column, 60))
        column_widths = [
            max(
                42,
                min(
                    280,
                    int(
                        (
                            sheet.column_dimensions[get_column_letter(column)].width
                            or 8.43
                        )
                        * 7
                        + 12
                    ),
                ),
            )
            for column in range(1, max_column + 1)
        ]
        row_heights = [
            max(24, min(120, int((sheet.row_dimensions[row].height or 18) * 1.34)))
            for row in range(1, max_row + 1)
        ]
        width = min(5000, sum(column_widths) + 2)
        height = min(7000, sum(row_heights) + 2)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        y = 1
        for row in range(1, max_row + 1):
            x = 1
            row_height = row_heights[row - 1]
            for column in range(1, max_column + 1):
                column_width = column_widths[column - 1]
                if x >= width:
                    break
                right = min(width - 1, x + column_width)
                bottom = min(height - 1, y + row_height)
                cell = sheet.cell(row, column)
                draw.rectangle(
                    (x, y, right, bottom),
                    fill=_xlsx_cell_color(cell),
                    outline="#c7ced8",
                )
                value = "" if cell.value is None else str(cell.value)
                font = getattr(cell, "font", None)
                alignment = getattr(cell, "alignment", None)
                _draw_text_box(
                    draw,
                    (x, y, right, bottom),
                    value,
                    color=_color(
                        getattr(getattr(font, "color", None), "rgb", None), "#1f2937"
                    ),
                    size=max(9, min(18, int(getattr(font, "sz", None) or 11))),
                    bold=bool(getattr(font, "bold", False)),
                    align=str(getattr(alignment, "horizontal", None) or "left"),
                )
                x += column_width
            y += row_height
            if y >= height:
                break
        destination = render_dir / f"sheet-{sheet_index:03d}.png"
        image.save(destination)
        outputs.append(destination)
    return outputs


def render_xlsx_file(source: Path, render_dir: Path) -> list[Path]:
    from openpyxl import load_workbook

    workbook = load_workbook(source, data_only=False)
    try:
        return render_xlsx_workbook(workbook, render_dir)
    finally:
        workbook.close()


def _pptx_rgb(value: Any, default: str) -> str:
    try:
        rgb = value.rgb
    except (AttributeError, TypeError, ValueError):
        return default
    return _color(rgb, default)


def _render_chart(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], chart: Any
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill="#ffffff", outline="#c6cfdb", width=1)
    try:
        series = list(chart.series)
        values = [list(item.values) for item in series]
    except (AttributeError, TypeError, ValueError):
        return
    flat = [float(value or 0) for row in values for value in row]
    if not flat:
        return
    maximum = max(max(flat), 1)
    count = max(len(row) for row in values)
    group_width = max(1, (right - left - 24) // max(1, count))
    palette = ("#2563eb", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6")
    for series_index, row in enumerate(values):
        bar_width = max(2, group_width // max(1, len(values)) - 2)
        for index, value in enumerate(row):
            magnitude = max(0.0, float(value or 0)) / maximum
            x = left + 12 + index * group_width + series_index * (bar_width + 2)
            y = bottom - 12 - int((bottom - top - 28) * magnitude)
            draw.rectangle(
                (x, y, x + bar_width, bottom - 12),
                fill=palette[series_index % len(palette)],
            )


def render_pptx_pages(
    source: Path, render_dir: Path, *, width: int = 1280
) -> list[Path]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(str(source))
    slide_width = int(presentation.slide_width or 1)
    slide_height = int(presentation.slide_height or 1)
    height = max(1, int(width * slide_height / slide_width))
    x_scale = width / slide_width
    y_scale = height / slide_height
    render_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        background = "#ffffff"
        try:
            background = _pptx_rgb(slide.background.fill.fore_color, background)
        except (AttributeError, TypeError, ValueError):
            pass
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        for shape in slide.shapes:
            box = (
                int(shape.left * x_scale),
                int(shape.top * y_scale),
                int((shape.left + shape.width) * x_scale),
                int((shape.top + shape.height) * y_scale),
            )
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    picture = Image.open(BytesIO(shape.image.blob)).convert("RGBA")
                    picture.thumbnail(
                        (max(1, box[2] - box[0]), max(1, box[3] - box[1]))
                    )
                    image.paste(picture, (box[0], box[1]), picture)
                except (OSError, ValueError):
                    draw.rectangle(box, fill="#e5e7eb", outline="#94a3b8")
                continue
            if getattr(shape, "has_table", False):
                table = shape.table
                row_height = max(1, (box[3] - box[1]) // len(table.rows))
                column_width = max(1, (box[2] - box[0]) // len(table.columns))
                for row_index, row in enumerate(table.rows):
                    for column_index, cell in enumerate(row.cells):
                        cell_box = (
                            box[0] + column_index * column_width,
                            box[1] + row_index * row_height,
                            box[0] + (column_index + 1) * column_width,
                            box[1] + (row_index + 1) * row_height,
                        )
                        draw.rectangle(
                            cell_box,
                            fill="#e8eef7" if row_index == 0 else "#ffffff",
                            outline="#94a3b8",
                        )
                        _draw_text_box(
                            draw, cell_box, cell.text, size=12, bold=row_index == 0
                        )
                continue
            if getattr(shape, "has_chart", False):
                _render_chart(draw, box, shape.chart)
                continue
            fill = "#ffffff"
            line = "#94a3b8"
            try:
                fill = _pptx_rgb(shape.fill.fore_color, fill)
            except (AttributeError, TypeError, ValueError):
                pass
            try:
                line = _pptx_rgb(shape.line.color, line)
            except (AttributeError, TypeError, ValueError):
                pass
            if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
                draw.rectangle(box, fill=fill, outline=line, width=1)
            if getattr(shape, "has_text_frame", False) and shape.text.strip():
                paragraph = shape.text_frame.paragraphs[0]
                first_run = paragraph.runs[0] if paragraph.runs else None
                size = 20
                color = "#111827"
                bold = False
                if first_run is not None:
                    try:
                        if first_run.font.size:
                            size = max(
                                8, min(80, int(first_run.font.size.pt * width / 1280))
                            )
                    except (AttributeError, TypeError, ValueError):
                        pass
                    color = _pptx_rgb(first_run.font.color, color)
                    bold = bool(first_run.font.bold)
                _draw_text_box(draw, box, shape.text, color=color, size=size, bold=bold)
        destination = render_dir / f"slide-{slide_index:03d}.png"
        image.save(destination)
        outputs.append(destination)
    return outputs


__all__ = [
    "count_pdf_pages",
    "render_docx_pages",
    "render_pdf_pages",
    "render_pptx_pages",
    "render_xlsx_file",
    "render_xlsx_workbook",
]
