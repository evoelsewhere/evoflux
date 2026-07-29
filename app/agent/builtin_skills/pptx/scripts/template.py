"""Inspect, patch, and verify PPTX templates without rebuilding the deck."""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

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
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": A, "p": P, "r": R, "rel": REL}
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


def _slide_rels_name(slide_part: str) -> str:
    directory, filename = posixpath.split(slide_part)
    return f"{directory}/_rels/{filename}.rels"


def _image_part(
    package: zipfile.ZipFile,
    slide_part: str,
    shape: ET.Element,
) -> str:
    blip = shape.find(".//a:blip", NS)
    relation_id = blip.get(f"{{{R}}}embed") if blip is not None else None
    if not relation_id:
        raise ValueError("Target shape is not an embedded image")
    rels = ET.fromstring(package.read(_slide_rels_name(slide_part)))
    for relation in rels.findall("rel:Relationship", NS):
        if relation.get("Id") == relation_id:
            target = relation.get("Target")
            if target is None:
                raise ValueError(f"Image relationship {relation_id!r} has no target")
            return posixpath.normpath(
                posixpath.join(posixpath.dirname(slide_part), target)
            ).lstrip("/")
    raise ValueError(f"Image relationship {relation_id!r} was not found")


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
                shapes.append(
                    {
                        "shape_id": shape_id,
                        "name": name.get("name", "") if name is not None else "",
                        "kind": shape.tag.rsplit("}", 1)[-1],
                        "placeholder": shape.find(".//p:ph", NS) is not None,
                        "text": "".join(
                            node.text or "" for node in shape.findall(".//a:t", NS)
                        ),
                        "geometry": {
                            "x": off.get("x") if off is not None else None,
                            "y": off.get("y") if off is not None else None,
                            "cx": ext.get("cx") if ext is not None else None,
                            "cy": ext.get("cy") if ext is not None else None,
                        },
                    }
                )
            slides.append({"slide": number, "part": part, "shapes": shapes})
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
            if action in {"replace_text", "replace_table_cell"}:
                allowed.add(slide_part)
            elif action == "replace_image":
                root = ET.fromstring(package.read(slide_part))
                allowed.add(
                    _image_part(
                        package, slide_part, _shape(root, int(edit["shape_id"]))
                    )
                )
            else:
                raise ValueError(f"Unsupported PPTX edit action: {action}")
    return sorted(allowed)


def apply(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    replacements: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as package:
        slides = _ordered_slides(package)
        roots: dict[str, ET.Element] = {}
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
            elif action == "replace_table_cell":
                rows = shape.findall(".//a:tbl/a:tr", NS)
                row = rows[int(edit["row"])]
                cells = row.findall("a:tc", NS)
                _set_text(
                    cells[int(edit["column"])].findall(".//a:t", NS), str(edit["text"])
                )
            elif action == "replace_image":
                media_part = _image_part(package, part, shape)
                replacement = Path(edit["file"])
                if replacement.suffix.lower() != Path(media_part).suffix.lower():
                    raise ValueError(
                        "Replacement image must use the template image format"
                    )
                replacements[media_part] = replacement.read_bytes()
            else:
                raise ValueError(f"Unsupported PPTX edit action: {action}")
        for part, root in roots.items():
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
