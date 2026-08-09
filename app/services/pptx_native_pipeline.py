"""High-fidelity PPTX authoring through Artifact Fabric.

Net-new decks can use a deterministic Chromium-rendered visual shell for exact
HTML fidelity, optionally layered with native editable PowerPoint objects.
The renderer is backend-only and never depends on Desktop WebView state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageChops
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.services.office.runtime import (
    NodeWorkerRuntime,
    file_sha256,
    resolve_chromium_binary,
)
from app.services.office.rendering import render_pages, renderer_available

MAX_SLIDES = 80
MAX_ELEMENTS_PER_SLIDE = 160
MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_CSS_BYTES = 2 * 1024 * 1024

_FORBIDDEN_HTML_TAGS = {
    "audio",
    "base",
    "button",
    "canvas",
    "embed",
    "form",
    "foreignobject",
    "iframe",
    "input",
    "object",
    "script",
    "select",
    "source",
    "textarea",
    "video",
}
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_UNSAFE_CSS = re.compile(
    r"@import\b|expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding\s*:",
    re.IGNORECASE,
)


class _StaticSlideHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in _FORBIDDEN_HTML_TAGS:
            raise ValueError(f"HTML visual shell contains forbidden <{tag}> tag")
        if normalized_tag == "meta":
            normalized_attrs = {
                name.lower(): (value or "").lower() for name, value in attrs
            }
            if normalized_attrs != {"charset": "utf-8"}:
                raise ValueError('HTML visual shell allows only <meta charset="utf-8">')
        if normalized_tag == "link":
            names = [name.lower() for name, _ in attrs]
            if len(names) != len(set(names)):
                raise ValueError("HTML visual shell link attributes must be unique")
            if not set(names).issubset({"rel", "href", "type"}):
                raise ValueError(
                    "HTML visual shell allows only rel, href, and type on <link>"
                )
            normalized_attrs = {
                name.lower(): (value or "").strip() for name, value in attrs
            }
            if normalized_attrs.get("rel", "").lower() != "stylesheet":
                raise ValueError("HTML visual shell allows only stylesheet links")
            href = normalized_attrs.get("href", "")
            if not href:
                raise ValueError("HTML visual shell stylesheet link requires href")
            if normalized_attrs.get("type", "text/css").lower() != "text/css":
                raise ValueError("HTML visual shell stylesheet must use text/css")
            self.stylesheets.append(href)
        for name, value in attrs:
            normalized_name = name.lower()
            if normalized_name.startswith("on"):
                raise ValueError(
                    f"HTML visual shell contains forbidden event attribute {name}"
                )
            if normalized_name == "srcset":
                raise ValueError("HTML visual shell does not allow srcset")
            if value and normalized_name in {"href", "src", "xlink:href"}:
                self.references.append(value.strip())

    handle_startendtag = handle_starttag


class SlidePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: float = Field(ge=0)
    top: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class TextElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"] = "text"
    name: str | None = Field(default=None, max_length=160)
    position: SlidePosition
    text: str = Field(min_length=1, max_length=20000)
    font_size: float = Field(default=24, ge=6, le=160)
    typeface: str | None = Field(default=None, max_length=120)
    color: str = "#111827"
    bold: bool = False
    italic: bool = False
    alignment: Literal["left", "center", "right", "justify"] = "left"
    vertical_alignment: Literal["top", "middle", "bottom"] = "top"
    auto_fit: Literal["none", "shrinkText", "resizeShapeToFitText"] = "shrinkText"
    fill: str = "none"
    line_fill: str = "none"
    line_width: float = Field(default=0, ge=0, le=20)


class ShapeElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["shape"] = "shape"
    name: str | None = Field(default=None, max_length=160)
    position: SlidePosition
    geometry: str = Field(default="rect", min_length=1, max_length=80)
    fill: str = "#ffffff"
    line_fill: str = "none"
    line_width: float = Field(default=0, ge=0, le=20)
    border_radius: float | str | None = None
    shadow: str | None = None
    text: str | None = Field(default=None, max_length=12000)
    font_size: float = Field(default=20, ge=6, le=160)
    text_color: str = "#111827"
    bold: bool = False
    alignment: Literal["left", "center", "right", "justify"] = "left"
    vertical_alignment: Literal["top", "middle", "bottom"] = "middle"

    @model_validator(mode="after")
    def compatible_border_radius(self) -> "ShapeElement":
        if self.border_radius is not None and self.geometry not in {
            "rect",
            "roundRect",
        }:
            raise ValueError("border_radius is supported only for rectangular shapes")
        return self


class ImageElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"] = "image"
    name: str | None = Field(default=None, max_length=160)
    position: SlidePosition
    asset_path: str = Field(min_length=1, max_length=2000)
    alt: str = Field(min_length=1, max_length=1000)
    fit: Literal["cover", "contain"] = "cover"
    geometry: str = "rect"
    border_radius: float | str | None = None

    @model_validator(mode="after")
    def compatible_border_radius(self) -> "ImageElement":
        if self.border_radius is not None and self.geometry not in {
            "rect",
            "roundRect",
        }:
            raise ValueError("border_radius is supported only for rectangular images")
        return self


class TableElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["table"] = "table"
    name: str | None = Field(default=None, max_length=160)
    position: SlidePosition
    values: list[list[str | int | float | None]] = Field(min_length=1, max_length=100)
    header_row: bool = True
    header_fill: str = "#e2e8f0"
    header_text_color: str = "#0f172a"
    body_fill: str = "#ffffff"
    body_text_color: str = "#334155"
    font_size: float = Field(default=16, ge=6, le=72)

    @field_validator("values")
    @classmethod
    def rectangular(cls, rows: list[list[Any]]) -> list[list[Any]]:
        width = len(rows[0])
        if width == 0 or width > 40 or any(len(row) != width for row in rows):
            raise ValueError("table values must be a non-empty rectangular matrix")
        return rows


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    values: list[float] = Field(min_length=1, max_length=500)
    fill: str | None = None


class ChartElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["chart"] = "chart"
    name: str | None = Field(default=None, max_length=160)
    position: SlidePosition
    chart_type: Literal["bar", "line", "pie", "doughnut", "area"] = "bar"
    title: str | None = Field(default=None, max_length=500)
    categories: list[str] = Field(min_length=1, max_length=500)
    series: list[ChartSeries] = Field(min_length=1, max_length=40)
    has_legend: bool = True
    show_values: bool = False

    @model_validator(mode="after")
    def matching_series(self) -> "ChartElement":
        for series in self.series:
            if len(series.values) != len(self.categories):
                raise ValueError("every chart series must match categories length")
        return self


SlideElement = Annotated[
    TextElement | ShapeElement | ImageElement | TableElement | ChartElement,
    Field(discriminator="type"),
]


class VisualShell(BaseModel):
    """One static HTML composition rendered by the bundled Chromium."""

    model_config = ConfigDict(extra="forbid")
    html_path: str = Field(min_length=1, max_length=2000)
    alt: str = Field(min_length=1, max_length=1000)
    reference_html_path: str | None = Field(default=None, max_length=2000)
    render_scale: Literal[1, 2] = 2
    max_changed_pixel_ratio: float = Field(default=0.02, ge=0, le=0.25)
    max_mean_absolute_error: float = Field(default=0.01, ge=0, le=0.25)


class NativeSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    background: str = "#ffffff"
    visual_shell: VisualShell | None = None
    elements: list[SlideElement] = Field(
        default_factory=list, max_length=MAX_ELEMENTS_PER_SLIDE
    )
    speaker_notes: str | None = Field(default=None, max_length=30000)


class NativePptxProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    mode: Literal["new"] = "new"
    quality_profile: Literal["fidelity", "hybrid", "native"] = "fidelity"
    title: str = Field(min_length=1, max_length=500)
    width: int = Field(default=1280, ge=640, le=3840)
    height: int = Field(default=720, ge=360, le=2160)
    slides: list[NativeSlide] = Field(min_length=1, max_length=MAX_SLIDES)

    @model_validator(mode="after")
    def validate_geometry(self) -> "NativePptxProject":
        ids = [slide.id for slide in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("slide ids must be unique")
        for slide in self.slides:
            if self.quality_profile == "fidelity":
                if slide.visual_shell is None:
                    raise ValueError(
                        f"slide {slide.id} requires visual_shell in fidelity mode"
                    )
                if slide.elements:
                    raise ValueError(
                        f"slide {slide.id} cannot contain native elements in fidelity mode"
                    )
            elif self.quality_profile == "hybrid":
                if slide.visual_shell is None or not slide.elements:
                    raise ValueError(
                        f"slide {slide.id} requires visual_shell and native elements "
                        "in hybrid mode"
                    )
                if slide.visual_shell.reference_html_path is None:
                    raise ValueError(
                        f"slide {slide.id} requires reference_html_path in hybrid mode"
                    )
            elif slide.visual_shell is not None or not slide.elements:
                raise ValueError(
                    f"slide {slide.id} requires native elements and no visual_shell "
                    "in native mode"
                )
            for element in slide.elements:
                position = element.position
                if position.left + position.width > self.width + 0.01:
                    raise ValueError(
                        f"slide {slide.id} element exceeds the right slide boundary"
                    )
                if position.top + position.height > self.height + 0.01:
                    raise ValueError(
                        f"slide {slide.id} element exceeds the bottom slide boundary"
                    )
        return self


_PROJECT_ADAPTER = TypeAdapter(NativePptxProject)


@dataclass
class NativePptxPipelineResult:
    action: str
    work_dir: Path
    output: Path | None = None
    previews: list[Path] = field(default_factory=list)
    layout_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.get("severity") == "error" for issue in self.issues)


def load_native_pptx_project(path: Path) -> NativePptxProject:
    return _PROJECT_ADAPTER.validate_json(path.read_text(encoding="utf-8"))


def _project_file(project_dir: Path, value: str, *, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} must be relative to the project directory")
    project_root = project_dir.resolve()
    resolved = (project_root / relative).resolve()
    if not resolved.is_relative_to(project_root):
        raise ValueError(f"{label} escapes the project directory")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _validate_local_reference(
    project_dir: Path,
    value: str,
    *,
    label: str,
    base_dir: Path | None = None,
) -> Path | None:
    reference = value.strip()
    if not reference or reference.startswith("#"):
        return
    parsed = urlsplit(reference)
    scheme = parsed.scheme.lower()
    if scheme == "data":
        media_type = reference[5:].split(";", 1)[0].lower()
        if media_type.startswith("image/") or media_type.startswith("font/"):
            return None
        if media_type in {"application/font-woff", "application/font-woff2"}:
            return None
        raise ValueError(f"{label} uses unsupported data URL media type")
    if scheme or parsed.netloc or reference.startswith("//"):
        raise ValueError(f"{label} may reference only local files or data URLs")
    local_path = unquote(parsed.path)
    if not local_path:
        return None
    relative = Path(local_path)
    if relative.is_absolute():
        raise ValueError(f"{label} must be relative to the project directory")
    project_root = project_dir.resolve()
    reference_root = (base_dir or project_root).resolve()
    resolved = (reference_root / relative).resolve()
    if not resolved.is_relative_to(project_root):
        raise ValueError(f"{label} escapes the project directory")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _validate_static_stylesheet(path: Path, project_dir: Path) -> None:
    if path.suffix.lower() != ".css":
        raise ValueError(f"HTML visual shell stylesheet must use .css: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_CSS_BYTES:
        raise ValueError(
            f"HTML visual shell stylesheet must be between 1 and {MAX_CSS_BYTES} "
            f"bytes: {path}"
        )
    source = path.read_text(encoding="utf-8")
    if _UNSAFE_CSS.search(source):
        raise ValueError(f"HTML visual shell stylesheet contains unsafe CSS: {path}")
    for match in _CSS_URL.finditer(source):
        _validate_local_reference(
            project_dir,
            match.group(2).strip(),
            label=f"HTML visual shell stylesheet reference in {path.name}",
            base_dir=path.parent,
        )


def _validate_static_slide_html(path: Path, project_dir: Path) -> None:
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"HTML visual shell must use .html or .htm: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_HTML_BYTES:
        raise ValueError(
            f"HTML visual shell must be between 1 and {MAX_HTML_BYTES} bytes: {path}"
        )
    source = path.read_text(encoding="utf-8")
    if _UNSAFE_CSS.search(source):
        raise ValueError(f"HTML visual shell contains unsafe CSS or URL syntax: {path}")
    parser = _StaticSlideHtmlParser()
    parser.feed(source)
    parser.close()
    references = [*parser.references]
    references.extend(match.group(2).strip() for match in _CSS_URL.finditer(source))
    for reference in references:
        _validate_local_reference(
            project_dir,
            reference,
            label=f"HTML visual shell reference in {path.name}",
            base_dir=path.parent,
        )
    for stylesheet in parser.stylesheets:
        stylesheet_path = _validate_local_reference(
            project_dir,
            stylesheet,
            label=f"HTML visual shell stylesheet in {path.name}",
            base_dir=path.parent,
        )
        if stylesheet_path is not None:
            _validate_static_stylesheet(stylesheet_path, project_dir)


def _visual_parity(
    reference_path: Path,
    preview_path: Path,
    *,
    max_changed_pixel_ratio: float,
    max_mean_absolute_error: float,
) -> dict[str, Any]:
    with Image.open(reference_path) as source:
        reference = source.convert("RGB")
    with Image.open(preview_path) as rendered:
        preview = rendered.convert("RGB")

    # LibreOffice/Poppler and PowerPoint rasterize glyph edges differently from
    # Chromium, even when a full-slide image has identical placement. Compare
    # color/detail at presentation resolution, but measure displaced structure
    # on a thumbnail so anti-aliasing does not masquerade as layout drift.
    detail_scale = min(1.0, 960 / reference.width, 540 / reference.height)
    detail_size = (
        round(reference.width * detail_scale),
        round(reference.height * detail_scale),
    )
    reference_detail = reference.resize(detail_size, Image.Resampling.LANCZOS)
    preview_detail = preview.resize(detail_size, Image.Resampling.LANCZOS)
    detail_difference = ImageChops.difference(reference_detail, preview_detail)
    detail_pixels = detail_size[0] * detail_size[1]
    histogram = detail_difference.histogram()
    absolute_sum = sum((index % 256) * count for index, count in enumerate(histogram))
    mean_absolute_error = absolute_sum / (detail_pixels * 3 * 255)

    structural_scale = min(1.0, 240 / reference.width, 135 / reference.height)
    structural_size = (
        round(reference.width * structural_scale),
        round(reference.height * structural_scale),
    )
    reference_structure = reference.resize(structural_size, Image.Resampling.LANCZOS)
    preview_structure = preview.resize(structural_size, Image.Resampling.LANCZOS)
    structural_difference = ImageChops.difference(
        reference_structure, preview_structure
    )
    structural_pixels = structural_size[0] * structural_size[1]
    changed_mask = structural_difference.getchannel(0).point(
        lambda value: 255 if value > 16 else 0
    )
    for channel in (1, 2):
        channel_mask = structural_difference.getchannel(channel).point(
            lambda value: 255 if value > 16 else 0
        )
        changed_mask = ImageChops.lighter(changed_mask, channel_mask)
    changed = structural_pixels - changed_mask.histogram()[0]
    changed_pixel_ratio = changed / structural_pixels
    return {
        "reference_path": str(reference_path),
        "preview_path": str(preview_path),
        "comparison_size": list(structural_size),
        "detail_comparison_size": list(detail_size),
        "changed_pixel_ratio": changed_pixel_ratio,
        "mean_absolute_error": mean_absolute_error,
        "max_changed_pixel_ratio": max_changed_pixel_ratio,
        "max_mean_absolute_error": max_mean_absolute_error,
        "passed": (
            changed_pixel_ratio <= max_changed_pixel_ratio
            and mean_absolute_error <= max_mean_absolute_error
        ),
    }


def native_pptx_catalog() -> dict[str, Any]:
    return {
        "workflow": "artifact-tool-high-fidelity-pptx",
        "invariants": [
            "Use bundled headless Chromium and @oai/artifact-tool; never Desktop WebView or python-pptx.",
            "Fidelity mode preserves the authored HTML composition as a full-slide visual shell.",
            "Hybrid mode layers native editable objects over a visual shell and requires a full reference render.",
            "Native mode keeps every text, shape, image, table, and chart editable.",
            "Render every slide and export layout evidence before candidate acceptance.",
            "Reject unresolved placeholders, out-of-slide geometry, and visual parity drift.",
        ],
        "quality_profiles": {
            "fidelity": "Default: exact visual match; slide content is one full-slide image.",
            "hybrid": "Exact reference gate plus native editable overlays.",
            "native": "Fully editable primitives; visual fidelity depends on native styling.",
        },
        "supported_elements": ["text", "shape", "image", "table", "chart"],
        "project_json_schema": NativePptxProject.model_json_schema(),
    }


def validate_native_pptx_project(
    project: NativePptxProject, project_path: Path
) -> dict[str, Any]:
    project_dir = project_path.parent.resolve()
    for slide in project.slides:
        if slide.visual_shell is not None:
            shell_path = _project_file(
                project_dir,
                slide.visual_shell.html_path,
                label=f"slide {slide.id} visual_shell.html_path",
            )
            _validate_static_slide_html(shell_path, project_dir)
            if slide.visual_shell.reference_html_path:
                reference_path = _project_file(
                    project_dir,
                    slide.visual_shell.reference_html_path,
                    label=f"slide {slide.id} visual_shell.reference_html_path",
                )
                _validate_static_slide_html(reference_path, project_dir)
        for element in slide.elements:
            if not isinstance(element, ImageElement):
                continue
            path = Path(element.asset_path)
            if not path.is_absolute():
                path = project_path.parent / path
            if not path.is_file():
                raise FileNotFoundError(f"presentation image does not exist: {path}")
    return {
        "valid": True,
        "mode": "new",
        "quality_profile": project.quality_profile,
        "slide_count": len(project.slides),
        "element_count": sum(len(slide.elements) for slide in project.slides),
        "project_sha256": file_sha256(project_path),
    }


_WORKER = NodeWorkerRuntime(
    worker=Path(__file__).with_name("pptx_native_worker.mjs"),
    label="PPTX",
    purpose="high-fidelity PPTX authoring",
    requirement_hint="Net-new decks never fall back to Desktop WebView rendering.",
)


async def compose_native_pptx_project(
    project_path: Path,
    output: Path,
    *,
    workspace_root: Path,
    work_dir: Path,
) -> NativePptxPipelineResult:
    project = load_native_pptx_project(project_path)
    validate_native_pptx_project(project, project_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    normalized_project_path = work_dir / "normalized-project.json"
    normalized_project_path.write_text(
        project.model_dump_json(indent=2), encoding="utf-8"
    )
    chromium_path = None
    if project.quality_profile != "native":
        chromium_path = resolve_chromium_binary(
            purpose=f"PPTX {project.quality_profile} rendering"
        )
    value = await _WORKER.run(
        "compose",
        {
            "protocolVersion": 2,
            "projectPath": str(normalized_project_path),
            "sourceProjectPath": str(project_path.resolve()),
            "projectDir": str(project_path.parent.resolve()),
            "chromiumPath": chromium_path,
            "outputPath": str(output),
            "workDir": str(work_dir),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    issues = list(value.get("issues", []))
    parity: list[dict[str, Any]] = []
    artifact_preview_paths = [Path(path) for path in value.get("previewPaths", [])]
    preview_paths = artifact_preview_paths
    roundtrip_paths: list[Path] = []
    worker_output = Path(value["outputPath"]) if value.get("outputPath") else None
    if worker_output is not None and not any(
        issue.get("severity") == "error" for issue in issues
    ):
        if renderer_available():
            roundtrip_paths, roundtrip_issues = await asyncio.to_thread(
                render_pages,
                worker_output,
                work_dir / "roundtrip",
                code_prefix="pptx-roundtrip",
                dpi=144,
            )
            issues.extend(roundtrip_issues)
            if not roundtrip_issues and len(roundtrip_paths) != len(project.slides):
                issues.append(
                    {
                        "severity": "error",
                        "code": "pptx-roundtrip-slide-count",
                        "message": (
                            "Exported PPTX round trip returned "
                            f"{len(roundtrip_paths)} slides; expected {len(project.slides)}."
                        ),
                    }
                )
            elif not roundtrip_issues:
                preview_paths = roundtrip_paths
        else:
            issues.append(
                {
                    "severity": "warning",
                    "code": "pptx-roundtrip-unavailable",
                    "message": (
                        "LibreOffice/Poppler round-trip rendering is unavailable; "
                        "Artifact Fabric preview evidence was used."
                    ),
                }
            )
    reference_paths = [
        Path(path) if path else None for path in value.get("referencePaths", [])
    ]
    if len(reference_paths) != len(project.slides) or len(preview_paths) != len(
        project.slides
    ):
        issues.append(
            {
                "severity": "error",
                "code": "visual-parity-evidence-missing",
                "message": (
                    "PPTX worker did not return one preview and reference slot "
                    "per slide."
                ),
            }
        )
    else:
        for index, (slide, reference_path, preview_path) in enumerate(
            zip(project.slides, reference_paths, preview_paths, strict=True), start=1
        ):
            if reference_path is None or slide.visual_shell is None:
                continue
            metric = _visual_parity(
                reference_path,
                preview_path,
                max_changed_pixel_ratio=(slide.visual_shell.max_changed_pixel_ratio),
                max_mean_absolute_error=(slide.visual_shell.max_mean_absolute_error),
            )
            metric.update({"slide": index, "slide_id": slide.id})
            parity.append(metric)
            if not metric["passed"]:
                issues.append(
                    {
                        "severity": "error",
                        "code": "visual-parity-drift",
                        "message": (
                            f"Slide {index} differs from its HTML reference: "
                            f"changed_pixel_ratio={metric['changed_pixel_ratio']:.4f}, "
                            f"mean_absolute_error={metric['mean_absolute_error']:.4f}."
                        ),
                        "slide": index,
                    }
                )
    result = NativePptxPipelineResult(
        action="compose",
        work_dir=work_dir,
        output=Path(value["outputPath"]) if value.get("outputPath") else None,
        previews=preview_paths,
        layout_paths=[Path(path) for path in value.get("layoutPaths", [])],
        manifest_path=(
            Path(value["manifestPath"]) if value.get("manifestPath") else None
        ),
        issues=issues,
        metadata={
            key: item
            for key, item in value.items()
            if key
            not in {
                "outputPath",
                "previewPaths",
                "layoutPaths",
                "manifestPath",
                "issues",
            }
        },
    )
    result.metadata["visual_parity"] = parity
    result.metadata["quality_profile"] = project.quality_profile
    result.metadata["artifact_preview_paths"] = [
        str(path) for path in artifact_preview_paths
    ]
    result.metadata["roundtrip_preview_paths"] = [str(path) for path in roundtrip_paths]
    result.metadata["roundtrip_verified"] = bool(roundtrip_paths)
    if not result.passed and output.exists():
        output.unlink()
        result.output = None
    return result


__all__ = [
    "NativePptxPipelineResult",
    "NativePptxProject",
    "compose_native_pptx_project",
    "load_native_pptx_project",
    "native_pptx_catalog",
    "validate_native_pptx_project",
]
