"""Structural and optional render QA for DOCX deliverables."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docx import Document

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
WORDPROCESSING_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
)


def _render(source: Path, render_dir: Path) -> dict[str, Any]:
    return render_office_images(source, render_dir)


def inspect_docx(source: Path) -> dict[str, Any]:
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
                "word/document.xml",
                "word/styles.xml",
            ):
                if required not in names:
                    errors.append(f"Missing package part: {required}")
            document_xml = package.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return {"errors": [f"Invalid DOCX package: {exc}"], "warnings": []}

    try:
        document = Document(str(source))
    except Exception as exc:
        return {
            "errors": [f"python-docx could not open the package: {exc}"],
            "warnings": [],
        }

    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    if placeholders:
        errors.append(f"Unresolved placeholders: {', '.join(placeholders[:10])}")
    if not text.strip() and not document.tables:
        errors.append("Document has no visible paragraphs or tables")

    fake_lists = [
        paragraph.text[:80]
        for paragraph in document.paragraphs
        if re.match(r"^\s*(?:[•●▪◦]|\d+[.)])\s+", paragraph.text)
        and not str(getattr(paragraph.style, "name", "") or "")
        .lower()
        .startswith(("list", "number"))
    ]
    if fake_lists:
        warnings.append(
            f"{len(fake_lists)} paragraph(s) may use text instead of real numbering"
        )

    root = ElementTree.fromstring(document_xml)
    missing_alt = 0
    for drawing in root.findall(f".//{{{WORDPROCESSING_DRAWING_NS}}}docPr"):
        if not (drawing.get("descr") or "").strip():
            missing_alt += 1
    if missing_alt:
        warnings.append(f"{missing_alt} image(s) have no alt description")

    headings = sum(
        1
        for paragraph in document.paragraphs
        if paragraph.style and paragraph.style.name.lower().startswith("heading")
    )
    return {
        "errors": errors,
        "warnings": warnings,
        "paragraphs": len(document.paragraphs),
        "tables": len(document.tables),
        "sections": len(document.sections),
        "headings": headings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--compare-to", type=Path)
    args = parser.parse_args()

    report = inspect_docx(args.file)
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
