"""Structural and optional render QA for DOCX deliverables."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, cast
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
from app.agent.builtin_skills.docx.scripts.stylekit import (  # noqa: E402
    DocumentProfileName,
    document_profile,
)

PLACEHOLDER_RE = re.compile(
    r"(\{\{[^{}]+\}\}|<TODO>|<PLACEHOLDER>|lorem ipsum|\bxxxx\b)",
    re.IGNORECASE,
)
WORDPROCESSING_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
)
WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORDPROCESSING_NS}}}"


def _render(source: Path, render_dir: Path) -> dict[str, Any]:
    return render_office_images(source, render_dir)


def _metadata_marker(keywords: str, key: str) -> str | None:
    match = re.search(
        rf"(?:^|;\s*){re.escape(key)}:([^;]*)",
        keywords or "",
        re.IGNORECASE,
    )
    return match.group(1).strip() if match is not None else None


def _document_profile(document) -> tuple[DocumentProfileName, bool]:
    value = _metadata_marker(
        document.core_properties.keywords or "",
        "evoflux-profile",
    )
    if value in {
        "standard-business",
        "compact-reference",
        "narrative-proposal",
        "operational-sop",
    }:
        return cast(DocumentProfileName, value), True
    return "standard-business", False


def _required_sections(document) -> list[str]:
    value = _metadata_marker(
        document.core_properties.keywords or "",
        "evoflux-required",
    )
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def _table_geometry_findings(root: ElementTree.Element) -> dict[str, int]:
    missing_geometry = 0
    fixed_rows = 0
    missing_repeating_headers = 0
    tables = root.findall(f".//{W}tbl")
    for table in tables:
        width = table.find(f"./{W}tblPr/{W}tblW")
        indent = table.find(f"./{W}tblPr/{W}tblInd")
        grid = table.findall(f"./{W}tblGrid/{W}gridCol")
        cells = table.findall(f"./{W}tr/{W}tc")
        widths = [cell.find(f"./{W}tcPr/{W}tcW") for cell in cells]
        if (
            width is None
            or width.get(f"{W}type") != "dxa"
            or indent is None
            or not grid
            or any(cell_width is None for cell_width in widths)
            or any(
                cell_width is not None and cell_width.get(f"{W}type") != "dxa"
                for cell_width in widths
            )
        ):
            missing_geometry += 1
        for row in table.findall(f"./{W}tr"):
            height = row.find(f"./{W}trPr/{W}trHeight")
            if height is not None and height.get(f"{W}hRule") == "exact":
                fixed_rows += 1
        first_row = table.find(f"./{W}tr")
        if first_row is not None and first_row.find(f"./{W}trPr/{W}tblHeader") is None:
            missing_repeating_headers += 1
    return {
        "missing_geometry": missing_geometry,
        "fixed_rows": fixed_rows,
        "missing_repeating_headers": missing_repeating_headers,
    }


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
            comments = sum(name == "word/comments.xml" for name in names)
            tracked_change_parts = sum(
                b"<w:ins" in package.read(name) or b"<w:del" in package.read(name)
                for name in names
                if name.startswith("word/") and name.endswith(".xml")
            )
            content_controls = sum(
                package.read(name).count(b"<w:sdt")
                for name in names
                if name.startswith("word/") and name.endswith(".xml")
            )
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return {"errors": [f"Invalid DOCX package: {exc}"], "warnings": []}

    try:
        document = Document(str(source))
    except Exception as exc:
        return {
            "errors": [f"python-docx could not open the package: {exc}"],
            "warnings": [],
        }

    profile_name, explicitly_profiled = _document_profile(document)
    policy = document_profile(profile_name)
    required_sections = _required_sections(document)
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
    all_text = " ".join(node.text or "" for node in root.findall(f".//{W}t"))
    missing_sections = [
        section
        for section in required_sections
        if section.casefold() not in all_text.casefold()
    ]
    if missing_sections:
        errors.append(
            "Content contract is missing required sections: "
            + ", ".join(missing_sections)
        )

    geometry = _table_geometry_findings(root)
    if geometry["fixed_rows"]:
        errors.append(
            f"{geometry['fixed_rows']} table row(s) use exact fixed height and may clip"
        )
    if geometry["missing_geometry"]:
        warnings.append(
            f"{geometry['missing_geometry']} table(s) lack complete fixed DXA geometry"
        )
    if geometry["missing_repeating_headers"]:
        warnings.append(
            f"{geometry['missing_repeating_headers']} table(s) do not repeat the "
            "first row across pages"
        )
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
    words = re.findall(r"\b[\w'-]+\b", all_text)
    word_count = len(words)
    if word_count >= 1200 and headings < 3:
        warnings.append(
            f"Long document has {word_count} words but only {headings} heading(s)"
        )

    if (
        profile_name == "narrative-proposal"
        and len(document.tables) >= 4
        and len(document.tables) > max(headings, 1)
    ):
        warnings.append(
            "Narrative proposal is table-heavy; verify prose was not packaged "
            "into unnecessary grids"
        )

    normal_size = document.styles["Normal"].font.size
    normal_size_pt = normal_size.pt if normal_size is not None else None
    minimum_body = {
        "standard-business": 9.5,
        "compact-reference": 9,
        "narrative-proposal": 10,
        "operational-sop": 9,
    }[profile_name]
    if normal_size_pt is not None and normal_size_pt < minimum_body:
        warnings.append(
            f"Normal style uses {normal_size_pt:.1f}pt; {profile_name} floor is "
            f"{minimum_body:.1f}pt"
        )

    if explicitly_profiled:
        for index, section in enumerate(document.sections, start=1):
            margins = [
                section.top_margin,
                section.bottom_margin,
                section.left_margin,
                section.right_margin,
            ]
            margin_inches = [margin.inches for margin in margins if margin is not None]
            if any(abs(value - policy.margin_inches) > 0.06 for value in margin_inches):
                warnings.append(
                    f"Section {index} margins drift from the {profile_name} "
                    f"profile's {policy.margin_inches:.2f}in token"
                )

    header_footer_text = " ".join(
        paragraph.text
        for section in document.sections
        for part in (section.header, section.footer)
        for paragraph in part.paragraphs
    ).strip()
    if word_count >= 1200 and not header_footer_text:
        warnings.append("Long document has no running header or page-number footer")
    return {
        "errors": errors,
        "warnings": warnings,
        "profile": profile_name,
        "profile_explicit": explicitly_profiled,
        "required_sections": required_sections,
        "words": word_count,
        "paragraphs": len(document.paragraphs),
        "tables": len(document.tables),
        "sections": len(document.sections),
        "headings": headings,
        "table_geometry": geometry,
        "comments": comments,
        "tracked_change_parts": tracked_change_parts,
        "content_controls": content_controls,
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
