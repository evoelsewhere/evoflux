"""Design-token helpers for EvoFlux PPTX builders."""

from __future__ import annotations

import math
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
LayoutName = Literal["hero", "split", "visual-left", "comparison", "statement"]


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
    minimum_gap_inches: float = 0.16
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
        gap = int(Inches(self.minimum_gap_inches))
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
) -> SlideLayoutPlan:
    """Return a safe, flat composition for a new 16:9 slide.

    The regions intentionally describe a small set of strong silhouettes,
    rather than a card grid. A slide should select one and fit its narrative
    into the regions before any shapes are created.
    """
    slide_width_emu = int(presentation.slide_width or 0)
    slide_height_emu = int(presentation.slide_height or 0)
    if slide_width_emu <= 0 or slide_height_emu <= 0:
        raise LayoutError("Presentation has invalid slide dimensions")
    slide_width = slide_width_emu / EMU_PER_INCH
    slide_height = slide_height_emu / EMU_PER_INCH
    margin = theme.margin_inches
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

    if name == "hero":
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
    return SlideLayoutPlan(name=name, safe_canvas=safe, title=title, content=content)


def estimate_text_fit(
    text: str,
    *,
    width: int,
    height: int,
    size: int,
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


def _apply_run(run, *, font: str, size: int, color: str, bold: bool) -> None:
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
    size: int,
    color: str,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
    vertical_anchor=MSO_ANCHOR.MIDDLE,
    margin_inches: float = 0.02,
    role: str = "body",
    max_lines: int | None = None,
    strict: bool = True,
    guard: LayoutGuard | None = None,
    ledger: QualityLedger | None = None,
):
    minimum_sizes = {
        "deck-title": 50,
        "title": 35,
        "subheading": 24,
        "body": 16,
        "caption": 10,
        "kicker": 10,
        "footer": 9,
    }
    active_ledger = ledger or (guard.ledger if guard is not None else None)

    def reject(message: str, error_type: type[LayoutError]) -> None:
        if active_ledger is None:
            raise error_type(message)
        active_ledger.error(message)

    minimum = minimum_sizes.get(role, 16)
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
    guard: LayoutGuard | None = None,
):
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
        size=theme.title_pt,
        color=theme.ink,
        bold=True,
        role="title",
        max_lines=1,
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
