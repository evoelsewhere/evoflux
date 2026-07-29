"""Structural, overflow-heuristic, and optional render QA for PPTX files."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from pptx import Presentation

for parent in Path(__file__).resolve().parents:
    if (parent / "app" / "services").is_dir():
        sys.path.insert(0, str(parent))
        break

from app.services.office_visual_qa_service import (  # noqa: E402
    compare_rendered_images,
    render_office_images,
)

PLACEHOLDER_RE = re.compile(
    r"(\{\{[^{}]+\}\}|<TODO>|<PLACEHOLDER>|lorem ipsum|\bxxxx\b)",
    re.IGNORECASE,
)
EMU_PER_INCH = 914400
OVERLAP_RATIO_THRESHOLD = 0.12
ICON_NAME_RE = re.compile(r"^\[icon:([a-z0-9-]+):([a-z0-9-]+)\]$")


def _shape_text(shape) -> str:
    if not getattr(shape, "has_text_frame", False):
        return ""
    return shape.text.strip()


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


def _is_flat_container_pair(left, right, ratio: float) -> bool:
    if ratio < 0.94:
        return False
    left_text = bool(_shape_text(left))
    right_text = bool(_shape_text(right))
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


def _estimated_capacity(shape) -> int:
    """Estimate readable character capacity; visual inspection remains final."""
    width_inches = shape.width / 914400
    height_inches = shape.height / 914400
    point_size = max(_font_floor(shape) or 18.0, 9)
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


def _one_line_capacity(shape) -> int:
    point_size = max(_font_ceiling(shape) or 35.0, 9)
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


def _layout_findings(presentation) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
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
            capacity = max(_estimated_capacity(shape), 1)
            explicit_lines = max(text.count("\n") + 1, 1)
            estimated_lines = max(
                math.ceil(len(text) / max(_one_line_capacity(shape), 1)),
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
            if is_title and estimated_lines > 1:
                findings.append(
                    _finding(
                        "error",
                        f"slide:{slide_number}:title-wrap:{shape_id}",
                        estimated_lines,
                        f"Slide {slide_number}: title {shape.name!r} is likely to wrap "
                        f"to {estimated_lines} lines; shorten it or change layout",
                    )
                )
            floor = _font_floor(shape)
            minimum = 35 if is_title else 16
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

        rounded_ratio = len(rounded) / max(len(content_shapes), 1)
        if len(rounded) >= 3:
            severity = (
                "error" if len(rounded) >= 4 or rounded_ratio >= 0.5 else "warning"
            )
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:rounded-cards",
                    len(rounded),
                    f"Slide {slide_number}: {len(rounded)} rounded rectangles create "
                    "a card-grid/UI look; use a flatter composition",
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
            if minimum_side < 0.28:
                findings.append(
                    _finding(
                        "warning",
                        f"slide:{slide_number}:small-icon:{_shape_id(shape)}",
                        0.28 - minimum_side,
                        f"Slide {slide_number}: {family}:{icon_name} is only "
                        f"{minimum_side:.2f}in; use at least 0.28in",
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
        if len(icons) > 6:
            severity = "error" if len(icons) > 10 else "warning"
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:icon-density",
                    len(icons),
                    f"Slide {slide_number}: {len(icons)} icons compete for attention; "
                    "use icons only where they carry meaning",
                )
            )
        if len(content_shapes) > 12 or len(text_shapes) > 6:
            density = max(len(content_shapes) / 12, len(text_shapes) / 6)
            severity = (
                "error"
                if len(content_shapes) > 18 or len(text_shapes) > 9
                else "warning"
            )
            findings.append(
                _finding(
                    severity,
                    f"slide:{slide_number}:density",
                    density,
                    f"Slide {slide_number}: layout is dense "
                    f"({len(content_shapes)} items, {len(text_shapes)} text blocks); "
                    "split the message or choose one stronger composition",
                )
            )

        metrics.append(
            {
                "slide": slide_number,
                "content_shapes": len(content_shapes),
                "text_shapes": len(text_shapes),
                "rounded_shapes": len(rounded),
                "icon_count": len(icons),
                "icon_families": icon_families,
                "overlaps": overlaps,
            }
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
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
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
    layout_findings, layout_metrics = _layout_findings(presentation)
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
        "layout": {
            "findings": retained_findings,
            "metrics": layout_metrics,
            "reference_baseline": str(reference) if reference else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--compare-to", type=Path)
    args = parser.parse_args()

    report = inspect_pptx(args.file, reference=args.compare_to)
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
