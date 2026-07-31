"""Office-native PowerPoint features for richer, editable slide compositions."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import lxml.etree as etree  # ty: ignore[unresolved-import] - lxml ships no stubs
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (
    XL_CHART_TYPE,
    XL_LABEL_POSITION,
    XL_LEGEND_POSITION,
)
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from app.agent.builtin_skills.pptx.scripts.stylekit import (
    LayoutGuard,
    PresentationTheme,
)

ChartKind = Literal["column", "bar", "line", "area", "pie", "doughnut"]
TransitionKind = Literal["none", "fade", "push", "wipe", "cut", "morph"]
_MORPH_NAMESPACE = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"

_CHART_TYPES = {
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "area": XL_CHART_TYPE.AREA,
    "pie": XL_CHART_TYPE.PIE,
    "doughnut": XL_CHART_TYPE.DOUGHNUT,
}


@dataclass(frozen=True)
class RichTextRun:
    """One independently formatted DrawingML text run."""

    text: str
    font: str | None = None
    size: int | None = None
    color: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass(frozen=True)
class RichParagraph:
    """One rich paragraph with optional native bullet semantics."""

    runs: tuple[RichTextRun, ...]
    bullet: bool = False
    level: int = 0
    align: PP_ALIGN = PP_ALIGN.LEFT
    space_after_pt: float = 7


def _theme_color(root, name: str, *, fallback: str) -> str:
    nodes = root.xpath(
        f".//a:themeElements/a:clrScheme/a:{name}/*",
        namespaces={"a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
    )
    if not nodes:
        return fallback
    node = nodes[0]
    value = node.get("lastClr") or node.get("val") or fallback
    return value.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", value) else fallback


def theme_from_presentation(presentation) -> PresentationTheme:
    """Extract fonts and core colors from the first PowerPoint theme part."""
    if not presentation.slide_masters:
        return PresentationTheme()
    try:
        theme_part = presentation.slide_masters[0].part.part_related_by(RT.THEME)
        root = etree.fromstring(theme_part.blob)
    except (AttributeError, KeyError, TypeError, ValueError, etree.XMLSyntaxError):
        return PresentationTheme()
    namespaces = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    major = root.xpath(
        ".//a:themeElements/a:fontScheme/a:majorFont/a:latin",
        namespaces=namespaces,
    )
    minor = root.xpath(
        ".//a:themeElements/a:fontScheme/a:minorFont/a:latin",
        namespaces=namespaces,
    )
    defaults = PresentationTheme()
    return PresentationTheme(
        title_font=major[0].get("typeface") if major else defaults.title_font,
        body_font=minor[0].get("typeface") if minor else defaults.body_font,
        background=_theme_color(root, "lt1", fallback=defaults.background),
        ink=_theme_color(root, "dk1", fallback=defaults.ink),
        muted=_theme_color(root, "dk2", fallback=defaults.muted),
        accent=_theme_color(root, "accent1", fallback=defaults.accent),
        highlight=_theme_color(root, "accent2", fallback=defaults.highlight),
        title_pt=defaults.title_pt,
        body_pt=defaults.body_pt,
        margin_inches=defaults.margin_inches,
    )


def _rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value.removeprefix("#"))


def _validate_series(
    categories: Sequence[str],
    series: Mapping[str, Sequence[float]],
) -> None:
    if not categories:
        raise ValueError("A native chart requires at least one category")
    if not series:
        raise ValueError("A native chart requires at least one series")
    for name, values in series.items():
        if len(values) != len(categories):
            raise ValueError(
                f"Series {name!r} has {len(values)} values for "
                f"{len(categories)} categories"
            )
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError(f"Series {name!r} contains a non-finite value")


def _set_text_style(
    text_frame,
    *,
    font: str,
    size: int,
    color: str,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
) -> None:
    text_frame.word_wrap = True
    text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    for paragraph in text_frame.paragraphs:
        paragraph.alignment = align
        paragraph.space_after = Pt(0)
        for run in paragraph.runs:
            run.font.name = font
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = _rgb(color)


def add_native_chart(
    slide,
    categories: Sequence[str],
    series: Mapping[str, Sequence[float]],
    *,
    left,
    top,
    width,
    height,
    kind: ChartKind = "column",
    title: str | None = None,
    number_format: str = "0",
    show_legend: bool | None = None,
    show_data_labels: bool = False,
    theme: PresentationTheme = PresentationTheme(),
    guard: LayoutGuard | None = None,
):
    """Add an editable PowerPoint chart with an embedded workbook."""
    _validate_series(categories, series)
    if kind not in _CHART_TYPES:
        raise ValueError(f"Unsupported native chart kind: {kind}")
    if guard is not None:
        guard.reserve(
            f"office-chart:{kind}",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role="visual",
        )

    data = ChartData()
    data.categories = tuple(str(category) for category in categories)
    for name, values in series.items():
        data.add_series(str(name), tuple(float(value) for value in values))

    frame = slide.shapes.add_chart(
        _CHART_TYPES[kind],
        left,
        top,
        width,
        height,
        data,
    )
    frame.name = f"[office:chart:{kind}]"
    chart = frame.chart
    chart.chart_style = 10
    chart.has_title = bool(title)
    if title:
        chart.chart_title.text_frame.text = title
        _set_text_style(
            chart.chart_title.text_frame,
            font=theme.title_font,
            size=18,
            color=theme.ink,
            bold=True,
        )

    chart.has_legend = len(series) > 1 if show_legend is None else show_legend
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.name = theme.body_font
        chart.legend.font.size = Pt(11)
        chart.legend.font.color.rgb = _rgb(theme.muted)

    colors = (theme.accent, theme.highlight, theme.ink, theme.muted)
    for index, chart_series in enumerate(chart.series):
        color = _rgb(colors[index % len(colors)])
        if kind == "line":
            chart_series.format.line.color.rgb = color
            chart_series.format.line.width = Pt(2.25)
        else:
            chart_series.format.fill.solid()
            chart_series.format.fill.fore_color.rgb = color
            chart_series.format.line.fill.background()

    plot = chart.plots[0]
    plot.has_data_labels = show_data_labels
    if show_data_labels:
        labels = plot.data_labels
        labels.show_value = True
        labels.number_format = number_format
        labels.font.name = theme.body_font
        labels.font.size = Pt(10)
        labels.font.color.rgb = _rgb(theme.ink)
        if kind in {"column", "bar"}:
            labels.position = XL_LABEL_POSITION.OUTSIDE_END
    if kind == "doughnut":
        plot.hole_size = 62
    if kind not in {"pie", "doughnut"}:
        value_axis = chart.value_axis
        value_axis.has_major_gridlines = True
        value_axis.tick_labels.number_format = number_format
        value_axis.tick_labels.font.name = theme.body_font
        value_axis.tick_labels.font.size = Pt(10)
        value_axis.tick_labels.font.color.rgb = _rgb(theme.muted)
        category_axis = chart.category_axis
        category_axis.tick_labels.font.name = theme.body_font
        category_axis.tick_labels.font.size = Pt(10)
        category_axis.tick_labels.font.color.rgb = _rgb(theme.muted)
        if kind == "bar":
            category_axis.reverse_order = True
    return frame


def _set_cell_border(cell, *, color: str, width_pt: float = 0.6) -> None:
    properties = cell._tc.get_or_add_tcPr()  # noqa: SLF001
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        existing = properties.find(qn(f"a:{edge}"))
        if existing is not None:
            properties.remove(existing)
        line = OxmlElement(f"a:{edge}")
        line.set("w", str(int(Pt(width_pt))))
        solid = OxmlElement("a:solidFill")
        srgb = OxmlElement("a:srgbClr")
        srgb.set("val", color.removeprefix("#").upper())
        solid.append(srgb)
        line.append(solid)
        dash = OxmlElement("a:prstDash")
        dash.set("val", "solid")
        line.append(dash)
        properties.append(line)


def add_native_table(
    slide,
    headers: Sequence[str],
    rows: Sequence[Sequence[str | int | float]],
    *,
    left,
    top,
    width,
    height,
    column_weights: Sequence[float] | None = None,
    alignments: Sequence[PP_ALIGN] | None = None,
    theme: PresentationTheme = PresentationTheme(),
    guard: LayoutGuard | None = None,
):
    """Add a styled, editable PowerPoint table rather than a grid of shapes."""
    if not headers:
        raise ValueError("A native table requires at least one column")
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("Every native table row must match the header width")
    if guard is not None:
        guard.reserve(
            "office-table",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role="visual",
        )

    shape = slide.shapes.add_table(
        len(rows) + 1,
        len(headers),
        left,
        top,
        width,
        height,
    )
    shape.name = "[office:table]"
    table = shape.table
    weights = tuple(column_weights or [1.0] * len(headers))
    if len(weights) != len(headers) or sum(weights) <= 0:
        raise ValueError("column_weights must contain one positive total per column")
    total_weight = sum(weights)
    remaining_width = int(width)
    for index, weight in enumerate(weights):
        column_width = (
            remaining_width
            if index == len(weights) - 1
            else int(width * weight / total_weight)
        )
        table.columns[index].width = column_width
        remaining_width -= column_width

    alignment_values = tuple(alignments or [PP_ALIGN.LEFT] * len(headers))
    if len(alignment_values) != len(headers):
        raise ValueError("alignments must contain one value per column")

    values = [tuple(headers), *(tuple(str(value) for value in row) for row in rows)]
    row_height = int(height / max(len(values), 1))
    for row_index, row_values in enumerate(values):
        table.rows[row_index].height = row_height
        for column_index, value in enumerate(row_values):
            cell = table.cell(row_index, column_index)
            cell.text = str(value)
            cell.margin_left = Inches(0.11)
            cell.margin_right = Inches(0.11)
            cell.margin_top = Inches(0.05)
            cell.margin_bottom = Inches(0.05)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if row_index == 0:
                fill_color = theme.accent
                text_color = theme.background
                bold = True
            else:
                fill_color = "FFFFFF" if row_index % 2 else "EEF2F0"
                text_color = theme.ink
                bold = False
            cell.fill.fore_color.rgb = _rgb(fill_color)
            _set_cell_border(cell, color="D4DAD7")
            _set_text_style(
                cell.text_frame,
                font=theme.body_font,
                size=14,
                color=text_color,
                bold=bold,
                align=alignment_values[column_index],
            )
    return shape


def _set_native_bullet(paragraph, *, level: int) -> None:
    properties = paragraph._p.get_or_add_pPr()  # noqa: SLF001
    for tag in ("buNone", "buChar", "buAutoNum"):
        existing = properties.find(qn(f"a:{tag}"))
        if existing is not None:
            properties.remove(existing)
    bullet = OxmlElement("a:buChar")
    bullet.set("char", "•")
    properties.insert(0, bullet)
    properties.set("marL", str(int(Inches(0.26 + level * 0.22))))
    properties.set("indent", str(-int(Inches(0.16))))


def add_rich_text(
    slide,
    paragraphs: Sequence[RichParagraph],
    *,
    left,
    top,
    width,
    height,
    columns: int = 1,
    column_spacing_inches: float = 0.24,
    margin_inches: float = 0.04,
    theme: PresentationTheme = PresentationTheme(),
    guard: LayoutGuard | None = None,
):
    """Add native multi-run, multi-paragraph, optionally multi-column text."""
    if not paragraphs:
        raise ValueError("Rich text requires at least one paragraph")
    if not 1 <= columns <= 4:
        raise ValueError("Rich text columns must be between 1 and 4")
    if any(not paragraph.runs for paragraph in paragraphs):
        raise ValueError("Every rich paragraph requires at least one run")
    if guard is not None:
        guard.reserve(
            "office-rich-text",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role="body",
        )

    shape = slide.shapes.add_textbox(left, top, width, height)
    shape.name = "[office:rich-text]"
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(margin_inches)
    frame.margin_right = Inches(margin_inches)
    frame.margin_top = Inches(margin_inches)
    frame.margin_bottom = Inches(margin_inches)
    frame.vertical_anchor = MSO_ANCHOR.TOP
    body_properties = frame._txBody.bodyPr  # noqa: SLF001
    if columns > 1:
        body_properties.set("numCol", str(columns))
        body_properties.set("spcCol", str(int(Inches(column_spacing_inches))))

    for paragraph_index, specification in enumerate(paragraphs):
        paragraph = (
            frame.paragraphs[0] if paragraph_index == 0 else frame.add_paragraph()
        )
        paragraph.alignment = specification.align
        paragraph.level = specification.level
        paragraph.space_after = Pt(specification.space_after_pt)
        if specification.bullet:
            _set_native_bullet(paragraph, level=specification.level)
        for run_specification in specification.runs:
            run = paragraph.add_run()
            run.text = run_specification.text
            run.font.name = run_specification.font or theme.body_font
            run.font.size = Pt(run_specification.size or theme.body_pt)
            run.font.color.rgb = _rgb(run_specification.color or theme.ink)
            run.font.bold = run_specification.bold
            run.font.italic = run_specification.italic
            run.font.underline = run_specification.underline
    return shape


def _set_connector_arrow(connector) -> None:
    line = connector.line._get_or_add_ln()  # noqa: SLF001
    existing = line.find(qn("a:tailEnd"))
    if existing is not None:
        line.remove(existing)
    arrow = OxmlElement("a:tailEnd")
    arrow.set("type", "triangle")
    arrow.set("w", "sm")
    arrow.set("len", "sm")
    line.append(arrow)


def add_grouped_process(
    slide,
    labels: Sequence[str],
    *,
    left,
    top,
    width,
    height,
    theme: PresentationTheme = PresentationTheme(),
    guard: LayoutGuard | None = None,
):
    """Add a connector-first, editable PowerPoint process as one group."""
    if not 2 <= len(labels) <= 6:
        raise ValueError("A grouped process requires between two and six steps")
    if guard is not None:
        guard.reserve(
            "office-grouped-process",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role="visual",
        )
    group = slide.shapes.add_group_shape()
    group.name = "[office:grouped-process]"
    node_size = min(int(Inches(0.5)), int(height * 0.28))
    center_y = int(top + height * 0.34)
    usable_width = int(width - node_size)
    centers = [
        int(left + node_size / 2 + usable_width * index / (len(labels) - 1))
        for index in range(len(labels))
    ]

    for start, end in zip(centers, centers[1:]):
        connector = group.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            int(start + node_size / 2),
            center_y,
            int(end - node_size / 2),
            center_y,
        )
        connector.line.color.rgb = _rgb(theme.muted)
        connector.line.width = Pt(1.5)
        _set_connector_arrow(connector)

    label_width = min(int(Inches(1.8)), int(width / len(labels) * 0.9))
    for index, (center, label) in enumerate(zip(centers, labels, strict=True)):
        node = group.shapes.add_shape(
            MSO_SHAPE.OVAL,
            int(center - node_size / 2),
            int(center_y - node_size / 2),
            node_size,
            node_size,
        )
        node.name = f"process-step-{index + 1}"
        node.fill.solid()
        node.fill.fore_color.rgb = _rgb(
            theme.highlight if index == len(labels) - 1 else theme.accent
        )
        node.line.fill.background()
        node.text = str(index + 1)
        _set_text_style(
            node.text_frame,
            font=theme.body_font,
            size=14,
            color=theme.background,
            bold=True,
            align=PP_ALIGN.CENTER,
        )
        text = group.shapes.add_textbox(
            int(center - label_width / 2),
            int(center_y + node_size * 0.68),
            label_width,
            max(int(height * 0.42), int(Inches(0.5))),
        )
        text.name = f"process-label-{index + 1}"
        text.text = label
        _set_text_style(
            text.text_frame,
            font=theme.body_font,
            size=16,
            color=theme.ink,
            bold=index == len(labels) - 1,
            align=PP_ALIGN.CENTER,
        )
    return group


def _non_visual_properties(shape):
    properties = shape._element.xpath(".//*[local-name()='cNvPr']")
    if not properties:
        raise ValueError(f"Shape {shape.name!r} has no non-visual properties")
    return properties[0]


def set_accessibility(
    shape,
    *,
    title: str,
    description: str,
):
    """Set PowerPoint title/alt text on any shape, picture, table, or chart."""
    properties = _non_visual_properties(shape)
    properties.set("title", title)
    properties.set("descr", description)
    return shape


def set_shape_hyperlink(shape, address: str):
    """Attach an editable PowerPoint click hyperlink to a shape."""
    if not address.strip():
        raise ValueError("Hyperlink address cannot be empty")
    shape.click_action.hyperlink.address = address
    return shape


def set_morph_identity(shape, identity: str):
    """Assign the `!!name` continuity marker used by PowerPoint Morph."""
    normalized = identity.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", normalized):
        raise ValueError(
            "Morph identity must contain only letters, digits, underscore, or hyphen"
        )
    _non_visual_properties(shape).set("name", f"!!{normalized}")
    return shape


def set_slide_transition(
    slide,
    kind: TransitionKind = "fade",
    *,
    speed: Literal["slow", "med", "fast"] = "fast",
    direction: Literal["l", "r", "u", "d"] = "r",
    advance_after_ms: int | None = None,
) -> None:
    """Set a conservative native slide transition through targeted OOXML."""
    slide_element = slide._element
    for transition in list(slide_element.findall(qn("p:transition"))):
        slide_element.remove(transition)
    if kind == "none":
        return
    if kind not in {"fade", "push", "wipe", "cut", "morph"}:
        raise ValueError(f"Unsupported transition kind: {kind}")
    if speed not in {"slow", "med", "fast"}:
        raise ValueError(f"Unsupported transition speed: {speed}")
    if advance_after_ms is not None and advance_after_ms < 0:
        raise ValueError("advance_after_ms cannot be negative")

    transition = OxmlElement("p:transition")
    transition.set("spd", speed)
    transition.set("advClick", "1")
    if advance_after_ms is not None:
        transition.set("advTm", str(advance_after_ms))
    if kind == "morph":
        effect = etree.Element(
            f"{{{_MORPH_NAMESPACE}}}morph",
            nsmap={"p159": _MORPH_NAMESPACE},
        )
        effect.set("option", "byObject")
    else:
        effect = OxmlElement(f"p:{kind}")
        if kind in {"push", "wipe"}:
            effect.set("dir", direction)
    transition.append(effect)
    slide_element.insert_element_before(transition, "p:timing", "p:extLst")


def apply_gradient_fill(
    shape,
    stops: Sequence[tuple[float, str, float]],
    *,
    angle: float = 0,
):
    """Apply a native linear gradient to an AutoShape.

    Each stop is ``(position, RGB, opacity)`` with position and opacity in the
    inclusive 0..1 range.
    """
    if len(stops) < 2:
        raise ValueError("A gradient requires at least two stops")
    shape_properties = shape._element.spPr
    for tag in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"):
        existing = shape_properties.find(qn(f"a:{tag}"))
        if existing is not None:
            shape_properties.remove(existing)

    gradient = OxmlElement("a:gradFill")
    gradient.set("rotWithShape", "1")
    stop_list = OxmlElement("a:gsLst")
    for position, color, opacity in sorted(stops, key=lambda item: item[0]):
        if not 0 <= position <= 1 or not 0 <= opacity <= 1:
            raise ValueError("Gradient positions and opacity must be between 0 and 1")
        stop = OxmlElement("a:gs")
        stop.set("pos", str(round(position * 100000)))
        srgb = OxmlElement("a:srgbClr")
        srgb.set("val", color.removeprefix("#").upper())
        alpha = OxmlElement("a:alpha")
        alpha.set("val", str(round(opacity * 100000)))
        srgb.append(alpha)
        stop.append(srgb)
        stop_list.append(stop)
    gradient.append(stop_list)
    linear = OxmlElement("a:lin")
    linear.set("ang", str(round((angle % 360) * 60000)))
    linear.set("scaled", "1")
    gradient.append(linear)
    shape_properties.insert_element_before(
        gradient,
        "a:ln",
        "a:effectLst",
        "a:scene3d",
        "a:sp3d",
        "a:extLst",
    )
    return shape


def apply_soft_shadow(
    shape,
    *,
    color: str = "20303C",
    opacity: float = 0.16,
    blur_pt: float = 8,
    distance_pt: float = 2,
    angle: float = 45,
):
    """Apply a restrained native outer shadow to a shape or picture."""
    if not 0 <= opacity <= 1:
        raise ValueError("Shadow opacity must be between 0 and 1")
    shape_properties = shape._element.spPr
    effects = shape_properties.find(qn("a:effectLst"))
    if effects is None:
        effects = OxmlElement("a:effectLst")
        shape_properties.append(effects)
    existing = effects.find(qn("a:outerShdw"))
    if existing is not None:
        effects.remove(existing)
    shadow = OxmlElement("a:outerShdw")
    shadow.set("blurRad", str(int(Pt(blur_pt))))
    shadow.set("dist", str(int(Pt(distance_pt))))
    shadow.set("dir", str(round((angle % 360) * 60000)))
    shadow.set("algn", "ctr")
    shadow.set("rotWithShape", "0")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", color.removeprefix("#").upper())
    alpha = OxmlElement("a:alpha")
    alpha.set("val", str(round(opacity * 100000)))
    srgb.append(alpha)
    shadow.append(srgb)
    effects.append(shadow)
    return shape
