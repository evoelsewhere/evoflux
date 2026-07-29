"""Inspect, patch, and verify XLSX/XLSM templates without rebuilding workbooks."""

from __future__ import annotations

import argparse
import json
import posixpath
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

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": MAIN, "r": R, "rel": REL}
CELL_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
PROTECTED = (
    "xl/styles.xml",
    "xl/theme/*",
    "xl/drawings/*",
    "xl/charts/*",
    "xl/tables/*",
    "xl/pivotTables/*",
    "xl/pivotCache/*",
    "xl/vbaProject.bin",
)


def _sheets(package: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(package.read("xl/workbook.xml"))
    rels = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relation.get("Id"): relation.get("Target")
        for relation in rels.findall("rel:Relationship", NS)
        if relation.get("Id") and relation.get("Target")
    }
    result = {}
    for sheet in workbook.findall("./x:sheets/x:sheet", NS):
        name = sheet.get("name")
        target = targets[sheet.get(f"{{{R}}}id")]
        if name is None:
            raise ValueError("Workbook contains a worksheet without a name")
        if not isinstance(target, str):
            raise ValueError(f"Worksheet {name!r} has an invalid relationship")
        result[name] = posixpath.normpath(posixpath.join("xl", target)).lstrip("/")
    return result


def _column_number(letters: str) -> int:
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - 64
    return result


def _cell_key(reference: str) -> tuple[int, int]:
    match = CELL_RE.match(reference.upper())
    if not match:
        raise ValueError(f"Invalid A1 cell reference: {reference}")
    return int(match.group(2)), _column_number(match.group(1))


def _cell(root: ET.Element, reference: str) -> ET.Element:
    reference = reference.upper()
    match = root.find(f".//x:c[@r='{reference}']", NS)
    if match is not None:
        return match
    row_number, column_number = _cell_key(reference)
    sheet_data = root.find("./x:sheetData", NS)
    if sheet_data is None:
        sheet_data = ET.SubElement(root, f"{{{MAIN}}}sheetData")
    row = sheet_data.find(f"./x:row[@r='{row_number}']", NS)
    if row is None:
        row = ET.Element(f"{{{MAIN}}}row", {"r": str(row_number)})
        rows = list(sheet_data)
        position = next(
            (
                index
                for index, candidate in enumerate(rows)
                if int(candidate.get("r", "0")) > row_number
            ),
            len(rows),
        )
        sheet_data.insert(position, row)
    cell = ET.Element(f"{{{MAIN}}}c", {"r": reference})
    cells = list(row)
    position = next(
        (
            index
            for index, candidate in enumerate(cells)
            if _cell_key(candidate.get("r") or "A1")[1] > column_number
        ),
        len(cells),
    )
    row.insert(position, cell)
    return cell


def _clear_value(cell: ET.Element) -> None:
    for child in list(cell):
        if child.tag in {
            f"{{{MAIN}}}v",
            f"{{{MAIN}}}f",
            f"{{{MAIN}}}is",
        }:
            cell.remove(child)
    cell.attrib.pop("t", None)


def _set_cell(cell: ET.Element, edit: dict[str, Any]) -> None:
    kind = str(edit.get("kind", "string"))
    _clear_value(cell)
    if kind == "blank":
        return
    if kind == "formula":
        formula = str(edit["value"])
        ET.SubElement(cell, f"{{{MAIN}}}f").text = formula.removeprefix("=")
        return
    if kind == "string":
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{MAIN}}}is")
        ET.SubElement(inline, f"{{{MAIN}}}t").text = str(edit["value"])
        return
    if kind == "boolean":
        cell.set("t", "b")
        value = "1" if bool(edit["value"]) else "0"
    elif kind == "number":
        value = str(edit["value"])
    else:
        raise ValueError(f"Unsupported XLSX cell kind: {kind}")
    ET.SubElement(cell, f"{{{MAIN}}}v").text = value


def _display_value(cell: ET.Element) -> dict[str, object]:
    formula = cell.find("x:f", NS)
    value = cell.find("x:v", NS)
    inline = cell.find("x:is/x:t", NS)
    return {
        "cell": cell.get("r"),
        "style_id": cell.get("s"),
        "type": cell.get("t"),
        "formula": formula.text if formula is not None else None,
        "value": (
            inline.text
            if inline is not None
            else value.text
            if value is not None
            else None
        ),
    }


def inspect(path: Path) -> dict[str, object]:
    hashes = package_hashes(path)
    with zipfile.ZipFile(path) as package:
        sheets = _sheets(package)
        inventory = []
        for name, part in sheets.items():
            root = ET.fromstring(package.read(part))
            inventory.append(
                {
                    "sheet": name,
                    "part": part,
                    "cells": [
                        _display_value(cell)
                        for cell in root.findall(".//x:sheetData/x:row/x:c", NS)
                    ],
                    "merged_ranges": [
                        merge.get("ref")
                        for merge in root.findall("./x:mergeCells/x:mergeCell", NS)
                    ],
                }
            )
    return {
        "file": str(path),
        "sheets": inventory,
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


def _allowed(source: Path, plan: dict[str, Any]) -> list[str]:
    with zipfile.ZipFile(source) as package:
        sheets = _sheets(package)
    allowed = set()
    for raw in plan["edits"]:
        edit = dict(raw)
        if edit["action"] != "set_cell":
            raise ValueError(f"Unsupported XLSX edit action: {edit['action']}")
        try:
            allowed.add(sheets[str(edit["sheet"])])
        except KeyError as exc:
            raise ValueError(f"Unknown worksheet: {edit['sheet']}") from exc
    return sorted(allowed)


def apply(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    with zipfile.ZipFile(source) as package:
        sheets = _sheets(package)
        allowed = _allowed(source, plan)
        roots = {part: ET.fromstring(package.read(part)) for part in allowed}
        before_styles: dict[tuple[str, str], str | None] = {}
        for raw in plan["edits"]:
            edit = dict(raw)
            if edit["action"] != "set_cell":
                raise ValueError(f"Unsupported XLSX edit action: {edit['action']}")
            part = sheets[str(edit["sheet"])]
            reference = str(edit["cell"]).upper()
            cell = _cell(roots[part], reference)
            before_styles[(part, reference)] = cell.get("s")
            _set_cell(cell, edit)
            if cell.get("s") != before_styles[(part, reference)]:
                raise AssertionError(f"Style changed for {edit['sheet']}!{reference}")
        replacements = {
            part: ET.tostring(root, encoding="utf-8", xml_declaration=True)
            for part, root in roots.items()
        }
    patch_package(source, output, replacements)
    report = fidelity_report(source, output, allowed, protected_patterns=PROTECTED)
    report["output"] = str(output)
    return report


def verify(source: Path, output: Path, plan: dict[str, Any]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="evoflux-xlsx-plan-") as directory:
        expected = Path(directory) / f"expected{source.suffix}"
        apply(source, expected, plan)
        return planned_output_report(
            source,
            expected,
            output,
            _allowed(source, plan),
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
