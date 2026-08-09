"""First-class PDF creation, AcroForm filling, inspection, and visual QA."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal

import pdfplumber
import pypdfium2 as pdfium
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LEGAL, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.office.runtime import file_sha256

_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{[^{}]+\}\}|\b(?:TODO|TBD)\b|\blorem ipsum\b)", re.IGNORECASE
)
_PAGE_SIZES = {"a4": A4, "letter": LETTER, "legal": LEGAL}
_ALIGNMENTS = {
    "left": TA_LEFT,
    "center": TA_CENTER,
    "right": TA_RIGHT,
    "justify": TA_JUSTIFY,
}


class PdfHeading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["heading"] = "heading"
    text: str = Field(min_length=1, max_length=5000)
    level: Literal[1, 2, 3] = 1
    color: str = "#111827"
    alignment: Literal["left", "center", "right"] = "left"
    space_after: float = Field(default=8, ge=0, le=100)


class PdfParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=50000)
    font_size: float = Field(default=10.5, ge=6, le=72)
    leading: float | None = Field(default=None, ge=6, le=120)
    color: str = "#1f2937"
    alignment: Literal["left", "center", "right", "justify"] = "left"
    space_after: float = Field(default=7, ge=0, le=100)


class PdfSpacer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["spacer"] = "spacer"
    height: float = Field(default=8, ge=0, le=300)


class PdfPageBreak(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["page_break"] = "page_break"


class PdfImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"] = "image"
    asset_path: str = Field(min_length=1, max_length=2000)
    width_mm: float = Field(gt=1, le=500)
    height_mm: float = Field(gt=1, le=500)
    alt: str = Field(min_length=1, max_length=1000)


class PdfTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["table"] = "table"
    values: list[list[str | int | float | None]] = Field(min_length=1, max_length=500)
    header_row: bool = True
    repeat_header: bool = True
    font_size: float = Field(default=9, ge=5, le=36)
    header_fill: str = "#e2e8f0"
    grid_color: str = "#cbd5e1"
    column_widths_mm: list[float] | None = None

    @field_validator("values")
    @classmethod
    def rectangular(cls, rows: list[list[Any]]) -> list[list[Any]]:
        width = len(rows[0])
        if width == 0 or width > 80 or any(len(row) != width for row in rows):
            raise ValueError("PDF table must be a non-empty rectangular matrix")
        return rows

    @field_validator("column_widths_mm")
    @classmethod
    def positive_widths(cls, widths: list[float] | None) -> list[float] | None:
        if widths is not None and any(width <= 0 for width in widths):
            raise ValueError("PDF table column widths must be positive")
        return widths


PdfBlock = Annotated[
    PdfHeading | PdfParagraph | PdfSpacer | PdfPageBreak | PdfImage | PdfTable,
    Field(discriminator="type"),
]


class NewPdfProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    mode: Literal["new"] = "new"
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=1000)
    page_size: Literal["a4", "letter", "legal"] = "a4"
    margin_top_mm: float = Field(default=18, ge=5, le=80)
    margin_right_mm: float = Field(default=18, ge=5, le=80)
    margin_bottom_mm: float = Field(default=18, ge=5, le=80)
    margin_left_mm: float = Field(default=18, ge=5, le=80)
    blocks: list[PdfBlock] = Field(min_length=1, max_length=5000)


class FormPdfProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    mode: Literal["form"] = "form"
    title: str = Field(min_length=1, max_length=500)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_confirmed: Literal[True]
    fields: dict[str, str] = Field(min_length=1, max_length=1000)


PdfProject = NewPdfProject | FormPdfProject
_PROJECT_ADAPTER = TypeAdapter(Annotated[PdfProject, Field(discriminator="mode")])


@dataclass
class PdfPipelineResult:
    action: str
    work_dir: Path
    source_pdf: Path | None = None
    output: Path | None = None
    manifest_path: Path | None = None
    previews: list[Path] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.get("severity") == "error" for issue in self.issues)


def load_pdf_project(path: Path) -> PdfProject:
    return _PROJECT_ADAPTER.validate_json(path.read_text(encoding="utf-8"))


def pdf_catalog() -> dict[str, Any]:
    return {
        "workflow": "first-class-pdf",
        "lanes": ["new", "form"],
        "invariants": [
            "PDF is a first-class format, not only an Office conversion side effect.",
            "Inspect source structure and AcroForm names before template filling.",
            "Render every page and scan unresolved placeholders before publishing.",
            "Publish the same immutable bytes that passed structural and visual QA.",
        ],
        "new_project_schema": NewPdfProject.model_json_schema(),
        "form_project_schema": FormPdfProject.model_json_schema(),
    }


def validate_pdf_project(project: PdfProject, source: Path | None) -> dict[str, Any]:
    if isinstance(project, FormPdfProject):
        if source is None:
            raise ValueError("form mode requires source_pdf")
        if file_sha256(source) != project.source_sha256:
            raise ValueError("source PDF changed after inspection; inspect it again")
        reader = PdfReader(source)
        available = set((reader.get_fields() or {}).keys())
        missing = sorted(set(project.fields) - available)
        if missing:
            raise ValueError(f"unknown PDF form fields: {', '.join(missing)}")
        return {
            "valid": True,
            "mode": "form",
            "field_count": len(project.fields),
            "available_field_count": len(available),
        }
    if source is not None:
        raise ValueError("new PDF project must not declare source_pdf")
    return {
        "valid": True,
        "mode": "new",
        "block_count": len(project.blocks),
        "page_size": project.page_size,
    }


def inspect_pdf(source: Path, work_dir: Path) -> PdfPipelineResult:
    manifest, issues = _inspect_structure(source)
    previews, render_issues = render_pdf_pages(source, work_dir / "previews")
    issues.extend(render_issues)
    manifest_path = work_dir / "pdf-manifest.json"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return PdfPipelineResult(
        action="inspect",
        work_dir=work_dir,
        source_pdf=source,
        manifest_path=manifest_path,
        previews=previews,
        issues=issues,
        metadata={"page_count": manifest.get("page_count", 0)},
    )


def compose_pdf_project(
    project_path: Path,
    source: Path | None,
    output: Path,
    *,
    work_dir: Path,
) -> PdfPipelineResult:
    project = load_pdf_project(project_path)
    validate_pdf_project(project, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(project, NewPdfProject):
        _build_new_pdf(project, project_path, output)
    else:
        assert source is not None
        _fill_pdf_form(project, source, output)

    manifest, issues = _inspect_structure(output)
    previews, render_issues = render_pdf_pages(output, work_dir / "previews")
    issues.extend(render_issues)
    manifest_path = work_dir / "pdf-manifest.json"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if any(issue.get("severity") == "error" for issue in issues):
        output.unlink(missing_ok=True)
        published = None
    else:
        published = output
    return PdfPipelineResult(
        action="compose",
        work_dir=work_dir,
        source_pdf=source,
        output=published,
        manifest_path=manifest_path,
        previews=previews,
        issues=issues,
        metadata={
            "mode": project.mode,
            "page_count": manifest.get("page_count", 0),
            "form_field_count": len(manifest.get("form_fields", [])),
        },
    )


def render_pdf_pages(
    source: Path, render_dir: Path
) -> tuple[list[Path], list[dict[str, Any]]]:
    render_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    issues: list[dict[str, Any]] = []
    try:
        document = pdfium.PdfDocument(source)
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=2.0)
            destination = render_dir / f"page-{index + 1:03d}.png"
            bitmap.to_pil().save(destination)
            outputs.append(destination)
            page.close()
        document.close()
    except Exception as exc:  # noqa: BLE001 - return normalized QA evidence
        issues.append(
            {"severity": "error", "code": "pdf-render-failed", "message": str(exc)}
        )
    if not outputs and not issues:
        issues.append(
            {
                "severity": "error",
                "code": "pdf-has-no-pages",
                "message": "PDF renderer returned no pages",
            }
        )
    return outputs, issues


def _inspect_structure(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        reader = PdfReader(source)
        if reader.is_encrypted:
            issues.append(
                {
                    "severity": "error",
                    "code": "encrypted-pdf",
                    "message": "Encrypted PDFs are not accepted by the authoring pipeline",
                }
            )
        fields = reader.get_fields() or {}
        pages: list[dict[str, Any]] = []
        full_text: list[str] = []
        with pdfplumber.open(source) as document:
            for index, page in enumerate(document.pages, start=1):
                text = page.extract_text() or ""
                full_text.append(text)
                pages.append(
                    {
                        "page": index,
                        "width": float(page.width),
                        "height": float(page.height),
                        "text_characters": len(text),
                    }
                )
        for match in sorted(set(_PLACEHOLDER_RE.findall("\n".join(full_text)))):
            issues.append(
                {
                    "severity": "error",
                    "code": "unresolved-placeholder",
                    "message": str(match),
                }
            )
        if not pages:
            issues.append(
                {
                    "severity": "error",
                    "code": "empty-pdf",
                    "message": "PDF has no pages",
                }
            )
        metadata = {
            key.lstrip("/"): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        }
        return (
            {
                "schema_version": 1,
                "source_path": str(source),
                "source_sha256": file_sha256(source),
                "page_count": len(pages),
                "pages": pages,
                "metadata": metadata,
                "form_fields": sorted(fields),
            },
            issues,
        )
    except Exception as exc:  # noqa: BLE001 - invalid PDFs become QA failures
        return (
            {"schema_version": 1, "source_path": str(source), "page_count": 0},
            [{"severity": "error", "code": "invalid-pdf", "message": str(exc)}],
        )


def _build_new_pdf(project: NewPdfProject, project_path: Path, output: Path) -> None:
    page_size = _PAGE_SIZES[project.page_size]
    document = SimpleDocTemplate(
        str(output),
        pagesize=page_size,
        topMargin=project.margin_top_mm * mm,
        rightMargin=project.margin_right_mm * mm,
        bottomMargin=project.margin_bottom_mm * mm,
        leftMargin=project.margin_left_mm * mm,
        title=project.title,
        author=project.author,
        subject=project.subject,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []
    for index, block in enumerate(project.blocks):
        if isinstance(block, PdfHeading):
            sizes = {1: 24, 2: 17, 3: 13}
            story.append(
                Paragraph(
                    block.text,
                    ParagraphStyle(
                        f"heading-{index}",
                        parent=styles[f"Heading{block.level}"],
                        fontName="Helvetica-Bold",
                        fontSize=sizes[block.level],
                        leading=sizes[block.level] * 1.18,
                        textColor=colors.HexColor(block.color),
                        alignment=_ALIGNMENTS[block.alignment],
                        spaceAfter=block.space_after,
                    ),
                )
            )
        elif isinstance(block, PdfParagraph):
            story.append(
                Paragraph(
                    block.text,
                    ParagraphStyle(
                        f"paragraph-{index}",
                        parent=styles["BodyText"],
                        fontName="Helvetica",
                        fontSize=block.font_size,
                        leading=block.leading or block.font_size * 1.35,
                        textColor=colors.HexColor(block.color),
                        alignment=_ALIGNMENTS[block.alignment],
                        spaceAfter=block.space_after,
                    ),
                )
            )
        elif isinstance(block, PdfSpacer):
            story.append(Spacer(1, block.height))
        elif isinstance(block, PdfPageBreak):
            story.append(PageBreak())
        elif isinstance(block, PdfImage):
            asset = Path(block.asset_path)
            if not asset.is_absolute():
                asset = project_path.parent / asset
            if not asset.is_file():
                raise FileNotFoundError(f"PDF image does not exist: {asset}")
            story.append(
                Image(
                    str(asset),
                    width=block.width_mm * mm,
                    height=block.height_mm * mm,
                )
            )
        elif isinstance(block, PdfTable):
            widths = (
                [width * mm for width in block.column_widths_mm]
                if block.column_widths_mm
                else None
            )
            if widths and len(widths) != len(block.values[0]):
                raise ValueError("PDF table column_widths_mm must match column count")
            table = Table(
                block.values,
                colWidths=widths,
                repeatRows=1 if block.header_row and block.repeat_header else 0,
            )
            commands: list[tuple[Any, ...]] = [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), block.font_size),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334155")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(block.grid_color)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            if block.header_row:
                commands.extend(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor(block.header_fill),
                        ),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ]
                )
            table.setStyle(TableStyle(commands))
            story.append(table)
    document.build(story)


def _fill_pdf_form(project: FormPdfProject, source: Path, output: Path) -> None:
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(
            page,
            project.fields,
            auto_regenerate=False,
        )
    with output.open("wb") as stream:
        writer.write(stream)


__all__ = [
    "FormPdfProject",
    "NewPdfProject",
    "PdfPipelineResult",
    "compose_pdf_project",
    "inspect_pdf",
    "load_pdf_project",
    "pdf_catalog",
    "render_pdf_pages",
    "validate_pdf_project",
]
