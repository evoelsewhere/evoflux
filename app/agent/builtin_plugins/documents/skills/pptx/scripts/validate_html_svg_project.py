#!/usr/bin/env python3
"""Validate a static HTML/SVG-to-PPTX project without rendering it."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = 8
MAX_SLIDES = 80
MAX_HTML_BYTES = 2_000_000
MAX_CSS_BYTES = 2_000_000
MAX_ASSET_BYTES = 20_000_000
MAX_TOTAL_ASSET_BYTES = 60_000_000
MAX_ASSETS_PER_SLIDE = 80
ALLOWED_EDITABLE_KINDS = {"text", "shape", "image", "svg", "table", "chart"}
ALLOWED_SHAPES = {"rect", "roundrect", "ellipse", "line", "connector"}
ALLOWED_ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".json",
    ".csv",
    ".tsv",
}
DISALLOWED_TAGS = {
    "script",
    "iframe",
    "object",
    "embed",
    "video",
    "audio",
    "canvas",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "template",
}
ASSET_TOKEN = re.compile(r"asset://([A-Za-z][A-Za-z0-9_-]{0,63})")
UNSAFE_URL = re.compile(
    r"(?:javascript:|vbscript:|data:text/html|https?://|(?<!asset:)//)", re.I
)
UNSAFE_CSS = re.compile(r"(?:</?style\b|@import|expression\s*\(|-moz-binding)", re.I)
PLACEHOLDER = re.compile(r"\b(?:lorem ipsum|todo|tbd|click to add)\b", re.I)
VALID_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
VALID_ASSET_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class ProjectValidationError(ValueError):
    """Raised when a project cannot safely enter the render pipeline."""


class SlideHTMLParser(HTMLParser):
    """Collect the static contract needed before browser rendering."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_count = 0
        self.editable: list[dict[str, str]] = []
        self.art_count = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._editable_svg_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if normalized_tag in DISALLOWED_TAGS:
            self.errors.append(f"disallowed HTML element <{normalized_tag}>")
        if any(key.startswith("on") for key in values):
            self.errors.append(f"inline event handler on <{normalized_tag}>")
        if any(UNSAFE_URL.search(value) for value in values.values()):
            self.errors.append(f"network or executable URL on <{normalized_tag}>")
        if "data-slide-root" in values:
            self.root_count += 1
        if values.get("data-pptx-mode") == "art":
            self.art_count += 1

        kind = values.get("data-pptx-editable")
        enters_editable_svg = normalized_tag == "svg" and kind == "svg"
        if enters_editable_svg:
            self._editable_svg_depth += 1
        elif self._editable_svg_depth:
            self._editable_svg_depth += 1

        if self._editable_svg_depth and normalized_tag == "foreignobject":
            self.errors.append(
                "editable SVG contains <foreignObject>; keep it in art mode or rasterize it"
            )
        if self._editable_svg_depth and normalized_tag == "text":
            self.warnings.append(
                "editable SVG contains <text>; it will not become native PowerPoint text"
            )

        if kind:
            name = values.get("data-pptx-name", "").strip()
            if kind not in ALLOWED_EDITABLE_KINDS:
                self.errors.append(f"unsupported data-pptx-editable kind {kind!r}")
            if not name:
                self.errors.append(
                    f"{kind!r} object on <{normalized_tag}> needs data-pptx-name"
                )
            if kind == "svg" and normalized_tag != "svg":
                self.errors.append(
                    'data-pptx-editable="svg" must be placed on an <svg> element'
                )
            if kind == "shape":
                shape = values.get("data-pptx-shape", "").lower()
                if shape not in ALLOWED_SHAPES:
                    self.errors.append(
                        "editable shape needs data-pptx-shape="
                        '"rect|roundRect|ellipse|line|connector"'
                    )
            if kind in {"table", "chart"} and not ASSET_TOKEN.fullmatch(
                values.get("data-pptx-source", "")
            ):
                self.errors.append(
                    f'editable {kind} needs data-pptx-source="asset://<declared-key>"'
                )
            self.editable.append({"kind": kind, "name": name, "tag": normalized_tag})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        depth = self._editable_svg_depth
        self.handle_starttag(tag, attrs)
        self._editable_svg_depth = depth

    def handle_endtag(self, tag: str) -> None:
        if self._editable_svg_depth:
            self._editable_svg_depth -= 1


def _project_file(project_dir: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 2_000:
        raise ProjectValidationError(f"{label} must be a non-empty relative path")
    candidate = (project_dir / value).resolve(strict=False)
    try:
        candidate.relative_to(project_dir)
    except ValueError as exc:
        raise ProjectValidationError(
            f"{label} must stay inside the project directory"
        ) from exc
    if not candidate.is_file():
        raise ProjectValidationError(f"{label} does not exist: {candidate}")
    return candidate


def _read_limited(path: Path, limit: int, *, label: str) -> str:
    if path.stat().st_size > limit:
        raise ProjectValidationError(f"{label} exceeds {limit} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectValidationError(f"{label} is not UTF-8") from exc


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProjectValidationError(f"{label} must be an array")
    return value


def validate_project(project_path: Path) -> dict[str, Any]:
    """Validate *project_path* and return a JSON-serializable summary."""

    project_path = project_path.expanduser().resolve()
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectValidationError(f"cannot read project JSON: {exc}") from exc
    project = _require_mapping(project, label="project")
    if project.get("schema_version") != SCHEMA_VERSION:
        raise ProjectValidationError(
            f"schema_version must be {SCHEMA_VERSION}, got {project.get('schema_version')!r}"
        )
    if not isinstance(project.get("title"), str) or not project["title"].strip():
        raise ProjectValidationError("title must be a non-empty string")
    width = project.get("width", 1280)
    height = project.get("height", 720)
    if not isinstance(width, int) or not 640 <= width <= 3840:
        raise ProjectValidationError("width must be an integer from 640 to 3840")
    if not isinstance(height, int) or not 360 <= height <= 2160:
        raise ProjectValidationError("height must be an integer from 360 to 2160")
    slides = _require_list(project.get("slides"), label="slides")
    if not 1 <= len(slides) <= MAX_SLIDES:
        raise ProjectValidationError(f"slides must contain 1 to {MAX_SLIDES} items")

    project_dir = project_path.parent
    slide_ids: set[str] = set()
    slide_summaries: list[dict[str, Any]] = []
    for index, raw_slide in enumerate(slides, start=1):
        slide = _require_mapping(raw_slide, label=f"slide {index}")
        slide_id = slide.get("id")
        if not isinstance(slide_id, str) or not VALID_ID.fullmatch(slide_id):
            raise ProjectValidationError(f"slide {index} has an invalid id")
        if slide_id in slide_ids:
            raise ProjectValidationError(f"duplicate slide id: {slide_id}")
        slide_ids.add(slide_id)

        html_path = _project_file(
            project_dir, slide.get("html_path"), label=f"slide {slide_id} html_path"
        )
        html = _read_limited(html_path, MAX_HTML_BYTES, label=f"slide {slide_id} HTML")
        style_paths = _require_list(
            slide.get("style_paths", []), label=f"slide {slide_id} style_paths"
        )
        if len(style_paths) > 8:
            raise ProjectValidationError(
                f"slide {slide_id} has more than 8 stylesheets"
            )
        css_parts: list[str] = []
        for style_index, raw_path in enumerate(style_paths, start=1):
            style_path = _project_file(
                project_dir,
                raw_path,
                label=f"slide {slide_id} stylesheet {style_index}",
            )
            css_parts.append(
                _read_limited(
                    style_path,
                    MAX_CSS_BYTES,
                    label=f"slide {slide_id} stylesheet {style_index}",
                )
            )
        css = "\n".join(css_parts)
        if len(css.encode("utf-8")) > MAX_CSS_BYTES:
            raise ProjectValidationError(
                f"slide {slide_id} combined CSS exceeds {MAX_CSS_BYTES} bytes"
            )
        if UNSAFE_URL.search(html) or UNSAFE_URL.search(css):
            raise ProjectValidationError(
                f"slide {slide_id} contains a network or executable URL"
            )
        if UNSAFE_CSS.search(css):
            raise ProjectValidationError(f"slide {slide_id} contains unsafe CSS")
        if PLACEHOLDER.search(html):
            raise ProjectValidationError(
                f"slide {slide_id} contains unresolved placeholder text"
            )

        parser = SlideHTMLParser()
        parser.feed(html)
        parser.close()
        if parser.root_count != 1:
            raise ProjectValidationError(
                f"slide {slide_id} must contain exactly one data-slide-root"
            )
        if parser.errors:
            raise ProjectValidationError(
                f"slide {slide_id}: " + "; ".join(dict.fromkeys(parser.errors))
            )
        names = [item["name"] for item in parser.editable if item["name"]]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ProjectValidationError(
                f"slide {slide_id} has duplicate data-pptx-name values: "
                + ", ".join(duplicates)
            )

        assets = _require_mapping(
            slide.get("assets", {}), label=f"slide {slide_id} assets"
        )
        if len(assets) > MAX_ASSETS_PER_SLIDE:
            raise ProjectValidationError(
                f"slide {slide_id} has more than {MAX_ASSETS_PER_SLIDE} assets"
            )
        total_asset_bytes = 0
        for key, raw_path in assets.items():
            if not isinstance(key, str) or not VALID_ASSET_ID.fullmatch(key):
                raise ProjectValidationError(
                    f"slide {slide_id} has an invalid asset id: {key!r}"
                )
            asset_path = _project_file(
                project_dir, raw_path, label=f"slide {slide_id} asset {key}"
            )
            if asset_path.suffix.lower() not in ALLOWED_ASSET_SUFFIXES:
                raise ProjectValidationError(
                    f"slide {slide_id} asset {key} has unsupported type {asset_path.suffix}"
                )
            size = asset_path.stat().st_size
            if size > MAX_ASSET_BYTES:
                raise ProjectValidationError(
                    f"slide {slide_id} asset {key} exceeds {MAX_ASSET_BYTES} bytes"
                )
            total_asset_bytes += size
        if total_asset_bytes > MAX_TOTAL_ASSET_BYTES:
            raise ProjectValidationError(
                f"slide {slide_id} assets exceed {MAX_TOTAL_ASSET_BYTES} bytes"
            )
        referenced_assets = set(ASSET_TOKEN.findall(html + "\n" + css))
        missing_assets = sorted(referenced_assets - set(assets))
        if missing_assets:
            raise ProjectValidationError(
                f"slide {slide_id} references undeclared assets: "
                + ", ".join(missing_assets)
            )

        notes = slide.get("speaker_notes", "")
        if not isinstance(notes, str) or len(notes) > 40_000:
            raise ProjectValidationError(
                f"slide {slide_id} speaker_notes must be a string up to 40000 characters"
            )
        counts = {kind: 0 for kind in sorted(ALLOWED_EDITABLE_KINDS)}
        for item in parser.editable:
            if item["kind"] in counts:
                counts[item["kind"]] += 1
        slide_summaries.append(
            {
                "slide": index,
                "id": slide_id,
                "editable_counts": counts,
                "art_blocks": parser.art_count,
                "warnings": list(dict.fromkeys(parser.warnings)),
            }
        )

    return {
        "valid": True,
        "schema_version": SCHEMA_VERSION,
        "title": project["title"],
        "canvas": {"width": width, "height": height, "unit": "CSS px"},
        "slide_count": len(slides),
        "slides": slide_summaries,
        "render_surfaces": "unverified",
        "editability": "unverified until the exact PPTX is reopened",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a static HTML/SVG-to-PPTX project without rendering it."
    )
    parser.add_argument("project", type=Path, help="Path to project.json")
    args = parser.parse_args()
    project_path = args.project.expanduser().resolve()
    try:
        result = validate_project(project_path)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "project": str(project_path),
                    "error": str(exc),
                    "render_surfaces": "unverified",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {"project": str(project_path), **result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
