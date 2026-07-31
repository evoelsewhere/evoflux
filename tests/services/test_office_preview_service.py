from __future__ import annotations

from docx import Document
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as WorkbookImage
from PIL import Image
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt
import pytest

from app.services import office_preview_service as preview


def _docx(path):
    document = Document()
    document.add_heading("Quarterly review", level=1)
    document.add_paragraph("Revenue increased.")
    document.save(path)


def _xlsx(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet["A1"] = "Revenue"
    sheet["B1"] = 120
    sheet["B2"] = "=B1*2"
    workbook.save(path)


def _pptx(path):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    text_box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    text_box.text = "Product launch"
    text_box.text_frame.paragraphs[0].runs[0].font.name = "Aptos Display"
    presentation.save(path)


def _add_chart(slide, categories, series, *, kind, title):
    data = ChartData()
    data.categories = categories
    for name, values in series.items():
        data.add_series(name, values)
    chart = slide.shapes.add_chart(
        kind,
        Inches(0.8),
        Inches(0.8),
        Inches(11.7),
        Inches(5.8),
        data,
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = title
    return chart


def test_render_docx_preview_uses_cache(monkeypatch, tmp_path):
    source = tmp_path / "report.docx"
    _docx(source)
    cache = tmp_path / "cache"
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(cache))

    first = preview.render_office_preview(source)
    second = preview.render_office_preview(source)

    assert first == second
    rendered = first.read_text()
    assert "Content-Security-Policy" in rendered
    assert "Quarterly review" in rendered
    assert "Revenue increased." in rendered
    assert 'class="document-flow"' in rendered
    assert "--page-width:" in rendered


def test_render_xlsx_preview(monkeypatch, tmp_path):
    source = tmp_path / "workbook.xlsx"
    _xlsx(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text(encoding="utf-8")

    assert "Summary" in rendered
    assert "Revenue" in rendered
    assert "=B1*2" in rendered
    assert "==B1*2" not in rendered
    assert 'data-cell="A1"' in rendered


def test_render_xlsx_preview_includes_charts_and_images(monkeypatch, tmp_path):
    source = tmp_path / "dashboard.xlsx"
    image_path = tmp_path / "badge.png"
    Image.new("RGB", (32, 24), "#2563eb").save(image_path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Dashboard"
    sheet.append(["Month", "Revenue"])
    sheet.append(["Jan", 120])
    sheet.append(["Feb", 180])
    chart = BarChart()
    chart.title = "Revenue trend"
    chart.add_data(
        Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True
    )
    sheet.add_chart(chart, "D2")
    sheet.add_image(WorkbookImage(image_path), "D18")
    workbook.save(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text(encoding="utf-8")

    assert 'class="workbook-chart-svg"' in rendered
    assert "<rect " in rendered
    assert 'class="workbook-image"' in rendered
    assert "data:image/png;base64," in rendered


def test_render_pptx_preview(monkeypatch, tmp_path):
    source = tmp_path / "slides.pptx"
    _pptx(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text(encoding="utf-8")

    assert "Product launch" in rendered
    assert 'class="slide"' in rendered
    assert 'data-source-layer="slide"' in rendered
    assert "aspect-ratio:" in rendered
    assert "Arial,sans-serif" in rendered


def test_render_pptx_preview_keeps_titles_single_line_and_renders_area_charts(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "area-chart.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    title = slide.shapes.add_textbox(
        Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.7)
    )
    title.name = "[role:title] Delivery confidence"
    title.text = "Delivery confidence"
    title.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    _add_chart(
        slide,
        ["Plan", "Compose", "Render", "Repair"],
        {"Confidence": [42, 61, 78, 93]},
        kind=XL_CHART_TYPE.AREA,
        title="Quality gate confidence",
    )
    presentation.save(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text()

    assert "white-space:nowrap" in rendered
    assert "font-size:16.20pt" in rendered
    assert '<polygon class="chart-area"' in rendered
    assert 'fill-opacity=".24"' in rendered
    assert ">Plan</text>" in rendered
    assert ">Repair</text>" in rendered


def test_render_pptx_preview_labels_pie_and_bar_categories(monkeypatch, tmp_path):
    source = tmp_path / "labelled-charts.pptx"
    presentation = Presentation()
    pie_slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    pie = _add_chart(
        pie_slide,
        ["Automation", "Reuse", "Other"],
        {"Value": [48, 34, 18]},
        kind=XL_CHART_TYPE.DOUGHNUT,
        title="Value mix",
    )
    pie.has_legend = True
    pie.plots[0].has_data_labels = True
    bar_slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _add_chart(
        bar_slide,
        ["Discover", "Deliver", "Scale"],
        {"Confidence": [42, 78, 93]},
        kind=XL_CHART_TYPE.BAR_CLUSTERED,
        title="Confidence by phase",
    )
    presentation.save(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text()

    assert "Automation (48%)" in rendered
    assert "Reuse (34%)" in rendered
    assert ">Discover</text>" in rendered
    assert ">Scale</text>" in rendered


def test_render_pptx_preview_resolves_template_theme_colors(monkeypatch, tmp_path):
    source = tmp_path / "theme.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(1),
        Inches(1),
        Inches(3),
        Inches(1),
    )
    shape.fill.solid()
    shape.fill.fore_color.theme_color = MSO_THEME_COLOR.ACCENT_1
    presentation.save(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text(encoding="utf-8")

    assert "background:#4F81BD" in rendered


def test_render_pptx_preview_supports_bullets_columns_and_connectors(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "rich-office.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    text_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(5), Inches(2))
    text_box.text_frame._txBody.bodyPr.set("numCol", "2")
    for index, value in enumerate(("First point", "Second point")):
        paragraph = (
            text_box.text_frame.paragraphs[0]
            if index == 0
            else text_box.text_frame.add_paragraph()
        )
        paragraph.text = value
        properties = paragraph._p.get_or_add_pPr()
        bullet = OxmlElement("a:buChar")
        bullet.set("char", "•")
        properties.append(bullet)

    boxes = []
    for index, label in enumerate(("Discover", "Decide", "Deliver")):
        box = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(1 + index * 3.5),
            Inches(3.3),
            Inches(2.5),
            Inches(1.2),
        )
        box.text = label
        boxes.append(box)
    for left, right in zip(boxes[:-1], boxes[1:], strict=True):
        slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            left.left + left.width,
            left.top + left.height // 2,
            right.left,
            right.top + right.height // 2,
        )
    presentation.save(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    rendered = preview.render_office_preview(source).read_text(encoding="utf-8")

    assert 'class="bullet-marker">•</span>' in rendered
    assert "column-count:2" in rendered
    assert rendered.count('class="shape connector"') == 2
    assert "Discover" in rendered
    assert "Deliver" in rendered


def test_render_office_preview_invalidates_when_source_changes(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "workbook.xlsx"
    _xlsx(source)
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    first = preview.render_office_preview(source)
    workbook = Workbook()
    workbook.active["A1"] = "Changed"
    workbook.save(source)
    second = preview.render_office_preview(source)

    assert first != second


def test_render_office_preview_rejects_unsupported_file(tmp_path):
    source = tmp_path / "legacy.xls"
    source.write_bytes(b"legacy")
    with pytest.raises(preview.OfficePreviewUnsupportedError):
        preview.render_office_preview(source)


def test_render_office_preview_surfaces_parse_error(monkeypatch, tmp_path):
    source = tmp_path / "broken.pptx"
    source.write_bytes(b"not an OpenXML package")
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    with pytest.raises(preview.OfficePreviewError, match="Could not render"):
        preview.render_office_preview(source)
