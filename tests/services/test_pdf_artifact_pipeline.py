from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.agent.builtin_plugins.documents.engines.pdf import (
    compose_pdf_project,
    inspect_pdf,
    load_pdf_project,
    validate_pdf_project,
)
from app.agent.builtin_plugins.documents.rendering.runtime import file_sha256


def test_new_pdf_is_structurally_checked_and_every_page_is_rendered(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "report.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "new",
                "title": "Artifact Fabric PDF",
                "page_size": "a4",
                "blocks": [
                    {"type": "heading", "text": "Verified output", "level": 1},
                    {
                        "type": "paragraph",
                        "text": "These are the exact bytes that passed QA.",
                    },
                    {"type": "page_break"},
                    {
                        "type": "table",
                        "values": [["Format", "Driver"], ["PDF", "native"]],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "candidate.pdf"

    result = compose_pdf_project(
        project_path,
        None,
        output,
        work_dir=tmp_path / "work",
    )

    assert result.passed is True
    assert result.output == output
    assert len(PdfReader(output).pages) == 2
    assert len(result.previews) == 2
    assert all(path.is_file() for path in result.previews)
    assert result.manifest_path is not None and result.manifest_path.is_file()


def test_pdf_validation_rejects_source_for_new_mode(tmp_path: Path) -> None:
    project_path = tmp_path / "report.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "new",
                "title": "Report",
                "blocks": [{"type": "paragraph", "text": "Body"}],
            }
        ),
        encoding="utf-8",
    )
    project = load_pdf_project(project_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"not-used")

    try:
        validate_pdf_project(project, source)
    except ValueError as exc:
        assert "must not declare source_pdf" in str(exc)
    else:
        raise AssertionError("new PDF mode accepted a source template")


def test_inspect_pdf_emits_manifest_and_previews(tmp_path: Path) -> None:
    project_path = tmp_path / "one-page.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "new",
                "title": "Inspect me",
                "blocks": [{"type": "paragraph", "text": "Inspectable text"}],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "source.pdf"
    built = compose_pdf_project(project_path, None, output, work_dir=tmp_path / "build")
    assert built.passed

    inspected = inspect_pdf(output, tmp_path / "inspect")

    assert inspected.passed
    assert inspected.metadata["page_count"] == 1
    assert len(inspected.previews) == 1


def test_pdf_form_lane_is_hash_pinned_and_fills_acroform_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "form.pdf"
    form = canvas.Canvas(str(source), pagesize=letter)
    form.drawString(72, 720, "Customer")
    form.acroForm.textfield(name="customer", x=72, y=680, width=240, height=24)
    form.save()
    inspected = inspect_pdf(source, tmp_path / "inspect-form")
    assert inspected.passed
    assert inspected.manifest_path is not None
    manifest = json.loads(inspected.manifest_path.read_text(encoding="utf-8"))
    assert manifest["form_fields"] == ["customer"]

    project_path = tmp_path / "fill.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "form",
                "title": "Filled form",
                "source_sha256": file_sha256(source),
                "template_confirmed": True,
                "fields": {"customer": "EvoFlux"},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "filled.pdf"

    result = compose_pdf_project(
        project_path,
        source,
        output,
        work_dir=tmp_path / "fill-work",
    )

    assert result.passed
    fields = PdfReader(output).get_fields()
    assert fields is not None
    assert fields["customer"]["/V"] == "EvoFlux"
