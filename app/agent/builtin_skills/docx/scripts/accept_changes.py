"""Accept common Word tracked changes with direct OOXML transforms.

This implementation does not launch Word or LibreOffice. It accepts inserted
content, removes deleted/moved-from content and revision-property snapshots,
then disables future revision tracking in ``word/settings.xml``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

for parent in Path(__file__).resolve().parents:
    if (parent / "app" / "agent" / "builtin_skills").is_dir():
        sys.path.insert(0, str(parent))
        break

from app.agent.builtin_skills.template_fidelity import patch_package  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_PART_RE = re.compile(
    r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$"
)
UNWRAP = {"ins", "moveTo"}
REMOVE = {"del", "moveFrom"}
RANGE_MARKERS = {
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "customXmlInsRangeStart",
    "customXmlInsRangeEnd",
    "customXmlDelRangeStart",
    "customXmlDelRangeEnd",
    "customXmlMoveFromRangeStart",
    "customXmlMoveFromRangeEnd",
    "customXmlMoveToRangeStart",
    "customXmlMoveToRangeEnd",
}
PROPERTY_CHANGES = {
    "rPrChange",
    "pPrChange",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "sectPrChange",
    "numberingChange",
}

ET.register_namespace("w", W)


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _has_revision_marker(element: ET.Element, container: str, marker: str) -> bool:
    properties = element.find(f"{{{W}}}{container}")
    return properties is not None and properties.find(f"{{{W}}}{marker}") is not None


def _accept_in(parent: ET.Element) -> int:
    accepted = 0
    for child in list(parent):
        local = _local_name(child)
        if local == "tr" and _has_revision_marker(child, "trPr", "del"):
            parent.remove(child)
            accepted += 1
            continue
        if local == "tc" and _has_revision_marker(child, "tcPr", "cellDel"):
            parent.remove(child)
            accepted += 1
            continue
        if local in REMOVE:
            parent.remove(child)
            accepted += 1
            continue
        if local in UNWRAP:
            accepted += _accept_in(child) + 1
            position = list(parent).index(child)
            parent.remove(child)
            for offset, grandchild in enumerate(list(child)):
                parent.insert(position + offset, grandchild)
            continue
        if (
            local in RANGE_MARKERS
            or local in PROPERTY_CHANGES
            or local in {"cellIns", "cellDel", "cellMerge", "ins", "del"}
            and _local_name(parent).endswith("Pr")
        ):
            parent.remove(child)
            accepted += 1
            continue
        accepted += _accept_in(child)
    return accepted


def _transform_part(payload: bytes) -> tuple[bytes, int]:
    root = ET.fromstring(payload)
    accepted = _accept_in(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), accepted


def _transform_settings(payload: bytes) -> tuple[bytes, int]:
    root = ET.fromstring(payload)
    accepted = 0
    for name in ("trackRevisions", "doNotTrackMoves", "doNotTrackFormatting"):
        for node in list(root.findall(f"{{{W}}}{name}")):
            root.remove(node)
            accepted += 1
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), accepted


def accept_changes(input_file: str, output_file: str) -> tuple[None, str]:
    """Accept tracked changes while keeping untouched package parts byte-identical."""
    source = Path(input_file)
    output = Path(output_file)
    if not source.is_file():
        return None, f"Error: Input file not found: {input_file}"
    if source.suffix.lower() != ".docx":
        return None, f"Error: Input file is not a DOCX file: {input_file}"
    if source.resolve() == output.resolve():
        return None, "Error: Output must be different from the input template"

    replacements: dict[str, bytes] = {}
    accepted = 0
    temporary: Path | None = None
    try:
        with zipfile.ZipFile(source) as package:
            for part in package.namelist():
                if CONTENT_PART_RE.match(part):
                    payload, count = _transform_part(package.read(part))
                elif part == "word/settings.xml":
                    payload, count = _transform_settings(package.read(part))
                else:
                    continue
                if count:
                    replacements[part] = payload
                    accepted += count
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=".evoflux-accept-",
            suffix=".docx",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        patch_package(source, temporary, replacements)
        Document(str(temporary))
        os.replace(temporary, output)
    except (ET.ParseError, OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return None, f"Error: Could not accept tracked changes: {exc}"

    return (
        None,
        f"Accepted {accepted} tracked change marker(s): {input_file} -> {output_file}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="Input DOCX file with tracked changes")
    parser.add_argument("output_file", help="Output DOCX file with changes accepted")
    args = parser.parse_args()
    _, message = accept_changes(args.input_file, args.output_file)
    print(message)
    return 1 if message.startswith("Error:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
