"""Inspect, patch, and verify PPTX templates without rebuilding the deck."""

from __future__ import annotations

import argparse
import copy
import json
import posixpath
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from openpyxl import load_workbook

for parent in Path(__file__).resolve().parents:
    if (parent / "app" / "agent" / "builtin_skills").is_dir():
        sys.path.insert(0, str(parent))
        break

from app.agent.builtin_skills.template_fidelity import (  # noqa: E402
    fidelity_report,
    load_plan,
    package_hashes,
    patch_package,
    planned_output_report,
)

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"a": A, "c": C, "p": P, "r": R, "rel": REL}
PROTECTED = ("ppt/slideMasters/*", "ppt/slideLayouts/*", "ppt/theme/*")


def _ordered_slides(package: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(package.read("ppt/presentation.xml"))
    rels = ET.fromstring(package.read("ppt/_rels/presentation.xml.rels"))
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall("rel:Relationship", NS)
        if rel.get("Id") and rel.get("Target")
    }
    slides = []
    for slide_id in root.findall("./p:sldIdLst/p:sldId", NS):
        target = targets[slide_id.get(f"{{{R}}}id")]
        if not isinstance(target, str):
            raise ValueError("Presentation contains an invalid slide relationship")
        slides.append(posixpath.normpath(posixpath.join("ppt", target)).lstrip("/"))
    return slides


def _shape_nodes(root: ET.Element) -> list[ET.Element]:
    tree = root.find("./p:cSld/p:spTree", NS)
    return list(tree) if tree is not None else []


def _shape_id(shape: ET.Element) -> int | None:
    node = shape.find(".//p:cNvPr", NS)
    value = node.get("id") if node is not None else None
    return int(value) if value else None


def _shape(root: ET.Element, shape_id: int) -> ET.Element:
    matches = [node for node in _shape_nodes(root) if _shape_id(node) == shape_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one shape_id={shape_id}, found {len(matches)}")
    return matches[0]


def _set_text(nodes: list[ET.Element], value: str) -> None:
    if not nodes:
        raise ValueError("Target has no editable DrawingML text runs")
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ""


def _rels_name(owner_part: str) -> str:
    directory, filename = posixpath.split(owner_part)
    return f"{directory}/_rels/{filename}.rels"


def _related_part(
    package: zipfile.ZipFile,
    owner_part: str,
    relation_id: str,
) -> str:
    rels = ET.fromstring(package.read(_rels_name(owner_part)))
    for relation in rels.findall("rel:Relationship", NS):
        if relation.get("Id") == relation_id:
            target = relation.get("Target")
            if target is None:
                raise ValueError(f"Relationship {relation_id!r} has no target")
            return posixpath.normpath(
                posixpath.join(posixpath.dirname(owner_part), target)
            ).lstrip("/")
    raise ValueError(f"Relationship {relation_id!r} was not found")


def _image_part(
    package: zipfile.ZipFile,
    slide_part: str,
    shape: ET.Element,
) -> str:
    blip = shape.find(".//a:blip", NS)
    relation_id = blip.get(f"{{{R}}}embed") if blip is not None else None
    if not relation_id:
        raise ValueError("Target shape is not an embedded image")
    return _related_part(package, slide_part, relation_id)


def _chart_parts(
    package: zipfile.ZipFile,
    slide_part: str,
    shape: ET.Element,
) -> tuple[str, str]:
    chart = shape.find(".//c:chart", NS)
    relation_id = chart.get(f"{{{R}}}id") if chart is not None else None
    if not relation_id:
        raise ValueError("Target shape is not an embedded chart")
    chart_part = _related_part(package, slide_part, relation_id)
    rels = ET.fromstring(package.read(_rels_name(chart_part)))
    workbook_relation = next(
        (
            relation
            for relation in rels.findall("rel:Relationship", NS)
            if str(relation.get("Type", "")).endswith("/package")
        ),
        None,
    )
    if workbook_relation is None or not workbook_relation.get("Id"):
        raise ValueError("Chart has no embedded workbook relationship")
    workbook_part = _related_part(
        package,
        chart_part,
        str(workbook_relation.get("Id")),
    )
    return chart_part, workbook_part


def _set_cache(
    cache: ET.Element | None,
    values: Sequence[str | int | float],
) -> None:
    if cache is None:
        raise ValueError("Chart series is missing its cached data")
    for point in list(cache.findall("c:pt", NS)):
        cache.remove(point)
    point_count = cache.find("c:ptCount", NS)
    if point_count is None:
        point_count = ET.Element(f"{{{C}}}ptCount")
        cache.insert(0, point_count)
    point_count.set("val", str(len(values)))
    for index, value in enumerate(values):
        point = ET.SubElement(cache, f"{{{C}}}pt", {"idx": str(index)})
        ET.SubElement(point, f"{{{C}}}v").text = str(value)


def _set_formula(reference: ET.Element | None, formula: str) -> None:
    if reference is None:
        raise ValueError("Chart series is missing a workbook reference")
    node = reference.find("c:f", NS)
    if node is None:
        node = ET.SubElement(reference, f"{{{C}}}f")
    node.text = formula


def _preserve_workbook_core_properties(original: bytes, updated: bytes) -> bytes:
    """Keep embedded-workbook metadata stable across deterministic edits.

    openpyxl rewrites ``dcterms:modified`` on every save, making the same
    declared mutation differ solely because it ran at another wall-clock time.
    """
    with zipfile.ZipFile(BytesIO(original)) as source:
        core_properties = source.read("docProps/core.xml")
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(updated)) as incoming:
        with zipfile.ZipFile(output, "w") as outgoing:
            for item in incoming.infolist():
                payload = (
                    core_properties
                    if item.filename == "docProps/core.xml"
                    else incoming.read(item.filename)
                )
                outgoing.writestr(item, payload)
    return output.getvalue()


def _replace_chart_data(
    package: zipfile.ZipFile,
    slide_part: str,
    shape: ET.Element,
    edit: dict[str, Any],
) -> dict[str, bytes]:
    categories = [str(value) for value in edit["categories"]]
    series_specs = [dict(value) for value in edit["series"]]
    if not categories or not series_specs:
        raise ValueError("replace_chart_data requires categories and series")
    for specification in series_specs:
        values = specification.get("values", [])
        if len(values) != len(categories):
            raise ValueError(
                f"Chart series {specification.get('name', '')!r} does not match "
                "the category count"
            )

    chart_part, workbook_part = _chart_parts(package, slide_part, shape)
    original_workbook = package.read(workbook_part)
    workbook = load_workbook(BytesIO(original_workbook))
    worksheet = workbook.active
    for row in worksheet.iter_rows():
        for cell in row:
            cell.value = None
    worksheet.cell(1, 1, "")
    for row_index, category in enumerate(categories, start=2):
        worksheet.cell(row_index, 1, category)
    for column_index, specification in enumerate(series_specs, start=2):
        worksheet.cell(1, column_index, str(specification["name"]))
        for row_index, value in enumerate(specification["values"], start=2):
            worksheet.cell(row_index, column_index, float(value))
    workbook_buffer = BytesIO()
    workbook.save(workbook_buffer)
    workbook_payload = _preserve_workbook_core_properties(
        original_workbook, workbook_buffer.getvalue()
    )

    chart_root = ET.fromstring(package.read(chart_part))
    chart_series = chart_root.findall(".//c:ser", NS)
    if len(chart_series) != len(series_specs):
        raise ValueError(
            f"Chart has {len(chart_series)} existing series but the edit specifies "
            f"{len(series_specs)}; preserve the chart structure"
        )
    escaped_sheet = worksheet.title.replace("'", "''")
    last_row = len(categories) + 1
    for column_index, (series_node, specification) in enumerate(
        zip(chart_series, series_specs, strict=True),
        start=2,
    ):
        column_letter = worksheet.cell(1, column_index).column_letter
        name = str(specification["name"])
        values = [float(value) for value in specification["values"]]
        text_reference = series_node.find("./c:tx/c:strRef", NS)
        _set_formula(text_reference, f"'{escaped_sheet}'!${column_letter}$1")
        _set_cache(
            text_reference.find("c:strCache", NS)
            if text_reference is not None
            else None,
            [name],
        )
        category_reference = series_node.find("./c:cat/c:strRef", NS)
        if category_reference is None:
            category_reference = series_node.find("./c:cat/c:numRef", NS)
        _set_formula(
            category_reference,
            f"'{escaped_sheet}'!$A$2:$A${last_row}",
        )
        category_cache = (
            category_reference.find("c:strCache", NS)
            if category_reference is not None
            else None
        )
        if category_cache is None and category_reference is not None:
            category_cache = category_reference.find("c:numCache", NS)
        _set_cache(category_cache, categories)
        value_reference = series_node.find("./c:val/c:numRef", NS)
        _set_formula(
            value_reference,
            f"'{escaped_sheet}'!${column_letter}$2:${column_letter}${last_row}",
        )
        _set_cache(
            value_reference.find("c:numCache", NS)
            if value_reference is not None
            else None,
            values,
        )
    return {
        chart_part: ET.tostring(
            chart_root,
            encoding="utf-8",
            xml_declaration=True,
        ),
        workbook_part: workbook_payload,
    }


def _run_properties(
    template: ET.Element | None,
    specification: dict[str, Any],
) -> ET.Element:
    properties = (
        copy.deepcopy(template) if template is not None else ET.Element(f"{{{A}}}rPr")
    )
    for key, attribute in (
        ("bold", "b"),
        ("italic", "i"),
    ):
        if key in specification:
            properties.set(attribute, "1" if specification[key] else "0")
    if "underline" in specification:
        properties.set("u", "sng" if specification["underline"] else "none")
    if "size" in specification:
        properties.set("sz", str(round(float(specification["size"]) * 100)))
    if "font" in specification:
        latin = properties.find("a:latin", NS)
        if latin is None:
            latin = ET.SubElement(properties, f"{{{A}}}latin")
        latin.set("typeface", str(specification["font"]))
    if "color" in specification:
        for tag in ("solidFill", "gradFill", "noFill", "pattFill"):
            fill = properties.find(f"a:{tag}", NS)
            if fill is not None:
                properties.remove(fill)
        fill = ET.Element(f"{{{A}}}solidFill")
        ET.SubElement(
            fill,
            f"{{{A}}}srgbClr",
            {"val": str(specification["color"]).removeprefix("#").upper()},
        )
        properties.insert(0, fill)
    return properties


def _replace_rich_text(shape: ET.Element, edit: dict[str, Any]) -> None:
    text_body = shape.find(".//p:txBody", NS)
    if text_body is None:
        text_body = shape.find(".//a:txBody", NS)
    if text_body is None:
        raise ValueError("Target has no editable rich-text body")
    specifications = [dict(value) for value in edit.get("paragraphs", [])]
    if not specifications:
        raise ValueError("replace_rich_text requires paragraphs")
    template_run = text_body.find(".//a:r/a:rPr", NS)
    template_end = text_body.find(".//a:endParaRPr", NS)
    for paragraph in list(text_body.findall("a:p", NS)):
        text_body.remove(paragraph)

    alignments = {
        "left": "l",
        "center": "ctr",
        "right": "r",
        "justify": "just",
    }
    for paragraph_specification in specifications:
        runs = [dict(value) for value in paragraph_specification.get("runs", [])]
        if not runs:
            raise ValueError("Every rich-text paragraph requires runs")
        paragraph = ET.SubElement(text_body, f"{{{A}}}p")
        paragraph_properties = ET.SubElement(paragraph, f"{{{A}}}pPr")
        level = int(paragraph_specification.get("level", 0))
        paragraph_properties.set("lvl", str(level))
        alignment = paragraph_specification.get("align")
        if alignment:
            paragraph_properties.set("algn", alignments[str(alignment)])
        if paragraph_specification.get("bullet"):
            paragraph_properties.set("marL", str(237600 + level * 201168))
            paragraph_properties.set("indent", "-144000")
            ET.SubElement(
                paragraph_properties,
                f"{{{A}}}buChar",
                {"char": "•"},
            )
        else:
            ET.SubElement(paragraph_properties, f"{{{A}}}buNone")
        if "space_after_pt" in paragraph_specification:
            spacing = ET.SubElement(paragraph_properties, f"{{{A}}}spcAft")
            ET.SubElement(
                spacing,
                f"{{{A}}}spcPts",
                {
                    "val": str(
                        round(float(paragraph_specification["space_after_pt"]) * 100)
                    )
                },
            )
        for run_specification in runs:
            run = ET.SubElement(paragraph, f"{{{A}}}r")
            run.append(_run_properties(template_run, run_specification))
            text = ET.SubElement(run, f"{{{A}}}t")
            value = str(run_specification.get("text", ""))
            if value != value.strip():
                text.set(f"{{{XML}}}space", "preserve")
            text.text = value
        paragraph.append(
            copy.deepcopy(template_end)
            if template_end is not None
            else ET.Element(f"{{{A}}}endParaRPr")
        )


def inspect(path: Path) -> dict[str, object]:
    hashes = package_hashes(path)
    with zipfile.ZipFile(path) as package:
        slide_parts = _ordered_slides(package)
        slides = []
        for number, part in enumerate(slide_parts, start=1):
            root = ET.fromstring(package.read(part))
            shapes = []
            for shape in _shape_nodes(root):
                shape_id = _shape_id(shape)
                if shape_id is None:
                    continue
                name = shape.find(".//p:cNvPr", NS)
                xfrm = shape.find(".//a:xfrm", NS)
                off = xfrm.find("a:off", NS) if xfrm is not None else None
                ext = xfrm.find("a:ext", NS) if xfrm is not None else None
                placeholder = shape.find(".//p:ph", NS)
                shapes.append(
                    {
                        "shape_id": shape_id,
                        "name": name.get("name", "") if name is not None else "",
                        "kind": shape.tag.rsplit("}", 1)[-1],
                        "placeholder": placeholder is not None,
                        "placeholder_type": (
                            placeholder.get("type", "body")
                            if placeholder is not None
                            else None
                        ),
                        "placeholder_index": (
                            placeholder.get("idx") if placeholder is not None else None
                        ),
                        "text": "".join(
                            node.text or "" for node in shape.findall(".//a:t", NS)
                        ),
                        "rich_text_runs": len(shape.findall(".//a:r", NS)),
                        "has_chart": shape.find(".//c:chart", NS) is not None,
                        "has_table": shape.find(".//a:tbl", NS) is not None,
                        "has_image": shape.find(".//a:blip", NS) is not None,
                        "has_hyperlink": shape.find(".//a:hlinkClick", NS) is not None,
                        "grouped": shape.tag == f"{{{P}}}grpSp",
                        "geometry": {
                            "x": off.get("x") if off is not None else None,
                            "y": off.get("y") if off is not None else None,
                            "cx": ext.get("cx") if ext is not None else None,
                            "cy": ext.get("cy") if ext is not None else None,
                        },
                    }
                )
            slides.append(
                {
                    "slide": number,
                    "part": part,
                    "transition": root.find("./p:transition", NS) is not None,
                    "animation_timeline": root.find("./p:timing", NS) is not None,
                    "shapes": shapes,
                }
            )
    return {
        "file": str(path),
        "slides": slides,
        "protected_parts": {
            part: digest
            for part, digest in hashes.items()
            if any(part.startswith(prefix[:-1]) for prefix in PROTECTED)
        },
    }


def _resolve_allowed(source: Path, plan: dict[str, Any]) -> list[str]:
    allowed: set[str] = set()
    with zipfile.ZipFile(source) as package:
        slides = _ordered_slides(package)
        for raw in plan["edits"]:
            edit = dict(raw)
            slide_part = slides[int(edit["slide"]) - 1]
            action = edit["action"]
            if action in {
                "replace_text",
                "fill_placeholder",
                "replace_rich_text",
                "replace_table_cell",
            }:
                allowed.add(slide_part)
            elif action == "replace_image":
                root = ET.fromstring(package.read(slide_part))
                allowed.add(
                    _image_part(
                        package, slide_part, _shape(root, int(edit["shape_id"]))
                    )
                )
            elif action == "replace_chart_data":
                root = ET.fromstring(package.read(slide_part))
                chart_part, workbook_part = _chart_parts(
                    package,
                    slide_part,
                    _shape(root, int(edit["shape_id"])),
                )
                allowed.update((chart_part, workbook_part))
            else:
                raise ValueError(f"Unsupported PPTX edit action: {action}")
    return sorted(allowed)


def apply(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    replacements: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as package:
        slides = _ordered_slides(package)
        roots: dict[str, ET.Element] = {}
        dirty_slides: set[str] = set()
        for raw in plan["edits"]:
            edit = dict(raw)
            slide_number = int(edit["slide"])
            if not 1 <= slide_number <= len(slides):
                raise ValueError(f"Slide {slide_number} is out of range")
            part = slides[slide_number - 1]
            root = roots.setdefault(part, ET.fromstring(package.read(part)))
            shape = _shape(root, int(edit["shape_id"]))
            action = edit["action"]
            if action == "replace_text":
                _set_text(shape.findall(".//a:t", NS), str(edit["text"]))
                dirty_slides.add(part)
            elif action == "fill_placeholder":
                if shape.find(".//p:ph", NS) is None:
                    raise ValueError("fill_placeholder target is not a placeholder")
                _set_text(shape.findall(".//a:t", NS), str(edit["text"]))
                dirty_slides.add(part)
            elif action == "replace_rich_text":
                _replace_rich_text(shape, edit)
                dirty_slides.add(part)
            elif action == "replace_table_cell":
                rows = shape.findall(".//a:tbl/a:tr", NS)
                row = rows[int(edit["row"])]
                cells = row.findall("a:tc", NS)
                _set_text(
                    cells[int(edit["column"])].findall(".//a:t", NS), str(edit["text"])
                )
                dirty_slides.add(part)
            elif action == "replace_image":
                media_part = _image_part(package, part, shape)
                replacement = Path(edit["file"])
                if replacement.suffix.lower() != Path(media_part).suffix.lower():
                    raise ValueError(
                        "Replacement image must use the template image format"
                    )
                replacements[media_part] = replacement.read_bytes()
            elif action == "replace_chart_data":
                replacements.update(_replace_chart_data(package, part, shape, edit))
            else:
                raise ValueError(f"Unsupported PPTX edit action: {action}")
        for part in dirty_slides:
            root = roots[part]
            replacements[part] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
    patch_package(source, output, replacements)
    report = fidelity_report(
        source, output, sorted(replacements), protected_patterns=PROTECTED
    )
    report["output"] = str(output)
    return report


def verify(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="evoflux-pptx-plan-") as directory:
        expected = Path(directory) / f"expected{source.suffix}"
        apply(source, expected, plan)
        return planned_output_report(
            source,
            expected,
            output,
            _resolve_allowed(source, plan),
            protected_patterns=PROTECTED,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--out", type=Path)
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("source", type=Path)
    apply_parser.add_argument("output", type=Path)
    apply_parser.add_argument("--plan", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("source", type=Path)
    verify_parser.add_argument("output", type=Path)
    verify_parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "inspect":
        report = inspect(args.source)
        if args.out:
            args.out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    elif args.command == "apply":
        report = apply(args.source, args.output, load_plan(args.plan))
    else:
        report = verify(args.source, args.output, load_plan(args.plan))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
