"""Small deterministic style helpers for EvoFlux DOCX builders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph

DocumentProfileName = Literal[
    "standard-business",
    "compact-reference",
    "narrative-proposal",
    "operational-sop",
]


@dataclass(frozen=True)
class DocumentProfile:
    """Exact page, type, rhythm, and table tokens for a document archetype."""

    name: DocumentProfileName
    body_pt: float
    body_after_pt: float
    line_spacing: float
    title_pt: float
    h1_pt: float
    h2_pt: float
    h3_pt: float
    h1_before_pt: float
    h1_after_pt: float
    h2_before_pt: float
    h2_after_pt: float
    h3_before_pt: float
    h3_after_pt: float
    margin_inches: float
    header_footer_inches: float
    table_cell_vertical_dxa: int
    table_cell_horizontal_dxa: int
    table_header_fill: str


DOCUMENT_PROFILES: dict[DocumentProfileName, DocumentProfile] = {
    "standard-business": DocumentProfile(
        name="standard-business",
        body_pt=11,
        body_after_pt=6,
        line_spacing=1.10,
        title_pt=26,
        h1_pt=16,
        h2_pt=13,
        h3_pt=12,
        h1_before_pt=16,
        h1_after_pt=8,
        h2_before_pt=12,
        h2_after_pt=6,
        h3_before_pt=8,
        h3_after_pt=4,
        margin_inches=1.0,
        header_footer_inches=0.49,
        table_cell_vertical_dxa=80,
        table_cell_horizontal_dxa=120,
        table_header_fill="F2F4F7",
    ),
    "compact-reference": DocumentProfile(
        name="compact-reference",
        body_pt=10.5,
        body_after_pt=4,
        line_spacing=1.18,
        title_pt=24,
        h1_pt=15,
        h2_pt=12,
        h3_pt=10.5,
        h1_before_pt=18,
        h1_after_pt=10,
        h2_before_pt=14,
        h2_after_pt=7,
        h3_before_pt=10,
        h3_after_pt=5,
        margin_inches=0.78,
        header_footer_inches=0.42,
        table_cell_vertical_dxa=70,
        table_cell_horizontal_dxa=100,
        table_header_fill="E8EEF5",
    ),
    "narrative-proposal": DocumentProfile(
        name="narrative-proposal",
        body_pt=11,
        body_after_pt=8,
        line_spacing=1.30,
        title_pt=28,
        h1_pt=16,
        h2_pt=13,
        h3_pt=11.5,
        h1_before_pt=18,
        h1_after_pt=10,
        h2_before_pt=12,
        h2_after_pt=6,
        h3_before_pt=8,
        h3_after_pt=4,
        margin_inches=1.0,
        header_footer_inches=0.49,
        table_cell_vertical_dxa=90,
        table_cell_horizontal_dxa=120,
        table_header_fill="F4F6F9",
    ),
    "operational-sop": DocumentProfile(
        name="operational-sop",
        body_pt=10,
        body_after_pt=4,
        line_spacing=1.12,
        title_pt=23,
        h1_pt=15,
        h2_pt=12,
        h3_pt=10.5,
        h1_before_pt=12,
        h1_after_pt=6,
        h2_before_pt=10,
        h2_after_pt=5,
        h3_before_pt=8,
        h3_after_pt=4,
        margin_inches=0.70,
        header_footer_inches=0.38,
        table_cell_vertical_dxa=60,
        table_cell_horizontal_dxa=90,
        table_header_fill="E8EEF5",
    ),
}


def document_profile(
    name: DocumentProfileName = "standard-business",
) -> DocumentProfile:
    return DOCUMENT_PROFILES[name]


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


def _replace_metadata_marker(value: str, key: str, payload: str) -> str:
    pattern = re.compile(rf"(?:^|;\s*){re.escape(key)}:[^;]*")
    retained = pattern.sub("", value or "").strip(" ;")
    marker = f"{key}:{payload}"
    return f"{retained}; {marker}".strip(" ;") if retained else marker


def apply_document_profile(
    document: DocumentObject,
    name: DocumentProfileName,
) -> None:
    """Persist the document archetype without adding visible content."""

    document.core_properties.keywords = _replace_metadata_marker(
        document.core_properties.keywords or "",
        "evoflux-profile",
        name,
    )


def declare_content_contract(
    document: DocumentObject,
    required_sections: list[str],
) -> None:
    """Persist required sections so QA catches content dropped during layout."""

    cleaned = [section.strip() for section in required_sections if section.strip()]
    if not cleaned:
        raise ValueError("required_sections must not be empty")
    payload = "|".join(dict.fromkeys(cleaned)).replace(";", ",")
    document.core_properties.keywords = _replace_metadata_marker(
        document.core_properties.keywords or "",
        "evoflux-required",
        payload,
    )


def _set_style_font(style, *, name: str, size: float, color: str, bold: bool) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold
    style.element.rPr.rFonts.set(qn("w:eastAsia"), name)


def apply_theme(
    document: DocumentObject,
    theme: DocumentTheme = DocumentTheme(),
    *,
    profile: DocumentProfileName = "standard-business",
) -> None:
    """Apply page geometry and a semantic style ladder."""
    policy = document_profile(profile)
    apply_document_profile(document, profile)
    for section in document.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(policy.margin_inches)
        section.bottom_margin = Inches(policy.margin_inches)
        section.left_margin = Inches(policy.margin_inches)
        section.right_margin = Inches(policy.margin_inches)
        section.header_distance = Inches(policy.header_footer_inches)
        section.footer_distance = Inches(policy.header_footer_inches)

    styles = document.styles
    normal = styles["Normal"]
    _set_style_font(
        normal,
        name=theme.body_font,
        size=policy.body_pt,
        color=theme.ink,
        bold=False,
    )
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(policy.body_after_pt)
    normal.paragraph_format.line_spacing = policy.line_spacing
    normal.element.get_or_add_pPr().get_or_add_widowControl()

    roles = (
        ("Title", theme.heading_font, policy.title_pt, theme.ink, True, 0, 8),
        (
            "Heading 1",
            theme.heading_font,
            policy.h1_pt,
            theme.accent,
            True,
            policy.h1_before_pt,
            policy.h1_after_pt,
        ),
        (
            "Heading 2",
            theme.heading_font,
            policy.h2_pt,
            theme.ink,
            True,
            policy.h2_before_pt,
            policy.h2_after_pt,
        ),
        (
            "Heading 3",
            theme.body_font,
            policy.h3_pt,
            theme.ink,
            True,
            policy.h3_before_pt,
            policy.h3_after_pt,
        ),
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

    for list_style_name in ("List Bullet", "List Number"):
        list_style = styles[list_style_name]
        _set_style_font(
            list_style,
            name=theme.body_font,
            size=policy.body_pt,
            color=theme.ink,
            bold=False,
        )
        list_style.paragraph_format.left_indent = Inches(
            0.38 if profile in {"compact-reference", "operational-sop"} else 0.5
        )
        list_style.paragraph_format.first_line_indent = Inches(
            -0.19 if profile in {"compact-reference", "operational-sop"} else -0.25
        )
        list_style.paragraph_format.space_after = Pt(
            4 if profile in {"compact-reference", "operational-sop"} else 6
        )
        list_style.paragraph_format.line_spacing = policy.line_spacing

    if "Caption" not in styles:
        styles.add_style("Caption", WD_STYLE_TYPE.PARAGRAPH)
    caption = styles["Caption"]
    _set_style_font(
        caption,
        name=theme.body_font,
        size=max(policy.body_pt - 1.5, 8),
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
    profile: DocumentProfileName = "standard-business",
) -> None:
    """Set explicit Word geometry and a restrained header treatment."""
    policy = document_profile(profile)
    if not table.rows or len(widths_dxa) != len(table.columns):
        raise ValueError("widths_dxa must match the table column count")

    table.autofit = False
    table_properties = table._tbl.tblPr
    table_width = table_properties.first_child_found_in("w:tblW")
    table_width.set(qn("w:w"), str(sum(widths_dxa)))
    table_width.set(qn("w:type"), "dxa")
    table_indent = table_properties.first_child_found_in("w:tblInd")
    if table_indent is None:
        table_indent = OxmlElement("w:tblInd")
        table_properties.append(table_indent)
    table_indent.set(qn("w:w"), str(policy.table_cell_horizontal_dxa))
    table_indent.set(qn("w:type"), "dxa")
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
            set_cell_margins(
                cell,
                top=policy.table_cell_vertical_dxa,
                start=policy.table_cell_horizontal_dxa,
                bottom=policy.table_cell_vertical_dxa,
                end=policy.table_cell_horizontal_dxa,
            )
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = policy.line_spacing
                for run in paragraph.runs:
                    run.font.name = theme.body_font
                    run.font.size = Pt(policy.body_pt)
                    run.font.color.rgb = RGBColor.from_string(theme.ink)
            if row_index == 0:
                set_cell_shading(cell, policy.table_header_fill)
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
