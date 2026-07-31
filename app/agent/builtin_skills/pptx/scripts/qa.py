"""Structural, overflow-heuristic, and optional render QA for PPTX files."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree as ET

from pptx import Presentation
from pptx.oxml.ns import qn

for parent in Path(__file__).resolve().parents:
    if (parent / "app" / "services").is_dir():
        sys.path.insert(0, str(parent))
        break

from app.services.office_visual_qa_service import (  # noqa: E402
    compare_rendered_images,
    render_office_images,
)
from app.agent.builtin_skills.pptx.scripts.stylekit import (  # noqa: E402
    LayoutProfileName,
    layout_profile,
)

PLACEHOLDER_RE = re.compile(
    r"(\{\{[^{}]+\}\}|<TODO>|<PLACEHOLDER>|lorem ipsum|\bxxxx\b)",
    re.IGNORECASE,
)
EMU_PER_INCH = 914400
OVERLAP_RATIO_THRESHOLD = 0.12
ICON_NAME_RE = re.compile(r"^\[icon:([a-z0-9-]+):([a-z0-9-]+)\]$")
PROFILE_RE = re.compile(r"\[profile:(editorial|executive-dense|operational)\]")
ROLE_RE = re.compile(
    r"\[role:(deck-title|title|subheading|section-heading|body|label|caption|metadata|kicker|footer)\]"
)
_AUDIO_EXTENSIONS = {".aac", ".m4a", ".mp3", ".wav", ".wma"}
_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".wmv"}


def _shape_text(shape) -> str:
    if not getattr(shape, "has_text_frame", False):
        return ""
    return shape.text.strip()


def _slide_profile(slide) -> LayoutProfileName:
    """Read the explicit profile marker; unmarked slides remain editorial."""

    name = str(slide._element.cSld.get("name", "") or "").lower()
    match = PROFILE_RE.search(name)
    if match is None:
        return "editorial"
    return cast(LayoutProfileName, match.group(1))


def _shape_role(shape) -> str | None:
    match = ROLE_RE.search(str(getattr(shape, "name", "") or "").lower())
    return match.group(1) if match is not None else None


def _shape_id(shape) -> int:
    return int(getattr(shape, "shape_id", 0) or 0)


def _shape_area(shape) -> int:
    return max(int(shape.width), 0) * max(int(shape.height), 0)


def _is_background(shape, presentation) -> bool:
    slide_area = int(presentation.slide_width) * int(presentation.slide_height)
    return not _shape_text(shape) and _shape_area(shape) >= slide_area * 0.72


def _is_line_or_connector(shape) -> bool:
    shape_type = getattr(getattr(shape, "shape_type", None), "name", "")
    return shape_type in {"LINE", "FREEFORM"} or shape.width == 0 or shape.height == 0


def _walk_shapes(shapes):
    """Yield top-level shapes and editable descendants inside native groups."""
    for shape in shapes:
        yield shape
        shape_type = getattr(getattr(shape, "shape_type", None), "name", "")
        if shape_type == "GROUP":
            yield from _walk_shapes(shape.shapes)


def _is_rounded_shape(shape) -> bool:
    try:
        auto_shape = shape.auto_shape_type
    except (AttributeError, ValueError):
        return False
    name = getattr(auto_shape, "name", str(auto_shape)).upper()
    return "ROUND" in name


def _icon_metadata(shape) -> tuple[str, str] | None:
    match = ICON_NAME_RE.match(str(getattr(shape, "name", "")).lower())
    if match is None:
        return None
    return match.group(1), match.group(2)


def _picture_extension(shape) -> str | None:
    try:
        relation_id = shape._pic.blip_rId
        return str(shape.part.related_part(relation_id).partname.ext).lower()
    except (AttributeError, KeyError, ValueError):
        return None


def _has_accessibility_text(shape) -> bool:
    try:
        properties = shape._element.xpath(".//*[local-name()='cNvPr']")
    except (AttributeError, TypeError, ValueError):
        return False
    return bool(
        properties
        and (
            properties[0].get("title", "").strip()
            or properties[0].get("descr", "").strip()
        )
    )


def _has_hyperlink(shape) -> bool:
    try:
        return bool(shape._element.xpath(".//*[local-name()='hlinkClick']"))
    except (AttributeError, TypeError, ValueError):
        return False


def _intersection_ratio(left, right) -> float:
    intersection_width = max(
        0,
        min(left.left + left.width, right.left + right.width)
        - max(left.left, right.left),
    )
    intersection_height = max(
        0,
        min(left.top + left.height, right.top + right.height)
        - max(left.top, right.top),
    )
    intersection = intersection_width * intersection_height
    denominator = max(min(_shape_area(left), _shape_area(right)), 1)
    return intersection / denominator


def _contains_shape(container, child) -> bool:
    return (
        container.left <= child.left
        and container.top <= child.top
        and container.left + container.width >= child.left + child.width
        and container.top + container.height >= child.top + child.height
    )


def _is_flat_container_pair(left, right, ratio: float) -> bool:
    if ratio < 0.94:
        return False
    left_text = bool(_shape_text(left))
    right_text = bool(_shape_text(right))
    left_name = str(getattr(left, "name", "") or "").lower()
    right_name = str(getattr(right, "name", "") or "").lower()
    if "[container:" in left_name and _contains_shape(left, right):
        return True
    if "[container:" in right_name and _contains_shape(right, left):
        return True
    left_icon = _icon_metadata(left) is not None
    right_icon = _icon_metadata(right) is not None
    if left_icon != right_icon:
        icon = left if left_icon else right
        badge = right if left_icon else left
        try:
            if (
                badge.auto_shape_type is not None
                and not _shape_text(badge)
                and _contains_shape(badge, icon)
            ):
                return True
        except (AttributeError, ValueError):
            pass
    if left_text == right_text:
        return False
    container = right if left_text else left
    try:
        return container.auto_shape_type is not None and not _shape_text(container)
    except (AttributeError, ValueError):
        return False


def _font_sizes(shape) -> list[float]:
    return [
        run.font.size.pt
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
        if run.font.size is not None
    ]


def _render(source: Path, render_dir: Path) -> dict[str, Any]:
    return render_office_images(source, render_dir)


def _font_floor(shape) -> float | None:
    sizes = _font_sizes(shape)
    return min(sizes) if sizes else None


def _font_ceiling(shape) -> float | None:
    sizes = _font_sizes(shape)
    return max(sizes) if sizes else None


def _estimated_capacity(shape, *, minimum_point_size: float = 9) -> int:
    """Estimate readable character capacity; visual inspection remains final."""
    width_inches = shape.width / 914400
    height_inches = shape.height / 914400
    point_size = max(_font_floor(shape) or 18.0, minimum_point_size)
    chars_per_line = max(int(width_inches * 72 / (point_size * 0.52)), 1)
    lines = max(int(height_inches * 72 / (point_size * 1.2)), 1)
    return chars_per_line * lines


def _is_title_shape(shape, slide) -> bool:
    if shape == slide.shapes.title:
        return True
    name = str(getattr(shape, "name", "")).lower()
    if "title" in name:
        return True
    ceiling = _font_ceiling(shape)
    return bool(
        _shape_text(shape)
        and ceiling
        and ceiling >= 30
        and shape.top < 1.5 * EMU_PER_INCH
    )


def _one_line_capacity(shape, *, minimum_point_size: float = 9) -> int:
    point_size = max(_font_ceiling(shape) or 35.0, minimum_point_size)
    width_inches = shape.width / EMU_PER_INCH
    return max(int(width_inches * 72 / (point_size * 0.54)), 1)


def _finding(
    severity: str,
    signature: str,
    value: float,
    message: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "signature": signature,
        "value": round(value, 4),
        "message": message,
    }


def _package_feature_inventory(package: zipfile.ZipFile) -> dict[str, Any]:
    names = package.namelist()
    slide_names = [
        name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
    ]
    slide_roots = [ET.fromstring(package.read(name)) for name in slide_names]

    def count_local(local_name: str) -> int:
        suffix = f"}}{local_name}"
        return sum(
            1
            for root in slide_roots
            for node in root.iter()
            if node.tag.endswith(suffix)
        )

    morph_namespace = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
    media_extensions = [
        Path(name).suffix.lower() for name in names if name.startswith("ppt/media/")
    ]
    return {
        "masters": sum(
            bool(re.fullmatch(r"ppt/slideMasters/slideMaster\d+\.xml", name))
            for name in names
        ),
        "layouts": sum(
            bool(re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", name))
            for name in names
        ),
        "themes": sum(name.startswith("ppt/theme/theme") for name in names),
        "charts": sum(
            bool(
                re.fullmatch(
                    r"ppt/(?:charts|slides/charts)/chart[^/]*\.xml",
                    name,
                )
            )
            for name in names
        ),
        "embedded_workbooks": sum(name.startswith("ppt/embeddings/") for name in names),
        "smartart_parts": sum(name.startswith("ppt/diagrams/") for name in names),
        "audio_files": sum(
            extension in _AUDIO_EXTENSIONS for extension in media_extensions
        ),
        "video_files": sum(
            extension in _VIDEO_EXTENSIONS for extension in media_extensions
        ),
        "notes_slides": sum(
            name.startswith("ppt/notesSlides/notesSlide") for name in names
        ),
        "comments": sum(
            name.startswith("ppt/comments/") or name.startswith("ppt/commentAuthors")
            for name in names
        ),
        "ole_objects": sum(
            name.startswith("ppt/embeddings/oleObject") for name in names
        ),
        "transitions": count_local("transition"),
        "morph_transitions": sum(
            1
            for root in slide_roots
            for node in root.iter()
            if node.tag == f"{{{morph_namespace}}}morph"
        ),
        "animation_timelines": count_local("timing"),
        "placeholders": count_local("ph"),
        "gradient_fills": count_local("gradFill"),
        "shadows": count_local("outerShdw"),
        "hyperlinks": count_local("hlinkClick"),
        "groups": count_local("grpSp"),
    }


def _layout_findings(
    presentation,
    *,
    allow_shape_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        profile_name = _slide_profile(slide)
        policy = layout_profile(profile_name)
        all_shapes = list(_walk_shapes(slide.shapes))
        content_shapes = [
            shape
            for shape in slide.shapes
            if _shape_area(shape)
            and not _is_background(shape, presentation)
            and not _is_line_or_connector(shape)
        ]
        text_shapes = [shape for shape in content_shapes if _shape_text(shape)]
        rounded = [shape for shape in content_shapes if _is_rounded_shape(shape)]
        icons = [
            (shape, metadata)
            for shape in content_shapes
            if (metadata := _icon_metadata(shape)) is not None
        ]
        charts = [
            shape for shape in content_shapes if getattr(shape, "has_chart", False)
        ]
        tables = [
            shape for shape in content_shapes if getattr(shape, "has_table", False)
        ]
        pictures = [
            shape
            for shape in content_shapes
            if getattr(getattr(shape, "shape_type", None), "name", "") == "PICTURE"
            and _icon_metadata(shape) is None
        ]
        groups = [
            shape
            for shape in content_shapes
            if getattr(getattr(shape, "shape_type", None), "name", "") == "GROUP"
        ]
        connectors = [
            shape
            for shape in all_shapes
            if _is_line_or_connector(shape) and not _is_background(shape, presentation)
        ]
        accessible_shapes = [
            shape
            for shape in all_shapes
            if _shape_area(shape)
            and not _is_background(shape, presentation)
            and _has_accessibility_text(shape)
        ]
        hyperlinks = [shape for shape in all_shapes if _has_hyperlink(shape)]
        has_transition = slide._element.find(qn("p:transition")) is not None
        try:
            has_source_notes = bool(
                slide.has_notes_slide
                and "[Sources]" in slide.notes_slide.notes_text_frame.text
            )
        except (AttributeError, TypeError, ValueError):
            has_source_notes = False
        overlaps: list[dict[str, Any]] = []

        for index, left in enumerate(content_shapes):
            for right in content_shapes[index + 1 :]:
                names = f"{left.name!r} and {right.name!r}"
                if "[allow-overlap]" in left.name or "[allow-overlap]" in right.name:
                    continue
                ratio = _intersection_ratio(left, right)
                if ratio < OVERLAP_RATIO_THRESHOLD or _is_flat_container_pair(
                    left, right, ratio
                ):
                    continue
                left_id, right_id = sorted((_shape_id(left), _shape_id(right)))
                signature = f"slide:{slide_number}:overlap:{left_id}:{right_id}"
                text_overlap = bool(_shape_text(left) or _shape_text(right))
                severity = "error" if text_overlap else "warning"
                message = (
                    f"Slide {slide_number}: {names} overlap by "
                    f"{ratio:.0%} of the smaller item"
                )
                findings.append(_finding(severity, signature, ratio, message))
                overlaps.append(
                    {
                        "shape_ids": [left_id, right_id],
                        "ratio": round(ratio, 4),
                        "severity": severity,
                    }
                )

        for shape in text_shapes:
            text = _shape_text(shape)
            capacity = max(
                _estimated_capacity(
                    shape,
                    minimum_point_size=policy.metadata_min_pt,
                ),
                1,
            )
            explicit_lines = max(text.count("\n") + 1, 1)
            estimated_lines = max(
                math.ceil(
                    len(text)
                    / max(
                        _one_line_capacity(
                            shape,
                            minimum_point_size=policy.metadata_min_pt,
                        ),
                        1,
                    )
                ),
                explicit_lines,
            )
            fit_ratio = len(text) / capacity
            shape_id = _shape_id(shape)
            if fit_ratio > 1:
                findings.append(
                    _finding(
                        "error",
                        f"slide:{slide_number}:overflow:{shape_id}",
                        fit_ratio,
                        f"Slide {slide_number}: {shape.name!r} needs about "
                        f"{fit_ratio:.1f}× its text capacity",
                    )
                )
            is_title = _is_title_shape(shape, slide)
            role = _shape_role(shape)
            maximum_title_lines = 2 if role == "deck-title" else 1
            if is_title and estimated_lines > maximum_title_lines:
                findings.append(
                    _finding(
                        "error",
                        f"slide:{slide_number}:title-wrap:{shape_id}",
                        estimated_lines,
                        f"Slide {slide_number}: title {shape.name!r} is likely to wrap "
                        f"to {estimated_lines} lines; the {role or 'title'} role allows "
                        f"{maximum_title_lines}. Shorten it or change layout",
                    )
                )
            floor = _font_floor(shape)
            if is_title or role == "title":
                minimum = policy.title_min_pt
            elif role in {"subheading", "section-heading"}:
                minimum = policy.subheading_min_pt
            elif role in {"caption", "kicker"}:
                minimum = policy.caption_min_pt
            elif role in {"metadata", "footer"}:
                minimum = policy.metadata_min_pt
            else:
                minimum = policy.body_min_pt
            if floor is not None and floor < minimum:
                findings.append(
                    _finding(
                        "warning",
                        f"slide:{slide_number}:small-font:{shape_id}",
                        minimum - floor,
                        f"Slide {slide_number}: {shape.name!r} uses {floor:.1f}pt "
                        f"text; layout floor is {minimum}pt",
                    )
                )

        rounded_warning = {
            "editorial": 3,
            "executive-dense": 6,
            "operational": 9,
        }[profile_name]
        rounded_error = {
            "editorial": 4,
            "executive-dense": 12,
            "operational": 18,
        }[profile_name]
        if len(rounded) >= rounded_warning:
            severity = "error" if len(rounded) >= rounded_error else "warning"
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:rounded-cards",
                    len(rounded),
                    f"Slide {slide_number}: {len(rounded)} rounded rectangles exceed "
                    f"the {profile_name} profile's structural-container allowance; "
                    "use borders, rules, grouping, or fewer corner treatments",
                )
            )
        icon_families = sorted({metadata[0] for _, metadata in icons})
        if len(icon_families) > 1:
            findings.append(
                _finding(
                    "warning",
                    f"slide:{slide_number}:mixed-icon-families",
                    len(icon_families),
                    f"Slide {slide_number}: icon families {', '.join(icon_families)} "
                    "are mixed; keep one visual language per deck",
                )
            )
        for shape, metadata in icons:
            family, icon_name = metadata
            minimum_side = min(shape.width, shape.height) / EMU_PER_INCH
            if minimum_side < policy.icon_min_inches:
                findings.append(
                    _finding(
                        "warning",
                        f"slide:{slide_number}:small-icon:{_shape_id(shape)}",
                        policy.icon_min_inches - minimum_side,
                        f"Slide {slide_number}: {family}:{icon_name} is only "
                        f"{minimum_side:.2f}in; {profile_name} profile uses at least "
                        f"{policy.icon_min_inches:.2f}in",
                    )
                )
            extension = _picture_extension(shape)
            if extension is not None and extension != "svg":
                findings.append(
                    _finding(
                        "warning",
                        f"slide:{slide_number}:raster-icon:{_shape_id(shape)}",
                        1,
                        f"Slide {slide_number}: {family}:{icon_name} is {extension}, "
                        "not a themeable SVG",
                    )
                )
        icon_warning = {
            "editorial": 6,
            "executive-dense": 14,
            "operational": 24,
        }[profile_name]
        icon_error = {
            "editorial": 10,
            "executive-dense": 24,
            "operational": 40,
        }[profile_name]
        if len(icons) > icon_warning:
            severity = "error" if len(icons) > icon_error else "warning"
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:icon-density",
                    len(icons),
                    f"Slide {slide_number}: {len(icons)} icons exceed the "
                    f"{profile_name} profile allowance; keep only semantic icons",
                )
            )
        shape_warning, text_warning, shape_error, text_error = {
            "editorial": (12, 6, 18, 9),
            "executive-dense": (48, 28, 80, 48),
            "operational": (96, 64, 160, 100),
        }[profile_name]
        semantic_items = (
            len(text_shapes)
            + len(icons)
            + len(charts)
            + len(tables)
            + len(pictures)
            + len(groups)
        )
        if semantic_items > shape_warning or len(text_shapes) > text_warning:
            density = max(
                semantic_items / shape_warning,
                len(text_shapes) / text_warning,
            )
            severity = (
                "error"
                if semantic_items > shape_error or len(text_shapes) > text_error
                else "warning"
            )
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:density",
                    density,
                    f"Slide {slide_number}: layout is dense "
                    f"({semantic_items} semantic items, "
                    f"{len(text_shapes)} text blocks); "
                    f"it exceeds the {profile_name} profile budget",
                )
            )

        metrics.append(
            {
                "slide": slide_number,
                "profile": profile_name,
                "content_shapes": len(content_shapes),
                "semantic_items": semantic_items,
                "text_shapes": len(text_shapes),
                "rounded_shapes": len(rounded),
                "icon_count": len(icons),
                "icon_families": icon_families,
                "office_features": {
                    "native_charts": len(charts),
                    "native_tables": len(tables),
                    "pictures": len(pictures),
                    "groups": len(groups),
                    "connectors": len(connectors),
                    "accessible_shapes": len(accessible_shapes),
                    "hyperlinks": len(hyperlinks),
                    "transition": has_transition,
                    "source_notes": has_source_notes,
                },
                "overlaps": overlaps,
            }
        )
    feature_totals = {
        key: sum(int(metric["office_features"][key]) for metric in metrics)
        for key in (
            "native_charts",
            "native_tables",
            "pictures",
            "groups",
            "connectors",
            "accessible_shapes",
            "hyperlinks",
            "transition",
            "source_notes",
        )
    }
    if len(metrics) >= 5 and not any(
        feature_totals[key] for key in ("native_charts", "native_tables", "pictures")
    ):
        findings.append(
            _finding(
                "warning" if allow_shape_only else "error",
                "deck:shape-only-composition",
                1,
                f"Deck has {len(metrics)} slides but no native charts, tables, "
                "or non-icon pictures; add a native visual or explicitly allow the "
                "shape-only treatment",
            )
        )
    return findings, metrics


def _baseline_values(reference: Path | None) -> dict[str, float]:
    if reference is None:
        return {}
    try:
        presentation = Presentation(str(reference))
    except Exception:
        return {}
    findings, _ = _layout_findings(presentation)
    return {finding["signature"]: float(finding["value"]) for finding in findings}


def inspect_pptx(
    source: Path,
    *,
    reference: Path | None = None,
    allow_shape_only: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    package_features: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(source) as package:
            bad_entry = package.testzip()
            if bad_entry:
                errors.append(f"Corrupt ZIP entry: {bad_entry}")
            names = set(package.namelist())
            for required in (
                "[Content_Types].xml",
                "_rels/.rels",
                "ppt/presentation.xml",
            ):
                if required not in names:
                    errors.append(f"Missing package part: {required}")
            package_features = _package_feature_inventory(package)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"errors": [f"Invalid PPTX package: {exc}"], "warnings": []}

    try:
        presentation = Presentation(str(source))
    except Exception as exc:
        return {
            "errors": [f"python-pptx could not open the package: {exc}"],
            "warnings": [],
        }

    if not presentation.slides:
        errors.append("Presentation contains no slides")
    titles: list[str] = []
    empty_slides: list[int] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        visible_shape_count = 0
        for shape in slide.shapes:
            if (
                shape.left < 0
                or shape.top < 0
                or shape.left + shape.width > presentation.slide_width
                or shape.top + shape.height > presentation.slide_height
            ):
                errors.append(
                    f"Slide {slide_number}: shape '{shape.name}' is outside the canvas"
                )

            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    visible_shape_count += 1
                    if PLACEHOLDER_RE.search(text):
                        errors.append(
                            f"Slide {slide_number}: unresolved placeholder in '{shape.name}'"
                        )
                    if shape == slide.shapes.title:
                        titles.append(text)
                elif shape.is_placeholder:
                    warnings.append(
                        f"Slide {slide_number}: empty placeholder '{shape.name}'"
                    )
                else:
                    visible_shape_count += 1
            elif shape.shape_type is not None:
                visible_shape_count += 1

            if getattr(shape, "has_chart", False) and not list(shape.chart.series):
                errors.append(
                    f"Slide {slide_number}: chart '{shape.name}' has no series"
                )
        if visible_shape_count == 0:
            empty_slides.append(slide_number)

    if empty_slides:
        errors.append(f"Empty slides: {', '.join(map(str, empty_slides))}")
    duplicate_titles = sorted({title for title in titles if titles.count(title) > 1})
    if duplicate_titles:
        warnings.append(f"Repeated slide titles: {', '.join(duplicate_titles[:10])}")
    if package_features.get("audio_files") or package_features.get("video_files"):
        warnings.append(
            "Embedded audio/video is preserved structurally, but Chromium visual QA "
            "does not verify media playback"
        )
    layout_findings, layout_metrics = _layout_findings(
        presentation,
        allow_shape_only=allow_shape_only,
    )
    baseline = _baseline_values(reference)
    retained_findings = []
    for finding in layout_findings:
        baseline_value = baseline.get(finding["signature"])
        if baseline_value is not None and finding["value"] <= baseline_value * 1.02:
            continue
        retained_findings.append(finding)
        target = errors if finding["severity"] == "error" else warnings
        target.append(finding["message"])
    return {
        "errors": errors,
        "warnings": warnings,
        "slides": len(presentation.slides),
        "slide_width": presentation.slide_width,
        "slide_height": presentation.slide_height,
        "powerpoint_features": package_features,
        "layout": {
            "findings": retained_findings,
            "metrics": layout_metrics,
            "office_feature_summary": {
                key: sum(
                    int(metric["office_features"][key]) for metric in layout_metrics
                )
                for key in (
                    "native_charts",
                    "native_tables",
                    "pictures",
                    "groups",
                    "connectors",
                    "accessible_shapes",
                    "hyperlinks",
                    "transition",
                    "source_notes",
                )
            },
            "reference_baseline": str(reference) if reference else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--compare-to", type=Path)
    parser.add_argument(
        "--allow-shape-only",
        action="store_true",
        help="permit decks of five or more slides without charts, tables, or pictures",
    )
    args = parser.parse_args()

    report = inspect_pptx(
        args.file,
        reference=args.compare_to,
        allow_shape_only=args.allow_shape_only,
    )
    if args.render_dir:
        report["render"] = _render(args.file, args.render_dir)
        render = report["render"]
        if render["status"] == "rendered":
            report["errors"].extend(render["errors"])
            report["warnings"].extend(render["warnings"])
            if args.compare_to:
                reference_dir = args.render_dir / "reference"
                reference = _render(args.compare_to, reference_dir)
                report["visual_diff"] = compare_rendered_images(
                    list(reference.get("images", [])),
                    list(render.get("images", [])),
                )
                report["errors"].extend(report["visual_diff"]["errors"])
        else:
            report["warnings"].append(
                f"Visual QA {render['status']}: {render.get('reason', 'unknown reason')}"
            )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
