"""Design-token helpers for EvoFlux PPTX builders."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.presentation import Presentation as PresentationObject
from pptx.util import Inches, Pt

EMU_PER_INCH = 914400
PT_PER_INCH = 72
LayoutName = Literal[
    "cover",
    "hero",
    "split",
    "visual-left",
    "comparison",
    "statement",
    "workstreams",
    "section",
    "agenda",
    "three-column",
    "four-quadrant",
    "chart-focus",
    "table-focus",
    "timeline",
    "metrics",
    "quote",
    "process",
    "image-full",
]
LayoutProfileName = Literal["editorial", "executive-dense", "operational"]


@dataclass(frozen=True)
class LayoutProfile:
    """Typography, spacing, and density policy for a family of slides."""

    name: LayoutProfileName
    title_min_pt: float
    subheading_min_pt: float
    body_min_pt: float
    caption_min_pt: float
    metadata_min_pt: float
    icon_min_inches: float
    minimum_gap_inches: float
    margin_inches: float


LAYOUT_PROFILES: dict[LayoutProfileName, LayoutProfile] = {
    "editorial": LayoutProfile(
        name="editorial",
        title_min_pt=35,
        subheading_min_pt=24,
        body_min_pt=16,
        caption_min_pt=10,
        metadata_min_pt=9,
        icon_min_inches=0.28,
        minimum_gap_inches=0.16,
        margin_inches=0.72,
    ),
    "executive-dense": LayoutProfile(
        name="executive-dense",
        title_min_pt=28,
        subheading_min_pt=14,
        body_min_pt=10,
        caption_min_pt=8,
        metadata_min_pt=7.5,
        icon_min_inches=0.22,
        minimum_gap_inches=0.10,
        margin_inches=0.48,
    ),
    "operational": LayoutProfile(
        name="operational",
        title_min_pt=24,
        subheading_min_pt=12,
        body_min_pt=8,
        caption_min_pt=7,
        metadata_min_pt=7,
        icon_min_inches=0.18,
        minimum_gap_inches=0.06,
        margin_inches=0.40,
    ),
}


def layout_profile(name: LayoutProfileName = "editorial") -> LayoutProfile:
    return LAYOUT_PROFILES[name]


def apply_layout_profile(slide, name: LayoutProfileName) -> None:
    """Persist the profile in editable slide XML for downstream QA."""

    marker = f"[profile:{name}]"
    current = str(slide._element.cSld.get("name", "") or "")
    current = re.sub(r"\s*\[profile:[a-z-]+\]\s*", " ", current).strip()
    slide._element.cSld.set("name", f"{current} {marker}".strip())


@dataclass(frozen=True)
class PresentationTheme:
    """A restrained editorial theme suitable for business decks."""

    title_font: str = "Aptos Display"
    body_font: str = "Aptos"
    background: str = "F7F5F0"
    ink: str = "20303C"
    muted: str = "66717C"
    accent: str = "2F6D68"
    highlight: str = "D6A756"
    title_pt: int = 40
    body_pt: int = 20
    margin_inches: float = 0.72


class LayoutError(ValueError):
    """Raised when a generated slide violates its declared composition."""


class TextOverflowError(LayoutError):
    """Raised before creating a text box whose copy cannot fit safely."""


@dataclass
class QualityLedger:
    """Collect every build-time quality issue before failing the build.

    A generator should create one ledger, pass it to its guards/text helpers,
    and call :meth:`raise_if_errors` once after all slides are composed. This
    avoids the expensive one-error-per-rebuild loop caused by fail-fast checks.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def raise_if_errors(self) -> None:
        if not self.errors:
            return
        details = "\n".join(
            f"{index}. {message}" for index, message in enumerate(self.errors, start=1)
        )
        raise LayoutError(
            f"PPTX preflight found {len(self.errors)} issue(s):\n{details}"
        )

    def report(self) -> dict[str, list[str]]:
        return {"errors": list(self.errors), "warnings": list(self.warnings)}


@dataclass(frozen=True)
class LayoutRegion:
    """A named rectangular region in EMUs."""

    name: str
    left: int
    top: int
    width: int
    height: int
    role: str = "content"

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def intersects(self, other: LayoutRegion, *, gap: int = 0) -> bool:
        return not (
            self.right + gap <= other.left
            or other.right + gap <= self.left
            or self.bottom + gap <= other.top
            or other.bottom + gap <= self.top
        )

    def contains(self, other: LayoutRegion) -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


@dataclass(frozen=True)
class SlideLayoutPlan:
    """One deliberate slide silhouette with non-overlapping content regions."""

    name: LayoutName
    profile: LayoutProfileName
    safe_canvas: LayoutRegion
    title: LayoutRegion
    content: dict[str, LayoutRegion]

    def region(self, name: str) -> LayoutRegion:
        try:
            return self.content[name]
        except KeyError as exc:
            available = ", ".join(sorted(self.content))
            raise LayoutError(
                f"Layout {self.name!r} has no region {name!r}; choose from {available}"
            ) from exc


@dataclass
class LayoutGuard:
    """Reserve slide geometry and reject unintended overlaps immediately."""

    plan: SlideLayoutPlan
    minimum_gap_inches: float | None = None
    ledger: QualityLedger | None = None
    _placed: list[LayoutRegion] = field(default_factory=list)

    def _reject(self, message: str) -> None:
        if self.ledger is None:
            raise LayoutError(message)
        self.ledger.error(message)

    def reserve(
        self,
        name: str,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
        role: str = "content",
        allow_overlap: bool = False,
    ) -> LayoutRegion:
        region = LayoutRegion(name, int(left), int(top), int(width), int(height), role)
        if width <= 0 or height <= 0:
            self._reject(f"{name!r} must have positive width and height")
        if role not in {"background", "footer"} and not self.plan.safe_canvas.contains(
            region
        ):
            self._reject(f"{name!r} is outside the declared safe canvas")
        gap_inches = (
            self.minimum_gap_inches
            if self.minimum_gap_inches is not None
            else layout_profile(self.plan.profile).minimum_gap_inches
        )
        gap = int(Inches(gap_inches))
        if not allow_overlap:
            collisions = [
                placed.name
                for placed in self._placed
                if placed.role not in {"background", "footer"}
                and region.intersects(placed, gap=gap)
            ]
            if collisions:
                self._reject(
                    f"{name!r} collides with {', '.join(collisions)}; "
                    "change the layout instead of stacking items"
                )
        self._placed.append(region)
        return region

    def reserve_region(self, region: LayoutRegion) -> LayoutRegion:
        return self.reserve(
            region.name,
            left=region.left,
            top=region.top,
            width=region.width,
            height=region.height,
            role=region.role,
        )


@dataclass(frozen=True)
class TextFitReport:
    estimated_lines: int
    maximum_lines: int
    required_height_pt: float
    available_height_pt: float
    fits: bool


def _region(name: str, left: float, top: float, width: float, height: float):
    return LayoutRegion(
        name,
        int(Inches(left)),
        int(Inches(top)),
        int(Inches(width)),
        int(Inches(height)),
    )


def layout_plan(
    presentation: PresentationObject,
    name: LayoutName,
    *,
    theme: PresentationTheme = PresentationTheme(),
    profile: LayoutProfileName = "editorial",
) -> SlideLayoutPlan:
    """Return a safe composition for a new 16:9 slide.

    Editorial slides use broad narrative regions. Dense profiles may use
    repeated micro-grids when the content itself is structured that way.
    """
    slide_width_emu = int(presentation.slide_width or 0)
    slide_height_emu = int(presentation.slide_height or 0)
    if slide_width_emu <= 0 or slide_height_emu <= 0:
        raise LayoutError("Presentation has invalid slide dimensions")
    slide_width = slide_width_emu / EMU_PER_INCH
    slide_height = slide_height_emu / EMU_PER_INCH
    policy = layout_profile(profile)
    margin = theme.margin_inches if profile == "editorial" else policy.margin_inches
    safe = _region(
        "safe-canvas",
        margin,
        0.34,
        slide_width - 2 * margin,
        slide_height - 0.68,
    )
    title = _region("title", margin, 0.42, slide_width - 2 * margin, 0.86)
    content_top = 1.62
    content_height = slide_height - content_top - 0.62
    content_width = slide_width - 2 * margin
    gap = 0.42

    if name == "cover":
        primary_width = content_width * 0.58
        content = {
            "primary": _region(
                "primary",
                margin,
                content_top,
                primary_width,
                content_height,
            ),
            "visual": _region(
                "visual",
                margin + primary_width + gap,
                content_top,
                content_width - primary_width - gap,
                content_height,
            ),
        }
    elif name == "hero":
        content = {
            "canvas": _region(
                "canvas",
                margin,
                content_top,
                content_width,
                content_height,
            )
        }
    elif name == "split":
        text_width = content_width * 0.38
        content = {
            "text": _region(
                "text",
                margin,
                content_top,
                text_width,
                content_height,
            ),
            "visual": _region(
                "visual",
                margin + text_width + gap,
                content_top,
                content_width - text_width - gap,
                content_height,
            ),
        }
    elif name == "visual-left":
        visual_width = content_width * 0.62
        content = {
            "visual": _region(
                "visual",
                margin,
                content_top,
                visual_width,
                content_height,
            ),
            "text": _region(
                "text",
                margin + visual_width + gap,
                content_top,
                content_width - visual_width - gap,
                content_height,
            ),
        }
    elif name == "comparison":
        column_width = (content_width - gap) / 2
        content = {
            "left": _region(
                "left",
                margin,
                content_top,
                column_width,
                content_height,
            ),
            "right": _region(
                "right",
                margin + column_width + gap,
                content_top,
                column_width,
                content_height,
            ),
        }
    elif name == "statement":
        statement_width = content_width * 0.68
        content = {
            "statement": _region(
                "statement",
                margin,
                content_top,
                statement_width,
                content_height,
            ),
            "evidence": _region(
                "evidence",
                margin + statement_width + gap,
                content_top,
                content_width - statement_width - gap,
                content_height,
            ),
        }
    elif name == "workstreams":
        if profile == "editorial":
            raise LayoutError(
                "The workstreams layout requires executive-dense or operational "
                "profile; editorial typography cannot carry its content safely"
            )
        content_top = 1.86 if profile == "executive-dense" else 1.72
        summary_height = 0.72
        summary_gap = 0.20
        columns_height = (
            slide_height - content_top - summary_height - summary_gap - 0.38
        )
        column_gap = 0.12 if profile == "executive-dense" else 0.09
        column_width = (content_width - 3 * column_gap) / 4
        content = {
            f"column-{index + 1}": _region(
                f"column-{index + 1}",
                margin + index * (column_width + column_gap),
                content_top,
                column_width,
                columns_height,
            )
            for index in range(4)
        }
        content["summary"] = _region(
            "summary",
            margin,
            content_top + columns_height + summary_gap,
            content_width,
            summary_height,
        )
    elif name == "section":
        statement_width = content_width * 0.78
        content = {
            "statement": _region(
                "statement",
                margin,
                content_top,
                statement_width,
                content_height,
            ),
            "marker": _region(
                "marker",
                margin + statement_width + gap,
                content_top,
                content_width - statement_width - gap,
                content_height,
            ),
        }
    elif name == "agenda":
        intro_width = content_width * 0.3
        content = {
            "intro": _region(
                "intro",
                margin,
                content_top,
                intro_width,
                content_height,
            ),
            "agenda": _region(
                "agenda",
                margin + intro_width + gap,
                content_top,
                content_width - intro_width - gap,
                content_height,
            ),
        }
    elif name == "three-column":
        column_gap = 0.24
        column_width = (content_width - 2 * column_gap) / 3
        content = {
            f"column-{index + 1}": _region(
                f"column-{index + 1}",
                margin + index * (column_width + column_gap),
                content_top,
                column_width,
                content_height,
            )
            for index in range(3)
        }
    elif name == "four-quadrant":
        row_gap = 0.22
        column_gap = 0.26
        cell_width = (content_width - column_gap) / 2
        cell_height = (content_height - row_gap) / 2
        content = {
            "top-left": _region(
                "top-left", margin, content_top, cell_width, cell_height
            ),
            "top-right": _region(
                "top-right",
                margin + cell_width + column_gap,
                content_top,
                cell_width,
                cell_height,
            ),
            "bottom-left": _region(
                "bottom-left",
                margin,
                content_top + cell_height + row_gap,
                cell_width,
                cell_height,
            ),
            "bottom-right": _region(
                "bottom-right",
                margin + cell_width + column_gap,
                content_top + cell_height + row_gap,
                cell_width,
                cell_height,
            ),
        }
    elif name == "chart-focus":
        chart_width = content_width * 0.7
        content = {
            "chart": _region("chart", margin, content_top, chart_width, content_height),
            "insight": _region(
                "insight",
                margin + chart_width + gap,
                content_top,
                content_width - chart_width - gap,
                content_height,
            ),
        }
    elif name == "table-focus":
        table_width = content_width * 0.76
        content = {
            "table": _region("table", margin, content_top, table_width, content_height),
            "note": _region(
                "note",
                margin + table_width + gap,
                content_top,
                content_width - table_width - gap,
                content_height,
            ),
        }
    elif name == "timeline":
        content = {
            "timeline": _region(
                "timeline", margin, content_top, content_width, content_height
            )
        }
    elif name == "metrics":
        metric_gap = 0.22
        metric_height = content_height * 0.58
        metric_width = (content_width - 2 * metric_gap) / 3
        content = {
            f"metric-{index + 1}": _region(
                f"metric-{index + 1}",
                margin + index * (metric_width + metric_gap),
                content_top,
                metric_width,
                metric_height,
            )
            for index in range(3)
        }
        content["detail"] = _region(
            "detail",
            margin,
            content_top + metric_height + 0.28,
            content_width,
            content_height - metric_height - 0.28,
        )
    elif name == "quote":
        quote_height = content_height * 0.72
        content = {
            "quote": _region("quote", margin, content_top, content_width, quote_height),
            "attribution": _region(
                "attribution",
                margin,
                content_top + quote_height + 0.22,
                content_width,
                content_height - quote_height - 0.22,
            ),
        }
    elif name == "process":
        process_height = content_height * 0.7
        content = {
            "process": _region(
                "process", margin, content_top, content_width, process_height
            ),
            "note": _region(
                "note",
                margin,
                content_top + process_height + 0.24,
                content_width,
                content_height - process_height - 0.24,
            ),
        }
    elif name == "image-full":
        content = {
            "canvas": _region(
                "canvas", margin, content_top, content_width, content_height
            )
        }
    else:
        raise LayoutError(f"Unknown layout: {name}")

    regions = list(content.values())
    for index, region in enumerate(regions):
        if not safe.contains(region):
            raise LayoutError(f"Layout region {region.name!r} is outside safe canvas")
        for other in regions[index + 1 :]:
            if region.intersects(other):
                raise LayoutError(
                    f"Layout {name!r} contains overlapping regions "
                    f"{region.name!r} and {other.name!r}"
                )
    return SlideLayoutPlan(
        name=name,
        profile=profile,
        safe_canvas=safe,
        title=title,
        content=content,
    )


def estimate_text_fit(
    text: str,
    *,
    width: int,
    height: int,
    size: float,
    margin_inches: float = 0.02,
    max_lines: int | None = None,
) -> TextFitReport:
    """Estimate wrapping conservatively before writing text to a slide."""
    usable_width_pt = max(
        width / EMU_PER_INCH * PT_PER_INCH - margin_inches * PT_PER_INCH * 2,
        1,
    )
    available_height_pt = max(
        height / EMU_PER_INCH * PT_PER_INCH - margin_inches * PT_PER_INCH * 2,
        1,
    )
    average_character_width = max(size * 0.54, 1)
    characters_per_line = max(int(usable_width_pt / average_character_width), 1)
    estimated_lines = 0
    for explicit_line in text.splitlines() or [""]:
        weighted_length = sum(
            1.18 if character.isupper() else 1.0 for character in explicit_line
        )
        estimated_lines += max(math.ceil(weighted_length / characters_per_line), 1)
    height_lines = max(int(available_height_pt / (size * 1.22)), 1)
    maximum_lines = min(height_lines, max_lines) if max_lines else height_lines
    required_height = estimated_lines * size * 1.22
    return TextFitReport(
        estimated_lines=estimated_lines,
        maximum_lines=maximum_lines,
        required_height_pt=round(required_height, 2),
        available_height_pt=round(available_height_pt, 2),
        fits=estimated_lines <= maximum_lines,
    )


def new_wide_presentation() -> PresentationObject:
    presentation = Presentation()
    presentation.slide_width = Inches(13.333333)
    presentation.slide_height = Inches(7.5)
    return presentation


def set_background(slide, color: str) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(color)


def _apply_run(run, *, font: str, size: float, color: str, bold: bool) -> None:
    run.font.name = font
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    run.font.bold = bold


def add_text(
    slide,
    text: str,
    *,
    left,
    top,
    width,
    height,
    font: str,
    size: float,
    color: str,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
    vertical_anchor=MSO_ANCHOR.MIDDLE,
    margin_inches: float = 0.02,
    role: str = "body",
    max_lines: int | None = None,
    strict: bool = True,
    profile: LayoutProfileName | None = None,
    guard: LayoutGuard | None = None,
    ledger: QualityLedger | None = None,
):
    active_profile = profile or (
        guard.plan.profile if guard is not None else "editorial"
    )
    policy = layout_profile(active_profile)
    minimum_sizes = {
        "deck-title": 50 if active_profile == "editorial" else 36,
        "title": policy.title_min_pt,
        "subheading": policy.subheading_min_pt,
        "section-heading": policy.subheading_min_pt,
        "body": policy.body_min_pt,
        "label": policy.body_min_pt,
        "caption": policy.caption_min_pt,
        "metadata": policy.metadata_min_pt,
        "kicker": policy.caption_min_pt,
        "footer": policy.metadata_min_pt,
    }
    active_ledger = ledger or (guard.ledger if guard is not None else None)

    def reject(message: str, error_type: type[LayoutError]) -> None:
        if active_ledger is None:
            raise error_type(message)
        active_ledger.error(message)

    minimum = minimum_sizes.get(role, policy.body_min_pt)
    if strict and size < minimum:
        reject(
            f"{role} text uses {size}pt; minimum is {minimum}pt. "
            "Shorten the copy or choose another layout.",
            LayoutError,
        )
    fit = estimate_text_fit(
        text,
        width=int(width),
        height=int(height),
        size=size,
        margin_inches=margin_inches,
        max_lines=max_lines,
    )
    if strict and not fit.fits:
        reject(
            f"{role} text needs about {fit.estimated_lines} lines but the box "
            f"allows {fit.maximum_lines}; shorten the copy or change layout",
            TextOverflowError,
        )
    if guard is not None:
        guard.reserve(
            f"{role}:{text[:32]}",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role=role,
        )
    shape = slide.shapes.add_textbox(left, top, width, height)
    shape.name = f"[role:{role}] {text[:48]}".strip()
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(margin_inches)
    frame.margin_right = Inches(margin_inches)
    frame.margin_top = Inches(margin_inches)
    frame.margin_bottom = Inches(margin_inches)
    frame.vertical_anchor = vertical_anchor
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    paragraph.space_after = Pt(0)
    run = paragraph.add_run()
    run.text = text
    _apply_run(run, font=font, size=size, color=color, bold=bold)
    return shape


def add_title(
    slide,
    text: str,
    *,
    theme: PresentationTheme = PresentationTheme(),
    kicker: str | None = None,
    profile: LayoutProfileName | None = None,
    guard: LayoutGuard | None = None,
):
    active_profile = profile or (
        guard.plan.profile if guard is not None else "editorial"
    )
    title_size = {
        "editorial": theme.title_pt,
        "executive-dense": min(theme.title_pt, 32),
        "operational": min(theme.title_pt, 28),
    }[active_profile]
    title_region = guard.plan.title if guard is not None else None
    if kicker:
        add_text(
            slide,
            kicker.upper(),
            left=Inches(theme.margin_inches),
            top=Inches(0.36),
            width=Inches(5.8),
            height=Inches(0.3),
            font=theme.body_font,
            size=11,
            color=theme.accent,
            bold=True,
            role="kicker",
            max_lines=1,
            profile=active_profile,
            ledger=guard.ledger if guard is not None else None,
        )
    return add_text(
        slide,
        text,
        left=title_region.left if title_region else Inches(theme.margin_inches),
        top=Inches(0.68 if kicker else 0.45),
        width=title_region.width if title_region else Inches(11.9),
        height=Inches(0.72),
        font=theme.title_font,
        size=title_size,
        color=theme.ink,
        bold=True,
        role="title",
        max_lines=1,
        profile=active_profile,
        guard=guard,
    )


def add_footer(
    slide,
    *,
    slide_number: int,
    source: str | None = None,
    theme: PresentationTheme = PresentationTheme(),
) -> None:
    if source:
        add_text(
            slide,
            source,
            left=Inches(theme.margin_inches),
            top=Inches(7.12),
            width=Inches(10.8),
            height=Inches(0.2),
            font=theme.body_font,
            size=9,
            color=theme.muted,
            role="footer",
        )
    add_text(
        slide,
        str(slide_number),
        left=Inches(12.15),
        top=Inches(7.08),
        width=Inches(0.45),
        height=Inches(0.22),
        font=theme.body_font,
        size=10,
        color=theme.muted,
        align=PP_ALIGN.RIGHT,
        role="footer",
    )


def add_image_cover(
    slide,
    image_path: str | Path,
    *,
    left,
    top,
    width,
    height,
    focal_x: float = 0.5,
    focal_y: float = 0.5,
    alt_text: str | None = None,
    guard: LayoutGuard | None = None,
):
    """Place an image with native crop controls and a configurable focal point."""
    if not 0 <= focal_x <= 1 or not 0 <= focal_y <= 1:
        raise ValueError("focal_x and focal_y must be between 0 and 1")
    if guard is not None:
        guard.reserve(
            f"image:{Path(image_path).name}",
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
            role="visual",
        )
    with Image.open(image_path) as image:
        image_ratio = image.width / image.height
    frame_ratio = width / height
    picture = slide.shapes.add_picture(
        str(image_path),
        left,
        top,
        width=width,
        height=height,
    )
    if image_ratio > frame_ratio:
        crop = 1 - frame_ratio / image_ratio
        picture.crop_left = crop * focal_x
        picture.crop_right = crop * (1 - focal_x)
    elif image_ratio < frame_ratio:
        crop = 1 - image_ratio / frame_ratio
        picture.crop_top = crop * focal_y
        picture.crop_bottom = crop * (1 - focal_y)
    if alt_text:
        properties = picture._element.xpath(".//*[local-name()='cNvPr']")
        if properties:
            properties[0].set("descr", alt_text)
    return picture


def add_speaker_source_note(slide, urls: list[str]) -> None:
    """Append a compact Sources block to speaker notes."""
    notes_frame = slide.notes_slide.notes_text_frame
    existing = notes_frame.text.rstrip()
    block = "[Sources]\n" + "\n".join(urls)
    notes_frame.text = f"{existing}\n\n{block}".strip()
