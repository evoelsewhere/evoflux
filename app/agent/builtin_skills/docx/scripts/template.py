"""Inspect, patch, and verify DOCX templates without rebuilding the document."""

from __future__ import annotations

import argparse
import json
import re
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

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": W, "w14": W14}
CONTENT_PART_RE = re.compile(
    r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$"
)
PROTECTED = (
    "word/styles.xml",
    "word/numbering.xml",
    "word/settings.xml",
    "word/theme/*",
    "word/fontTable.xml",
)


def _content_parts(package: zipfile.ZipFile) -> list[str]:
    return sorted(name for name in package.namelist() if CONTENT_PART_RE.match(name))


def _text(node: ET.Element) -> str:
    return "".join(item.text or "" for item in node.findall(".//w:t", NS))


def _set_text(node: ET.Element, value: str) -> None:
    runs = node.findall(".//w:t", NS)
    if not runs:
        raise ValueError("Target has no editable Word text runs")
    runs[0].text = value
    for run in runs[1:]:
        run.text = ""


def _paragraphs(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//w:p", NS)


def _paragraph(root: ET.Element, edit: dict[str, Any]) -> ET.Element:
    paragraphs = _paragraphs(root)
    if "para_id" in edit:
        wanted = str(edit["para_id"]).upper()
        matches = [
            paragraph
            for paragraph in paragraphs
            if (paragraph.get(f"{{{W14}}}paraId") or "").upper() == wanted
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one para_id={wanted}, found {len(matches)}")
        return matches[0]
    index = int(edit["paragraph"])
    try:
        return paragraphs[index]
    except IndexError as exc:
        raise ValueError(f"Paragraph index {index} is out of range") from exc


def _sdt(root: ET.Element, tag: str) -> ET.Element:
    matches = []
    for control in root.findall(".//w:sdt", NS):
        marker = control.find("./w:sdtPr/w:tag", NS)
        if marker is not None and marker.get(f"{{{W}}}val") == tag:
            matches.append(control)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one content-control tag={tag!r}, found {len(matches)}"
        )
    return matches[0]


def _table_cell(
    root: ET.Element,
    table_index: int,
    row_index: int,
    column_index: int,
) -> ET.Element:
    try:
        table = root.findall(".//w:tbl", NS)[table_index]
        row = table.findall("./w:tr", NS)[row_index]
        return row.findall("./w:tc", NS)[column_index]
    except IndexError as exc:
        raise ValueError("Table, row, or column index is out of range") from exc


def inspect(path: Path) -> dict[str, object]:
    hashes = package_hashes(path)
    with zipfile.ZipFile(path) as package:
        parts = []
        for part in _content_parts(package):
            root = ET.fromstring(package.read(part))
            paragraphs = []
            for index, paragraph in enumerate(_paragraphs(root)):
                style = paragraph.find("./w:pPr/w:pStyle", NS)
                paragraphs.append(
                    {
                        "paragraph": index,
                        "para_id": paragraph.get(f"{{{W14}}}paraId"),
                        "style": (
                            style.get(f"{{{W}}}val") if style is not None else None
                        ),
                        "text": _text(paragraph),
                    }
                )
            controls = []
            for control in root.findall(".//w:sdt", NS):
                marker = control.find("./w:sdtPr/w:tag", NS)
                controls.append(
                    {
                        "tag": (
                            marker.get(f"{{{W}}}val") if marker is not None else None
                        ),
                        "text": _text(control),
                    }
                )
            tables = [
                {
                    "table": table_index,
                    "rows": len(table.findall("./w:tr", NS)),
                    "columns": max(
                        (
                            len(row.findall("./w:tc", NS))
                            for row in table.findall("./w:tr", NS)
                        ),
                        default=0,
                    ),
                }
                for table_index, table in enumerate(root.findall(".//w:tbl", NS))
            ]
            parts.append(
                {
                    "part": part,
                    "paragraphs": paragraphs,
                    "content_controls": controls,
                    "tables": tables,
                }
            )
    return {
        "file": str(path),
        "parts": parts,
        "protected_parts": {
            part: digest
            for part, digest in hashes.items()
            if any(
                part == pattern
                or (pattern.endswith("*") and part.startswith(pattern[:-1]))
                for pattern in PROTECTED
            )
        },
    }


def _allowed(plan: dict[str, Any]) -> list[str]:
    parts = []
    for raw in plan["edits"]:
        part = str(dict(raw).get("part", "word/document.xml"))
        if not CONTENT_PART_RE.match(part):
            raise ValueError(f"Unsupported DOCX content part: {part}")
        parts.append(part)
    return sorted(set(parts))


def apply(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    allowed = _allowed(plan)
    replacements: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as package:
        roots = {part: ET.fromstring(package.read(part)) for part in allowed}
        for raw in plan["edits"]:
            edit = dict(raw)
            part = str(edit.get("part", "word/document.xml"))
            root = roots[part]
            action = edit["action"]
            if action == "replace_paragraph":
                _set_text(_paragraph(root, edit), str(edit["text"]))
            elif action == "replace_content_control":
                _set_text(_sdt(root, str(edit["tag"])), str(edit["text"]))
            elif action == "replace_table_cell":
                cell = _table_cell(
                    root,
                    int(edit["table"]),
                    int(edit["row"]),
                    int(edit["column"]),
                )
                _set_text(cell, str(edit["text"]))
            else:
                raise ValueError(f"Unsupported DOCX edit action: {action}")
        replacements = {
            part: ET.tostring(root, encoding="utf-8", xml_declaration=True)
            for part, root in roots.items()
        }
    patch_package(source, output, replacements)
    report = fidelity_report(source, output, allowed, protected_patterns=PROTECTED)
    report["output"] = str(output)
    return report


def verify(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="evoflux-docx-plan-") as directory:
        expected = Path(directory) / f"expected{source.suffix}"
        apply(source, expected, plan)
        return planned_output_report(
            source,
            expected,
            output,
            _allowed(plan),
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
