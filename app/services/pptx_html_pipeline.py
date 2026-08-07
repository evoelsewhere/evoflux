"""HTML-first presentation rendering and hybrid PowerPoint assembly.

The pipeline deliberately separates creative composition from PowerPoint's
coordinate API. An agent authors bounded HTML/CSS on a fixed 16:9 canvas, the
EvoFlux Desktop WebView renders and inspects it, and the exporter places the
complex visual surface into PowerPoint while restoring semantic elements as
editable native objects.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Final, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from app.services.office.rendering import (
    PDFTOPPM_BIN_ENV,
    SOFFICE_BIN_ENV,
    render_pages,
    renderer_available,
)
from app.services.pptx_html_styles import (
    COMMON_PRESET_CSS,
    get_style_preset,
    style_catalog,
)
from app.services.pptx_html_templates import (
    EDITABLE_TEMPLATE_CSS,
    get_base_template,
    render_base_template,
    template_catalog,
)


CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 900
PPTX_WIDTH_IN = 13.333333
PPTX_HEIGHT_IN = 7.5
PPTX_POINTS_PER_PX = PPTX_HEIGHT_IN * 72 / CANVAS_HEIGHT
MAX_SLIDES = 40
# Backgrounds and editable images are embedded in the deck, so they carry the
# detail budget. Previews are only QA thumbnails and attachment cards.
EXPORT_PIXEL_RATIO = 2
PREVIEW_PIXEL_RATIO = 1
# The renderer is one WebView, so slides pipeline rather than fan out: each one
# holds a full-canvas bitmap while it encodes.
RENDER_CONCURRENCY = 3
# Editable text keeps its font name rather than its rendered pixels, so a family
# PowerPoint lacks gets substituted and reflows over the rendered background.
# These ship with Office or the host OS and all cover Vietnamese diacritics.
EXPORT_SAFE_FONTS = frozenset(
    {
        "Aptos",
        "Aptos Display",
        "Arial",
        "Calibri",
        "Calibri Light",
        "Cambria",
        "Consolas",
        "Courier New",
        "Georgia",
        "Segoe UI",
        "Tahoma",
        "Times New Roman",
        "Trebuchet MS",
        "Verdana",
    }
)
MAX_HTML_CHARS = 180_000
MAX_CSS_CHARS = 120_000
_ASSET_RE = re.compile(r"asset://([^\s\"'<>\)]+)")
_FORBIDDEN_CSS = re.compile(
    r"@import|javascript:|expression\s*\(|behavior\s*:",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_COLOR_RE = re.compile(r"rgba?\((\d+),\s*(\d+),\s*(\d+)")
_ALPHA_RE = re.compile(
    r"rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\s*\)",
    re.IGNORECASE,
)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT_STACK_RE = re.compile(r"^[a-zA-Z0-9 .,'\"_-]{1,200}$")


def _validate_css_value(value: str) -> None:
    if "<" in value or ">" in value:
        raise ValueError("CSS must not contain HTML delimiters")
    if _FORBIDDEN_CSS.search(value):
        raise ValueError("CSS contains an executable or imported rule")
    for match in _CSS_URL_RE.finditer(value):
        target = match.group(2).strip()
        if not target.startswith(("asset://", "data:image/")):
            raise ValueError(
                "CSS url() targets must use asset:// workspace images or data:image"
            )


DEFAULT_CSS = r"""
:root {
  --paper: #f7f5f0;
  --ink: #17242d;
  --muted: #64727b;
  --primary: #155e63;
  --accent: #e97335;
  --line: rgba(23, 36, 45, .18);
  --font-sans: "Aptos", "Inter", "Arial", sans-serif;
  --font-display: "Aptos Display", "Inter", "Arial", sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: transparent; }
body { font-family: var(--font-sans); color: var(--ink); }
.slide {
  position: relative;
  width: 1600px;
  height: 900px;
  overflow: hidden;
  background: var(--paper);
  color: var(--ink);
  isolation: isolate;
}
.safe { position: absolute; inset: 64px 84px; }
.kicker {
  margin: 0 0 18px;
  color: var(--primary);
  font-size: 22px;
  line-height: 1.1;
  font-weight: 750;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.title {
  margin: 0;
  max-width: 1380px;
  font-family: var(--font-display);
  font-size: 62px;
  line-height: 1.02;
  letter-spacing: -.035em;
  font-weight: 760;
}
.subtitle {
  margin: 22px 0 0;
  max-width: 1120px;
  color: var(--muted);
  font-size: 27px;
  line-height: 1.34;
}
.eyebrow-rule { width: 72px; height: 6px; background: var(--accent); margin-bottom: 22px; }
.hero { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 72px; align-items: center; height: 100%; }
.split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 58px; }
.three { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 34px; }
.stack { display: flex; flex-direction: column; gap: 28px; }
.flow { display: flex; align-items: stretch; gap: 22px; }
.panel { padding: 30px; border: 1px solid var(--line); background: rgba(255,255,255,.68); }
.panel h2, .panel h3 { margin: 0 0 14px; font-size: 27px; line-height: 1.12; }
.panel p, .panel li { font-size: 20px; line-height: 1.35; }
.metric { font-family: var(--font-display); font-size: 72px; line-height: .95; font-weight: 780; letter-spacing: -.04em; }
.label { color: var(--muted); font-size: 17px; line-height: 1.25; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.body { font-size: 22px; line-height: 1.42; }
.body p { margin: 0 0 18px; }
.body ul, .body ol { margin: 0; padding-left: 1.2em; }
.body li { margin: 0 0 12px; }
.quote { font-family: var(--font-display); font-size: 42px; line-height: 1.18; letter-spacing: -.02em; }
.rule { height: 1px; background: var(--line); }
.process { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 24px; align-items: stretch; }
.step { position: relative; padding: 28px 26px 26px; border-top: 5px solid var(--primary); background: rgba(255,255,255,.72); }
.step-number { color: var(--accent); font-size: 18px; font-weight: 800; }
.step h3 { margin: 16px 0 12px; font-size: 25px; }
.step p { margin: 0; color: var(--muted); font-size: 18px; line-height: 1.35; }
.footer { position: absolute; left: 84px; right: 84px; bottom: 34px; display: flex; justify-content: space-between; color: var(--muted); font-size: 14px; }
img { display: block; max-width: 100%; }
svg { display: block; }
table { width: 100%; border-collapse: collapse; font-size: 18px; }
th, td { border-bottom: 1px solid var(--line); padding: 13px 15px; text-align: left; vertical-align: top; }
th { color: var(--primary); font-size: 15px; text-transform: uppercase; letter-spacing: .05em; }
"""


class HtmlDeckTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: str | None = None
    ink: str | None = None
    muted: str | None = None
    primary: str | None = None
    accent: str | None = None
    font_sans: str | None = None
    font_display: str | None = None
    css: str = ""

    @field_validator("background", "ink", "muted", "primary", "accent")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _HEX_COLOR_RE.fullmatch(value):
            raise ValueError("theme colors must use six-digit hex notation")
        return value

    @field_validator("font_sans", "font_display")
    @classmethod
    def validate_font_stack(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _FONT_STACK_RE.fullmatch(value):
            raise ValueError("font stacks contain unsupported characters")
        return value

    @field_validator("css")
    @classmethod
    def validate_css(cls, value: str) -> str:
        if len(value) > MAX_CSS_CHARS:
            raise ValueError(f"theme.css exceeds {MAX_CSS_CHARS} characters")
        _validate_css_value(value)
        return value


class HtmlSlideSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=240)
    html: str | None = Field(default=None, min_length=1, max_length=MAX_HTML_CHARS)
    template: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    speaker_notes: str = ""
    sources: list[str] = Field(default_factory=list)
    style_preset: str | None = None
    kind: Literal[
        "cover",
        "content",
        "process",
        "comparison",
        "data",
        "architecture",
        "closing",
    ] = "content"

    @field_validator("html")
    @classmethod
    def validate_html(cls, value: str | None) -> str | None:
        if value is not None:
            validate_html_fragment(value)
        return value

    @model_validator(mode="after")
    def validate_authoring_source(self) -> HtmlSlideSpec:
        if (self.html is None) == (self.template is None):
            raise ValueError("each slide must define exactly one of html or template")
        if self.template is not None:
            get_base_template(self.template)
            rendered = render_base_template(self.template, self.title, self.content)
            validate_html_fragment(rendered)
        elif self.content:
            raise ValueError("slide content is only accepted with a base template")
        return self

    @field_validator("style_preset")
    @classmethod
    def validate_style_preset(cls, value: str | None) -> str | None:
        if value is not None:
            get_style_preset(value)
        return value


class HtmlDeckProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=240)
    language: str = "en"
    audience: str = ""
    communication_job: str = ""
    visual_direction: str = ""
    style_preset: str
    style_confirmed: Literal[True]
    editable_mode: Literal["explicit", "balanced", "max"] = "max"
    width: Literal[1600] = CANVAS_WIDTH
    height: Literal[900] = CANVAS_HEIGHT
    theme: HtmlDeckTheme = Field(default_factory=HtmlDeckTheme)
    slides: list[HtmlSlideSpec] = Field(min_length=1, max_length=MAX_SLIDES)
    min_body_px: int = Field(default=18, ge=14, le=28)
    min_title_px: int = Field(default=44, ge=32, le=72)
    max_words_per_slide: int = Field(default=120, ge=30, le=220)

    @model_validator(mode="after")
    def validate_unique_slides(self) -> HtmlDeckProject:
        identifiers = [slide.id for slide in self.slides]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("slide ids must be unique")
        return self

    @field_validator("style_preset")
    @classmethod
    def validate_style_preset(cls, value: str) -> str:
        get_style_preset(value)
        return value


class _SafetyParser(HTMLParser):
    _forbidden_tags = {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "link",
        "meta",
        "base",
        "form",
        "input",
        "button",
        "textarea",
        "video",
        "audio",
        "canvas",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in self._forbidden_tags:
            self.errors.append(f"forbidden <{tag}> element")
        for name, value in attrs:
            attr = name.casefold()
            raw = value or ""
            if attr.startswith("on"):
                self.errors.append(f"forbidden event attribute {name}")
            if attr in {"href", "src", "xlink:href"} and raw:
                allowed = raw.startswith(("asset://", "data:image/", "#"))
                if not allowed:
                    self.errors.append(
                        f"URL must use asset://, data:image, or a local fragment: {raw}"
                    )
            if attr == "style":
                try:
                    _validate_css_value(raw)
                except ValueError as exc:
                    self.errors.append(f"inline style is unsafe: {exc}")

    handle_startendtag = handle_starttag


def validate_html_fragment(fragment: str) -> None:
    parser = _SafetyParser()
    parser.feed(fragment)
    parser.close()
    if parser.errors:
        raise ValueError("; ".join(dict.fromkeys(parser.errors)))


@dataclass
class QaIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    slide_number: int
    element: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "slide_number": self.slide_number,
            "element": self.element,
        }


@dataclass
class SlideRender:
    number: int
    slide_id: str
    preview_path: Path
    background_path: Path
    native_text: list[dict[str, Any]]
    native_shapes: list[dict[str, Any]] = field(default_factory=list)
    native_images: list[dict[str, Any]] = field(default_factory=list)
    editability: dict[str, Any] = field(default_factory=dict)
    issues: list[QaIssue] = field(default_factory=list)


@dataclass
class HtmlDeckBuildResult:
    output: Path | None
    render_dir: Path
    slides: list[SlideRender]
    issues: list[QaIssue]
    round_trip: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        eligible_objects = sum(
            int(slide.editability.get("eligibleObjects", 0)) for slide in self.slides
        )
        promoted_objects = sum(
            int(slide.editability.get("promotedObjects", 0)) for slide in self.slides
        )
        rich_text_runs = sum(
            int(slide.editability.get("richTextRuns", 0)) for slide in self.slides
        )
        return {
            "passed": self.passed,
            "output": str(self.output) if self.output else None,
            "render_dir": str(self.render_dir),
            "round_trip": self.round_trip,
            "slide_count": len(self.slides),
            "renders": [str(slide.preview_path) for slide in self.slides],
            "backgrounds": [str(slide.background_path) for slide in self.slides],
            "native_text_count": sum(len(slide.native_text) for slide in self.slides),
            "native_shape_count": sum(
                len(slide.native_shapes) for slide in self.slides
            ),
            "native_image_count": sum(
                len(slide.native_images) for slide in self.slides
            ),
            "editable_object_count": sum(
                len(slide.native_text)
                + len(slide.native_shapes)
                + len(slide.native_images)
                for slide in self.slides
            ),
            "editability": {
                "eligible_objects": eligible_objects,
                "promoted_objects": promoted_objects,
                "coverage_percent": (
                    round(promoted_objects / eligible_objects * 100, 2)
                    if eligible_objects
                    else 100.0
                ),
                "rich_text_runs": rich_text_runs,
            },
            "errors": [
                issue.to_dict() for issue in self.issues if issue.severity == "error"
            ],
            "warnings": [
                issue.to_dict() for issue in self.issues if issue.severity == "warning"
            ],
        }


def load_html_deck_project(path: Path) -> HtmlDeckProject:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    return HtmlDeckProject.model_validate(data)


def html_catalog(
    style_preset: str | None = None,
    base_template: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "canvas": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT, "ratio": "16:9"},
        "workflow": ["outline", "style", "sample", "render", "qa", "compose"],
        "style_selection_gate": {
            "required_before_authoring": True,
            "silent_default": None,
            "recommended_first_option": "scientific-defense",
            "rule": (
                "Ask the user which visual style they want before writing or "
                "rendering slides. Do not create a project until the user confirms."
            ),
            "confirmation_field": (
                "Set style_confirmed=true only after the user explicitly selects "
                "or confirms the proposed style."
            ),
            "prompt": (
                "Which visual style would you like for this deck? I recommend "
                "Scientific Defense (academic navy and white with restrained red "
                "conclusions), or you can choose Professional, Consulting, Data "
                "Dashboard, Teaching, or Creative."
            ),
            "localization": "Ask in the user's current language; do not hard-code a locale.",
        },
        "native_export": {
            "editable_mode": {
                "max": "default; auto-promotes semantic text with inline runs, data-box regions, rules, and images",
                "balanced": "auto-promotes semantic text with inline runs and images; shapes require markers",
                "explicit": "only data-pptx-native markers are exported",
            },
            "markers": {
                "text": 'data-pptx-native="text"',
                "shape": 'data-pptx-native="shape"',
                "image": 'data-pptx-native="image"',
                "line": 'data-pptx-native="line"',
                "shape_type": 'data-pptx-shape="rect|roundRect|ellipse"',
                "selection_name": "data-pptx-name gives the object a useful PowerPoint Selection Pane name",
                "raster_opt_out": "data-pptx-raster",
            },
            "behavior": "supported objects are removed from the rendered background and recreated as individually editable PowerPoint objects; text preserves inline font, size, weight, italic, underline, strike, color, tracking, line breaks, and list markers",
            "coverage": "qa.json reports eligible objects, promoted objects, percentage coverage, and preserved rich-text run count",
        },
        "qa_markers": {
            "box": "data-box marks structural regions for collision checks",
            "overlap": 'data-overlap="allow" permits an intentional overlap',
            "ignore": "data-qa-ignore skips an element from bounds/text checks",
            "density": 'data-qa-density="allow" permits a deliberately dense structure such as a data table',
            "role": 'data-pptx-role="title" applies the title font floor',
        },
        "built_in_classes": [
            "slide",
            "safe",
            "kicker",
            "title",
            "subtitle",
            "hero",
            "split",
            "three",
            "stack",
            "flow",
            "panel",
            "metric",
            "label",
            "body",
            "quote",
            "process",
            "step",
            "footer",
        ],
        "constraints": [
            "One .slide root is injected by the renderer; slide HTML must contain only its inner composition.",
            "No scripts, iframes, forms, remote URLs, @import, or network CSS.",
            "Use asset://relative/path for workspace-local raster or SVG assets.",
            "Keep important text at or above the configured font floors.",
            "Default editable_mode=max promotes common text, cards, rules, and images automatically.",
            "Use data-pptx-raster on transformed, gradient, clipped, or decorative elements that must remain pixel-stable.",
        ],
        "style_system": style_catalog(style_preset),
        "base_template_system": template_catalog(base_template),
    }


def _embed_assets(text: str, *, project_dir: Path, workspace_root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        relative = match.group(1)
        candidate = (project_dir / relative).resolve()
        try:
            candidate.relative_to(workspace_root.resolve())
        except ValueError as exc:
            raise ValueError(f"asset escapes workspace: asset://{relative}") from exc
        if not candidate.is_file():
            raise FileNotFoundError(f"asset does not exist: {candidate}")
        media_type = (
            mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        if not media_type.startswith("image/"):
            raise ValueError(f"asset must be an image: {candidate}")
        payload = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"data:{media_type};base64,{payload}"

    return _ASSET_RE.sub(replace, text)


def _theme_css(theme: HtmlDeckTheme, style_preset: str) -> str:
    preset = get_style_preset(style_preset)
    tokens = {
        "paper": theme.background,
        "ink": theme.ink,
        "muted": theme.muted,
        "primary": theme.primary,
        "accent": theme.accent,
        "font-sans": theme.font_sans,
        "font-display": theme.font_display,
    }
    declarations = "\n".join(
        f"  --{name}: {value};" for name, value in tokens.items() if value is not None
    )
    overrides = (
        f"\n.slide.style-{style_preset} {{\n{declarations}\n}}\n"
        if declarations
        else ""
    )
    return (
        DEFAULT_CSS
        + COMMON_PRESET_CSS
        + EDITABLE_TEMPLATE_CSS
        + preset.css
        + overrides
        + theme.css
    )


def _document_html(
    project: HtmlDeckProject,
    slide: HtmlSlideSpec,
    *,
    project_dir: Path,
    workspace_root: Path,
) -> str:
    style_preset = slide.style_preset or project.style_preset
    css = _embed_assets(
        _theme_css(project.theme, style_preset),
        project_dir=project_dir,
        workspace_root=workspace_root,
    )
    fragment_source = (
        slide.html
        if slide.html is not None
        else render_base_template(str(slide.template), slide.title, slide.content)
    )
    fragment = _embed_assets(
        fragment_source,
        project_dir=project_dir,
        workspace_root=workspace_root,
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=1600">
<title>{escape(slide.title)}</title><style>{css}</style></head>
<body><section class="slide style-{style_preset}" data-style-preset="{style_preset}" data-slide-id="{escape(slide.id)}" data-slide-kind="{slide.kind}">{fragment}</section></body></html>"""


_INSPECTION_SCRIPT = r"""
({ minBodyPx, minTitlePx, maxWords, editableMode, fontAllowlist }) => {
  const slide = document.querySelector('.slide');
  const slideRect = slide.getBoundingClientRect();
  const issues = [];
  const label = (el) => el.id || el.getAttribute('data-pptx-role') || el.className || el.tagName;
  // Mirrors _font_name on the Python side: the exported run keeps only the first
  // family of the stack, so that is the name PowerPoint has to resolve.
  const firstFamily = (value) => String(value || '').split(',')[0].trim().replace(/^["']|["']$/g, '');
  const outside = (rect) => rect.left < slideRect.left - 1 || rect.top < slideRect.top - 1 || rect.right > slideRect.right + 1 || rect.bottom > slideRect.bottom + 1;
  const textSelector = 'h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,th,td,[data-pptx-native="text"]';
  slide.querySelectorAll(textSelector).forEach((el) => {
    if (el.closest('[data-qa-ignore]')) return;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const text = (el.innerText || '').trim();
    if (!text || style.display === 'none' || style.visibility === 'hidden') return;
    if (outside(rect)) issues.push({ severity: 'error', code: 'out_of_bounds', message: 'Text extends beyond the slide canvas.', element: label(el) });
    const range = document.createRange();
    range.selectNodeContents(el);
    const contentRect = range.getBoundingClientRect();
    if (outside(contentRect)) issues.push({ severity: 'error', code: 'text_glyph_out_of_bounds', message: 'Rendered text glyphs extend beyond the slide canvas.', element: label(el) });
    const size = parseFloat(style.fontSize || '0');
    const glyphTolerance = Math.max(6, size * .20);
    if (contentRect.left < rect.left - glyphTolerance || contentRect.top < rect.top - glyphTolerance || contentRect.right > rect.right + glyphTolerance || contentRect.bottom > rect.bottom + glyphTolerance) issues.push({ severity: 'error', code: 'text_overflow', message: 'Text overflows its element box.', element: label(el) });
    const metadata = el.matches('.preset-tag,.preset-micro,.label,.footer,.footer *');
    const floor = el.matches('h1,.title,[data-pptx-role="title"]') ? minTitlePx : (metadata ? Math.min(13, minBodyPx) : minBodyPx);
    if (size && size < floor) issues.push({ severity: 'warning', code: 'small_text', message: `Font size ${size.toFixed(1)}px is below ${floor}px.`, element: label(el) });
  });
  slide.querySelectorAll('img').forEach((el) => {
    if (!el.complete || !el.naturalWidth) issues.push({ severity: 'error', code: 'broken_image', message: 'Image failed to load.', element: label(el) });
    if (outside(el.getBoundingClientRect())) issues.push({ severity: 'error', code: 'image_out_of_bounds', message: 'Image extends beyond the slide canvas.', element: label(el) });
  });
  const boxes = [...slide.querySelectorAll('[data-box]')].filter((el) => !el.closest('[data-qa-ignore]'));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.contains(b) || b.contains(a) || a.dataset.overlap === 'allow' || b.dataset.overlap === 'allow') continue;
    const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
    const w = Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.left, br.left));
    const h = Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top));
    const overlap = w * h;
    const smaller = Math.min(ar.width * ar.height, br.width * br.height);
    if (smaller > 0 && overlap / smaller > .12) issues.push({ severity: 'error', code: 'box_overlap', message: 'Structural regions overlap by more than 12%.', element: `${label(a)} <> ${label(b)}` });
  }
  const words = (slide.innerText || '').trim().split(/\s+/).filter(Boolean).length;
  if (words > maxWords) issues.push({ severity: 'warning', code: 'dense_copy', message: `Slide contains ${words} words; target maximum is ${maxWords}.`, element: 'slide' });
  if (boxes.length > 9 && !slide.querySelector('[data-qa-density="allow"]')) issues.push({ severity: 'warning', code: 'panel_density', message: `Slide declares ${boxes.length} structural boxes; simplify the composition.`, element: 'slide' });
  const domOrder = new Map([...slide.querySelectorAll('*')].map((el, index) => [el, index]));
  const rasterized = (el) => Boolean(el.closest('[data-pptx-raster]'));
  const unique = (items) => [...new Set(items)];
  const textStyle = (el) => {
    const style = getComputedStyle(el);
    return {
      fontFamily: style.fontFamily,
      fontSize: parseFloat(style.fontSize || '20'),
      fontWeight: style.fontWeight,
      fontStyle: style.fontStyle,
      textDecoration: style.textDecorationLine,
      letterSpacing: style.letterSpacing,
      color: style.color,
    };
  };
  const sameRunStyle = (a, b) => a.fontFamily === b.fontFamily
    && a.fontSize === b.fontSize
    && a.fontWeight === b.fontWeight
    && a.fontStyle === b.fontStyle
    && a.textDecoration === b.textDecoration
    && a.letterSpacing === b.letterSpacing
    && a.color === b.color;
  const inlineRuns = (root) => {
    const runs = [];
    const append = (text, style) => {
      if (!text) return;
      const normalized = text.replace(/[\t\r\f\v ]+/g, ' ');
      if (!normalized) return;
      const previous = runs[runs.length - 1];
      if (previous && sameRunStyle(previous, style)) previous.text += normalized;
      else runs.push({ text: normalized, ...style });
    };
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        append(node.nodeValue || '', textStyle(node.parentElement || root));
        return;
      }
      if (!(node instanceof Element)) return;
      if (node.tagName === 'BR') {
        append('\n', textStyle(node.parentElement || root));
        return;
      }
      [...node.childNodes].forEach(walk);
    };
    [...root.childNodes].forEach(walk);
    if (!runs.length) return [];
    runs[0].text = runs[0].text.replace(/^\s+/, '');
    runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/\s+$/, '');
    return runs.filter((run) => run.text);
  };
  const semanticTextSelector = 'h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,th,td';
  const explicitText = [...slide.querySelectorAll('[data-pptx-native="text"]')];
  explicitText.forEach((el) => {
    if (el.parentElement && el.parentElement.closest('[data-pptx-native="text"]')) issues.push({ severity: 'error', code: 'nested_native_text', message: 'Editable text markers must not be nested.', element: label(el) });
  });
  const automaticText = editableMode === 'explicit' ? [] : [...slide.querySelectorAll(semanticTextSelector)].filter((el) => !el.querySelector(semanticTextSelector));
  const nativeElements = unique([...explicitText, ...automaticText]).filter((el) => !rasterized(el));
  nativeElements.forEach((el, index) => el.setAttribute('data-pptx-export-text', String(index)));
  const nativeText = nativeElements.map((el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const runs = inlineRuns(el);
    const list = el.tagName === 'LI' ? el.closest('ol,ul') : null;
    const listItems = list ? [...list.children].filter((child) => child.tagName === 'LI') : [];
    const listIndex = list ? Math.max(0, listItems.indexOf(el)) : 0;
    const listStart = list && list.tagName === 'OL' ? parseInt(list.getAttribute('start') || '1', 10) : 1;
    return {
      text: (el.innerText || '').trim(),
      runs,
      role: el.getAttribute('data-pptx-role') || '',
      listMarker: list ? (list.tagName === 'OL' ? `${listStart + listIndex}.` : '•') : '',
      x: rect.left - slideRect.left,
      y: rect.top - slideRect.top,
      width: rect.width,
      height: rect.height,
      fontFamily: style.fontFamily,
      fontSize: parseFloat(style.fontSize || '20'),
      fontWeight: style.fontWeight,
      fontStyle: style.fontStyle,
      letterSpacing: style.letterSpacing,
      color: style.color,
      textAlign: style.textAlign,
      lineHeight: style.lineHeight,
      paddingLeft: parseFloat(style.paddingLeft || '0'),
      paddingRight: parseFloat(style.paddingRight || '0'),
      paddingTop: parseFloat(style.paddingTop || '0'),
      paddingBottom: parseFloat(style.paddingBottom || '0'),
      order: domOrder.get(el) || 0
    };
  }).filter((item) => item.text);

  const allowedFonts = new Set((fontAllowlist || []).map((name) => name.toLowerCase()));
  if (allowedFonts.size) {
    unique(nativeText.map((item) => firstFamily(item.fontFamily)))
      .filter((name) => name && !allowedFonts.has(name.toLowerCase()))
      .forEach((name) => issues.push({
        severity: 'warning',
        code: 'font_not_export_safe',
        message: `Editable text uses "${name}", which PowerPoint may not have installed. It would substitute another font and reflow the text over the rendered background. Use an export-safe family or mark the element data-pptx-raster to keep the look as pixels.`,
        element: name,
      }));
  }

  const explicitShapes = [...slide.querySelectorAll('[data-pptx-native="shape"],[data-pptx-native="line"]')];
  const automaticShapes = editableMode === 'max' ? [...slide.querySelectorAll('[data-box],.panel,.step,.rule,[data-pptx-line]')] : [];
  const shapeElements = unique([...explicitShapes, ...automaticShapes]).filter((el) => !rasterized(el));
  const nativeShapes = [];
  let eligibleShapeObjects = 0;
  shapeElements.forEach((el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const explicit = el.hasAttribute('data-pptx-native');
    const unsupported = style.transform !== 'none' || style.backgroundImage !== 'none' || style.clipPath !== 'none' || style.filter !== 'none';
    if (unsupported) {
      eligibleShapeObjects += 1;
      if (explicit) issues.push({ severity: 'warning', code: 'native_shape_raster_fallback', message: 'A transformed, gradient, clipped, or filtered shape stays in the raster layer.', element: label(el) });
      return;
    }
    const fill = style.backgroundColor;
    const borderWidths = [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth].map((value) => parseFloat(value || '0'));
    const borderStyles = [style.borderTopStyle, style.borderRightStyle, style.borderBottomStyle, style.borderLeftStyle];
    const borderColors = [style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor];
    const borderWidth = Math.max(...borderWidths);
    const borderStyle = style.borderTopStyle;
    const uniformBorder = borderWidths.every((value) => Math.abs(value - borderWidths[0]) < .1) && borderStyles.every((value) => value === borderStyles[0]) && borderColors.every((value) => value === borderColors[0]);
    const hasFill = fill && fill !== 'transparent' && fill !== 'rgba(0, 0, 0, 0)';
    const hasBorder = borderWidth > 0 && borderStyle !== 'none' && borderStyle !== 'hidden';
    const lineLike = el.getAttribute('data-pptx-native') === 'line' || el.hasAttribute('data-pptx-line') || el.classList.contains('rule');
    if (!lineLike && !uniformBorder) {
      if (hasFill || hasBorder || explicit) eligibleShapeObjects += 1;
      if (explicit) issues.push({ severity: 'warning', code: 'native_shape_raster_fallback', message: 'A shape with asymmetric borders stays in the raster layer.', element: label(el) });
      return;
    }
    if (!hasFill && !hasBorder && !lineLike) return;
    eligibleShapeObjects += 1;
    const radius = parseFloat(style.borderTopLeftRadius || '0');
    let shapeType = el.getAttribute('data-pptx-shape') || 'rect';
    if (!el.hasAttribute('data-pptx-shape')) {
      if (radius >= Math.min(rect.width, rect.height) * .45) shapeType = 'ellipse';
      else if (radius > 3) shapeType = 'roundRect';
    }
    const exportId = String(nativeShapes.length);
    el.setAttribute('data-pptx-export-shape', exportId);
    nativeShapes.push({
      type: lineLike ? 'line' : 'shape',
      shapeType,
      x: rect.left - slideRect.left,
      y: rect.top - slideRect.top,
      width: rect.width,
      height: rect.height,
      fill,
      borderColor: style.borderTopColor,
      borderWidth,
      borderStyle,
      opacity: parseFloat(style.opacity || '1'),
      name: el.getAttribute('data-pptx-name') || label(el),
      order: domOrder.get(el) || 0
    });
  });

  const explicitImages = [...slide.querySelectorAll('[data-pptx-native="image"]')];
  const automaticImages = editableMode === 'explicit' ? [] : [...slide.querySelectorAll('img')];
  const imageElements = unique([...explicitImages, ...automaticImages]).filter((el) => !rasterized(el));
  const nativeImages = imageElements.map((el, index) => {
    const rect = el.getBoundingClientRect();
    el.setAttribute('data-pptx-export-image', String(index));
    return {
      exportId: String(index),
      x: rect.left - slideRect.left,
      y: rect.top - slideRect.top,
      width: rect.width,
      height: rect.height,
      name: el.getAttribute('data-pptx-name') || el.getAttribute('alt') || label(el),
      order: domOrder.get(el) || 0
    };
  });
  const eligibleObjects = nativeElements.length + eligibleShapeObjects + imageElements.length;
  const promotedObjects = nativeText.length + nativeShapes.length + nativeImages.length;
  const richTextRuns = nativeText.reduce((total, item) => total + item.runs.length, 0);
  if (eligibleObjects && promotedObjects / eligibleObjects < .85) {
    issues.push({
      severity: 'warning',
      code: 'editable_coverage_low',
      message: `Only ${promotedObjects} of ${eligibleObjects} eligible HTML elements became editable PowerPoint objects. Mark unsupported decoration data-pptx-raster or simplify its CSS.`,
      element: 'slide',
    });
  }
  return {
    issues,
    nativeText,
    nativeShapes,
    nativeImages,
    editability: { eligibleObjects, promotedObjects, richTextRuns },
  };
}
"""


def _write_png_data_url(value: Any, path: Path) -> None:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise ValueError("Desktop presentation renderer returned invalid PNG data")
    try:
        payload = base64.b64decode(value.partition(",")[2], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Desktop presentation renderer returned invalid base64"
        ) from exc
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Desktop presentation renderer returned a non-PNG image")
    path.write_bytes(payload)


async def render_html_deck(
    project: HtmlDeckProject,
    *,
    session_id: str,
    project_file: Path,
    workspace_root: Path,
    render_dir: Path,
    slide_numbers: list[int] | None = None,
) -> HtmlDeckBuildResult:
    from app.services.desktop_presentation_bridge import desktop_presentation_bridge

    render_dir = Path(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    selected = set(slide_numbers or range(1, len(project.slides) + 1))
    invalid = sorted(
        number for number in selected if number < 1 or number > len(project.slides)
    )
    if invalid:
        raise ValueError(f"slide_numbers out of range: {invalid}")

    inspection_params = {
        "minBodyPx": project.min_body_px,
        "minTitlePx": project.min_title_px,
        "maxWords": project.max_words_per_slide,
        "editableMode": project.editable_mode,
        "fontAllowlist": sorted(EXPORT_SAFE_FONTS),
    }
    canvas = {
        "width": CANVAS_WIDTH,
        "height": CANVAS_HEIGHT,
        "exportPixelRatio": EXPORT_PIXEL_RATIO,
        "previewPixelRatio": PREVIEW_PIXEL_RATIO,
    }
    limit = asyncio.Semaphore(RENDER_CONCURRENCY)

    async def render_slide(number: int, slide: HtmlSlideSpec) -> SlideRender:
        document = _document_html(
            project,
            slide,
            project_dir=Path(project_file).parent,
            workspace_root=workspace_root,
        )
        async with limit:
            response = await desktop_presentation_bridge.render(
                session_id,
                document=document,
                inspection_script=_INSPECTION_SCRIPT,
                inspection_params=inspection_params,
                canvas=canvas,
            )
        if not isinstance(response, dict) or not isinstance(
            response.get("inspection"), dict
        ):
            raise ValueError("Desktop presentation renderer returned invalid output")
        inspection = response["inspection"]
        issues = [
            QaIssue(
                severity=item["severity"],
                code=item["code"],
                message=item["message"],
                slide_number=number,
                element=str(item.get("element", "")),
            )
            for item in inspection.get("issues", [])
        ]
        preview_path = render_dir / f"slide_{number:02d}.png"
        background_path = render_dir / f"slide_{number:02d}.background.png"
        _write_png_data_url(response.get("preview"), preview_path)
        _write_png_data_url(response.get("background"), background_path)

        image_data = response.get("nativeImages", [])
        if not isinstance(image_data, list):
            raise ValueError("Desktop presentation renderer returned invalid images")
        by_export_id = {
            item.get("exportId"): item.get("data")
            for item in image_data
            if isinstance(item, dict)
        }
        native_images: list[dict[str, Any]] = []
        for image_index, item in enumerate(inspection.get("nativeImages", []), start=1):
            image_path = render_dir / (
                f"slide_{number:02d}.editable_image_{image_index:02d}.png"
            )
            _write_png_data_url(by_export_id.get(item["exportId"]), image_path)
            native_images.append({**item, "path": str(image_path)})

        return SlideRender(
            number=number,
            slide_id=slide.id,
            preview_path=preview_path,
            background_path=background_path,
            native_text=list(inspection.get("nativeText", [])),
            native_shapes=list(inspection.get("nativeShapes", [])),
            native_images=native_images,
            editability=dict(inspection.get("editability", {})),
            issues=issues,
        )

    rendered = list(
        await asyncio.gather(
            *(
                render_slide(number, slide)
                for number, slide in enumerate(project.slides, start=1)
                if number in selected
            )
        )
    )
    all_issues = [issue for slide_render in rendered for issue in slide_render.issues]

    report = HtmlDeckBuildResult(
        output=None,
        render_dir=render_dir,
        slides=rendered,
        issues=all_issues,
    )
    (render_dir / "qa.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _rgb(value: str) -> tuple[int, int, int]:
    match = _COLOR_RE.search(value)
    if match:
        red, green, blue = (max(0, min(255, int(item))) for item in match.groups())
        return red, green, blue
    if value.startswith("#") and len(value) in {4, 7}:
        raw = value[1:]
        if len(raw) == 3:
            raw = "".join(char * 2 for char in raw)
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return 23, 36, 45


def _font_name(value: str) -> str:
    first = value.split(",", 1)[0].strip().strip("'\"")
    return first or "Aptos"


def _text_lines(item: dict[str, Any]) -> list[list[dict[str, Any]]]:
    raw_runs = item.get("runs")
    runs = (
        [run for run in raw_runs if isinstance(run, dict)]
        if isinstance(raw_runs, list)
        else []
    )
    if not runs:
        runs = [{"text": str(item.get("text", ""))}]
    lines: list[list[dict[str, Any]]] = [[]]
    for raw_run in runs:
        run_text = str(raw_run.get("text", ""))
        for index, part in enumerate(run_text.split("\n")):
            if index:
                lines.append([])
            if part:
                lines[-1].append({**raw_run, "text": part})
    marker = str(item.get("listMarker", "")).strip()
    if marker:
        lines[0].insert(0, {"text": f"{marker} "})
    return lines or [[]]


def _format_text_run(run: Any, style: dict[str, Any], fallback: dict[str, Any]) -> None:
    font_family = str(style.get("fontFamily") or fallback.get("fontFamily") or "Aptos")
    font_size = float(style.get("fontSize") or fallback.get("fontSize") or 20)
    color = str(style.get("color") or fallback.get("color") or "")
    red, green, blue = _rgb(color)
    run.font.name = _font_name(font_family)
    run.font.size = Pt(font_size * PPTX_POINTS_PER_PX)
    weight = str(style.get("fontWeight") or fallback.get("fontWeight") or "400")
    run.font.bold = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
    run.font.italic = (
        str(style.get("fontStyle") or fallback.get("fontStyle") or "normal") == "italic"
    )
    decoration = str(
        style.get("textDecoration") or fallback.get("textDecoration") or ""
    )
    run.font.underline = "underline" in decoration
    run.font.color.rgb = RGBColor(red, green, blue)
    properties = run._r.get_or_add_rPr()
    if "line-through" in decoration:
        properties.set("strike", "sngStrike")
    letter_spacing = str(
        style.get("letterSpacing") or fallback.get("letterSpacing") or ""
    )
    spacing_match = re.match(r"(-?[0-9.]+)px$", letter_spacing)
    if spacing_match:
        properties.set(
            "spc",
            str(round(float(spacing_match.group(1)) * PPTX_POINTS_PER_PX * 100)),
        )


def _populate_text_frame(frame: Any, item: dict[str, Any]) -> None:
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.TOP
    text_align = str(item.get("textAlign", "left"))
    font_size = float(item.get("fontSize", 20))
    line_height = str(item.get("lineHeight", ""))
    line_height_match = re.match(r"([0-9.]+)px$", line_height)
    for index, line_runs in enumerate(_text_lines(item)):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = {
            "center": PP_ALIGN.CENTER,
            "right": PP_ALIGN.RIGHT,
            "justify": PP_ALIGN.JUSTIFY,
        }.get(text_align, PP_ALIGN.LEFT)
        if line_height_match and font_size > 0:
            paragraph.line_spacing = max(
                0.8,
                min(2.0, float(line_height_match.group(1)) / font_size),
            )
        for run_style in line_runs:
            run = paragraph.add_run()
            run.text = str(run_style.get("text", ""))
            _format_text_run(run, run_style, item)


def _is_transparent(value: str) -> bool:
    lowered = value.strip().casefold()
    if lowered in {"", "transparent"}:
        return True
    alpha_match = re.search(r"rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)", lowered)
    return bool(alpha_match and float(alpha_match.group(1)) <= 0.01)


def _alpha(value: str) -> float:
    match = _ALPHA_RE.search(value)
    if not match:
        return 1.0
    return max(0.0, min(1.0, float(match.group(1))))


def _set_drawingml_alpha(root: Any, opacity: float) -> None:
    if opacity >= 0.999:
        return
    nodes = root.xpath(".//a:srgbClr")
    if not nodes:
        return
    alpha = OxmlElement("a:alpha")
    alpha.set("val", str(round(max(0.0, min(1.0, opacity)) * 100_000)))
    nodes[-1].append(alpha)


def _px(value: float) -> Inches:
    return Inches(float(value) / CANVAS_WIDTH * PPTX_WIDTH_IN)


def _add_native_shape(slide: Any, item: dict[str, Any]) -> None:
    width_px = max(1.0, float(item["width"]))
    height_px = max(1.0, float(item["height"]))
    if item.get("type") == "line":
        thickness = max(height_px, float(item.get("borderWidth", 0)), 1.0)
        if height_px > width_px:
            width_px = max(width_px, float(item.get("borderWidth", 0)), 1.0)
        else:
            height_px = thickness
    shape_type = {
        "ellipse": MSO_AUTO_SHAPE_TYPE.OVAL,
        "roundRect": MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE,
    }.get(str(item.get("shapeType", "rect")), MSO_AUTO_SHAPE_TYPE.RECTANGLE)
    shape = slide.shapes.add_shape(
        shape_type,
        _px(float(item["x"])),
        _px(float(item["y"])),
        _px(width_px),
        _px(height_px),
    )
    object_name = str(item.get("name", "Editable object"))[:80]
    shape.name = f"[evoflux-html][role:{item.get('type', 'shape')}] {object_name}"
    fill_value = str(item.get("fill", ""))
    if item.get("type") == "line" and _is_transparent(fill_value):
        fill_value = str(item.get("borderColor", ""))
    if _is_transparent(fill_value):
        shape.fill.background()
    else:
        red, green, blue = _rgb(fill_value)
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(red, green, blue)
        _set_drawingml_alpha(
            shape.fill._xPr,
            _alpha(fill_value) * float(item.get("opacity", 1)),
        )
    border_width = float(item.get("borderWidth", 0))
    border_value = str(item.get("borderColor", ""))
    if item.get("type") == "line" or border_width <= 0 or _is_transparent(border_value):
        shape.line.fill.background()
    else:
        red, green, blue = _rgb(border_value)
        shape.line.color.rgb = RGBColor(red, green, blue)
        shape.line.width = Pt(border_width * PPTX_POINTS_PER_PX)
        _set_drawingml_alpha(
            shape.line._get_or_add_ln(),
            _alpha(border_value) * float(item.get("opacity", 1)),
        )


def _add_native_image(slide: Any, item: dict[str, Any]) -> None:
    image_path = Path(str(item["path"]))
    with Image.open(image_path) as image:
        image.verify()
    picture = slide.shapes.add_picture(
        str(image_path),
        _px(float(item["x"])),
        _px(float(item["y"])),
        width=_px(max(1.0, float(item["width"]))),
        height=_px(max(1.0, float(item["height"]))),
    )
    object_name = str(item.get("name", "Editable picture"))[:80]
    picture.name = f"[evoflux-html][role:image] {object_name}"


def _notes(slide: HtmlSlideSpec) -> str:
    notes = slide.speaker_notes.strip()
    if slide.sources:
        sources = "[Sources]\n" + "\n".join(f"- {source}" for source in slide.sources)
        notes = f"{notes}\n\n{sources}".strip()
    return notes


def assemble_hybrid_pptx(
    project: HtmlDeckProject,
    renders: list[SlideRender],
    output: Path,
) -> Path:
    if len(renders) != len(project.slides):
        raise ValueError("all slides must be rendered before composition")
    presentation = Presentation()
    presentation.slide_width = Inches(PPTX_WIDTH_IN)
    presentation.slide_height = Inches(PPTX_HEIGHT_IN)
    blank = presentation.slide_layouts[6]

    by_number = {render.number: render for render in renders}
    for number, slide_spec in enumerate(project.slides, start=1):
        render = by_number[number]
        with Image.open(render.background_path) as image:
            image.verify()
        slide = presentation.slides.add_slide(blank)
        background = slide.shapes.add_picture(
            str(render.background_path),
            left=0,
            top=0,
            width=presentation.slide_width,
            height=presentation.slide_height,
        )
        background.name = f"Rendered background — {slide_spec.title}"
        background._element.nvPicPr.cNvPr.set(
            "descr",
            f"Rendered visual background for slide {number}: {slide_spec.title}",
        )

        for item in sorted(
            render.native_shapes,
            key=lambda value: int(value.get("order", 0)),
        ):
            _add_native_shape(slide, item)

        for item in sorted(
            render.native_images,
            key=lambda value: int(value.get("order", 0)),
        ):
            _add_native_image(slide, item)

        for item in sorted(
            render.native_text,
            key=lambda value: int(value.get("order", 0)),
        ):
            left_px = float(item["x"]) + float(item.get("paddingLeft", 0))
            top_px = float(item["y"]) + float(item.get("paddingTop", 0))
            width_px = max(
                1.0,
                float(item["width"])
                - float(item.get("paddingLeft", 0))
                - float(item.get("paddingRight", 0)),
            )
            height_px = max(
                1.0,
                float(item["height"])
                - float(item.get("paddingTop", 0))
                - float(item.get("paddingBottom", 0)),
            )
            role = str(item.get("role", ""))
            text_align = str(item.get("textAlign", "left"))
            font_size = float(item.get("fontSize", 20))
            width_buffer = 64.0 if role == "title" else 8.0
            if text_align == "right":
                left_px -= width_buffer
            elif text_align == "center":
                left_px -= width_buffer / 2
            left_px = max(0.0, left_px)
            width_px = min(CANVAS_WIDTH - left_px, width_px + width_buffer)
            height_px = min(
                CANVAS_HEIGHT - top_px,
                height_px + max(8.0, font_size * 0.25),
            )
            shape = slide.shapes.add_textbox(
                Inches(left_px / CANVAS_WIDTH * PPTX_WIDTH_IN),
                Inches(top_px / CANVAS_HEIGHT * PPTX_HEIGHT_IN),
                Inches(width_px / CANVAS_WIDTH * PPTX_WIDTH_IN),
                Inches(height_px / CANVAS_HEIGHT * PPTX_HEIGHT_IN),
            )
            shape.name = (
                f"[evoflux-html][role:{role or 'text'}] {str(item['text'])[:60]}"
            )
            _populate_text_frame(shape.text_frame, item)

        note_text = _notes(slide_spec)
        if note_text:
            notes_frame = slide.notes_slide.notes_text_frame
            notes_frame.clear()
            notes_frame.text = note_text

    presentation.core_properties.title = project.title
    presentation.core_properties.subject = (
        "HTML-first hybrid presentation generated by EvoFlux"
    )
    presentation.core_properties.keywords = "EvoFlux, HTML-first, hybrid PowerPoint"

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{output.stem}.",
        suffix=".pptx",
        dir=output.parent,
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        presentation.save(str(temp_path))
        reopened = Presentation(str(temp_path))
        if len(reopened.slides) != len(project.slides):
            raise RuntimeError(
                "PowerPoint verification found an unexpected slide count"
            )
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return output


# Round-trip verification compares a coarse grayscale signature rather than
# pixels. LibreOffice and Chromium hint and antialias text differently, so only
# low-frequency structure is comparable between them: a block of text that moved,
# vanished, or overlapped changes the signature, while rasterisation does not.
_SIGNATURE_SIZE: Final = (64, 36)
# Provisional, and reported alongside every measurement so it can be retuned
# against real decks instead of guessed at again.
_MAX_SIGNATURE_DRIFT: Final = 0.18
_ROUND_TRIP_DPI: Final = 96


def _signature(path: Path) -> bytes:
    with Image.open(path) as image:
        coarse = image.convert("L").resize(_SIGNATURE_SIZE, Image.Resampling.BILINEAR)
        return coarse.tobytes()


def _signature_drift(designed: Path, exported: Path) -> float:
    left = _signature(designed)
    right = _signature(exported)
    total = sum(abs(a - b) for a, b in zip(left, right, strict=True))
    return total / (len(left) * 255)


def verify_exported_deck(
    output: Path,
    slides: list[SlideRender],
    render_dir: Path,
) -> tuple[list[QaIssue], dict[str, Any]]:
    """Compares the written deck against the previews the WebView produced.

    Every other check runs on the HTML before export, so this is the only step
    that sees what PowerPoint will actually open. It reports rather than blocks:
    LibreOffice substitutes fonts of its own, so a difference is a prompt to look
    at both images, not proof the deck is wrong.
    """

    if not renderer_available():
        return [], {
            "status": "skipped",
            "reason": (
                "LibreOffice is unavailable, so the exported deck was not "
                f"rasterised. Set {SOFFICE_BIN_ENV} and {PDFTOPPM_BIN_ENV} to "
                "compare the written deck against the designed previews."
            ),
        }
    pages, render_issues = render_pages(
        output,
        render_dir,
        code_prefix="pptx",
        dpi=_ROUND_TRIP_DPI,
    )
    if render_issues:
        reason = render_issues[0]["message"]
        return [
            QaIssue(
                severity="warning",
                code="round_trip_render_failed",
                message=(
                    f"The exported deck could not be rasterised for verification: {reason}"
                ),
                slide_number=0,
            )
        ], {"status": "failed", "reason": reason}

    issues: list[QaIssue] = []
    if len(pages) != len(slides):
        issues.append(
            QaIssue(
                severity="warning",
                code="round_trip_page_count",
                message=(
                    f"The exported deck rasterised to {len(pages)} pages but the "
                    f"project has {len(slides)} slides."
                ),
                slide_number=0,
            )
        )
    measurements: list[dict[str, Any]] = []
    for slide_render, page in zip(slides, pages, strict=False):
        drift = _signature_drift(slide_render.preview_path, page)
        measurements.append(
            {
                "slide_number": slide_render.number,
                "difference": round(drift, 4),
                "designed": str(slide_render.preview_path),
                "exported": str(page),
            }
        )
        if drift <= _MAX_SIGNATURE_DRIFT:
            continue
        issues.append(
            QaIssue(
                severity="warning",
                code="round_trip_drift",
                message=(
                    f"The exported slide differs from its designed preview "
                    f"(difference {drift:.3f} above {_MAX_SIGNATURE_DRIFT}). Compare "
                    f"{slide_render.preview_path.name} with {page.name}; a substituted "
                    "font or a displaced native object is the usual cause."
                ),
                slide_number=slide_render.number,
            )
        )
    return issues, {
        "status": "completed",
        "threshold": _MAX_SIGNATURE_DRIFT,
        "slides": measurements,
    }


async def build_html_presentation(
    project: HtmlDeckProject,
    *,
    session_id: str,
    project_file: Path,
    workspace_root: Path,
    render_dir: Path,
    output: Path,
) -> HtmlDeckBuildResult:
    result = await render_html_deck(
        project,
        session_id=session_id,
        project_file=project_file,
        workspace_root=workspace_root,
        render_dir=render_dir,
    )
    if not result.passed:
        return result
    result.output = await asyncio.to_thread(
        assemble_hybrid_pptx,
        project,
        result.slides,
        output,
    )
    round_trip_issues, result.round_trip = await asyncio.to_thread(
        verify_exported_deck,
        result.output,
        result.slides,
        render_dir / "round-trip",
    )
    result.issues.extend(round_trip_issues)
    (render_dir / "qa.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "HtmlDeckBuildResult",
    "HtmlDeckProject",
    "HtmlDeckTheme",
    "HtmlSlideSpec",
    "assemble_hybrid_pptx",
    "build_html_presentation",
    "html_catalog",
    "load_html_deck_project",
    "render_html_deck",
    "validate_html_fragment",
    "verify_exported_deck",
]
