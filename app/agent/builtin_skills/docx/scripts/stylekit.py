"""Small deterministic style helpers for EvoFlux DOCX builders."""

from __future__ import annotations

from dataclasses import dataclass

from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph


@dataclass(frozen=True)
class DocumentTheme:
    """Exact design tokens for a professional business document."""

    body_font: str = "Aptos"
    heading_font: str = "Aptos Display"
    body_size_pt: float = 10.5
    title_size_pt: float = 28
    h1_size_pt: float = 18
    h2_size_pt: float = 13
    ink: str = "24323D"
    muted: str = "66717C"
    accent: str = "356B73"
    table_header: str = "E7EFEE"
    table_border: str = "B8C4C7"
    margin_inches: float = 0.85


def _set_style_font(style, *, name: str, size: float, color: str, bold: bool) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold
    style.element.rPr.rFonts.set(qn("w:eastAsia"), name)


def apply_theme(
    document: DocumentObject, theme: DocumentTheme = DocumentTheme()
) -> None:
    """Apply page geometry and a semantic style ladder."""
    for section in document.sections:
        section.top_margin = Inches(theme.margin_inches)
        section.bottom_margin = Inches(theme.margin_inches)
        section.left_margin = Inches(theme.margin_inches)
        section.right_margin = Inches(theme.margin_inches)

    styles = document.styles
    normal = styles["Normal"]
    _set_style_font(
        normal,
        name=theme.body_font,
        size=theme.body_size_pt,
        color=theme.ink,
        bold=False,
    )
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    roles = (
        ("Title", theme.heading_font, theme.title_size_pt, theme.ink, True, 16, 0),
        ("Heading 1", theme.heading_font, theme.h1_size_pt, theme.accent, True, 14, 5),
        ("Heading 2", theme.heading_font, theme.h2_size_pt, theme.ink, True, 10, 3),
    )
    for name, font, size, color, bold, before, after in roles:
        style = styles[name]
        _set_style_font(style, name=font, size=size, color=color, bold=bold)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
        if name == "Title":
            properties = style.element.get_or_add_pPr()
            border = properties.find(qn("w:pBdr"))
            if border is not None:
                properties.remove(border)

    if "Caption" not in styles:
        styles.add_style("Caption", WD_STYLE_TYPE.PARAGRAPH)
    caption = styles["Caption"]
    _set_style_font(
        caption,
        name=theme.body_font,
        size=9,
        color=theme.muted,
        bold=False,
    )
    caption.paragraph_format.space_before = Pt(3)
    caption.paragraph_format.space_after = Pt(9)


def set_keep(paragraph: Paragraph, *, next_paragraph: bool = False) -> None:
    """Keep paragraph lines together and optionally keep it with the next."""
    properties = paragraph._p.get_or_add_pPr()
    properties.get_or_add_keepLines()
    if next_paragraph:
        properties.get_or_add_keepNext()
    properties.get_or_add_widowControl()


def set_cell_shading(cell: _Cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)


def set_cell_margins(
    cell: _Cell,
    *,
    top: int = 100,
    start: int = 120,
    bottom: int = 100,
    end: int = 120,
) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = properties.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        properties.append(margins)
    for edge, value in (
        ("top", top),
        ("start", start),
        ("bottom", bottom),
        ("end", end),
    ):
        node = margins.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def style_table(
    table: Table,
    *,
    widths_dxa: list[int],
    theme: DocumentTheme = DocumentTheme(),
) -> None:
    """Set explicit Word geometry and a restrained header treatment."""
    if not table.rows or len(widths_dxa) != len(table.columns):
        raise ValueError("widths_dxa must match the table column count")

    table.autofit = False
    table_properties = table._tbl.tblPr
    table_width = table_properties.first_child_found_in("w:tblW")
    table_width.set(qn("w:w"), str(sum(widths_dxa)))
    table_width.set(qn("w:type"), "dxa")
    borders = table_properties.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        table_properties.append(borders)
    for edge, style, size in (
        ("top", "single", "8"),
        ("bottom", "single", "8"),
        ("insideH", "single", "4"),
        ("insideV", "nil", "0"),
        ("start", "nil", "0"),
        ("end", "nil", "0"),
    ):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), style)
        node.set(qn("w:sz"), size)
        node.set(qn("w:color"), theme.table_border)

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)

    for row_index, row in enumerate(table.rows):
        if row_index == 0:
            row_properties = row._tr.get_or_add_trPr()
            repeat = OxmlElement("w:tblHeader")
            repeat.set(qn("w:val"), "true")
            row_properties.append(repeat)
        for column_index, cell in enumerate(row.cells):
            width = widths_dxa[column_index]
            cell.width = width
            properties = cell._tc.get_or_add_tcPr()
            cell_width = properties.first_child_found_in("w:tcW")
            cell_width.set(qn("w:w"), str(width))
            cell_width.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index == 0:
                set_cell_shading(cell, theme.table_header)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.color.rgb = RGBColor.from_string(theme.ink)


def add_field(paragraph: Paragraph, instruction: str, fallback: str = "") -> None:
    """Append a Word field with a cached fallback value."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = f" {instruction.strip()} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = fallback
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, code, separate, text, end):
        run._r.append(node)


def add_page_number_footer(
    document: DocumentObject,
    *,
    label: str = "Page ",
) -> None:
    for section in document.sections:
        paragraph = section.footer.paragraphs[0]
        paragraph.alignment = 2
        paragraph.add_run(label)
        add_field(paragraph, "PAGE", "1")


def add_landscape_section(document: DocumentObject):
    """Add and return a landscape section with swapped page dimensions."""
    section = document.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = 1
    section.page_width, section.page_height = (
        section.page_height,
        section.page_width,
    )
    return section
