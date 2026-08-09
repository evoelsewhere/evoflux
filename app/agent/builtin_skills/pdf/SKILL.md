---
name: pdf
description: Read, extract, OCR, create, merge, split, rotate, watermark, secure, fill, render, and verify PDF files. Use whenever a PDF is an input, required output, or visual source of truth; do not use for a Word, spreadsheet, slide, or web deliverable with no PDF work.
---

# Work with PDFs

Preserve source files and produce the smallest requested PDF result. Structural
success is not visual proof: render and inspect every changed or created page
before delivery. Do not load bundled references or scripts when this skill
activates.

Use the deferred `artifact` tool with `format: "pdf"` for new authored PDFs and
fillable AcroForm workflows. Call `catalog` for the live schema. For a form,
call `inspect`, use the exact source hash and field names, then `validate` and
`preview`; pass the completed `inspect_job_id` so its durable manifest is
reused. Publish only the accepted preview job. The published PDF must be the
exact immutable bytes that were rendered and reviewed.

## Choose one lane

- **Inspect/extract:** read metadata, text, tables, images, annotations, page
  geometry, or accessibility structure without changing the source.
- **Transform:** merge, split, reorder, rotate, crop, watermark, redact,
  encrypt, decrypt, or optimize an existing PDF.
- **Create:** author a new PDF through the Artifact Fabric `new` schema.
- **Form:** inspect or fill AcroForm fields through the Artifact Fabric `form`
  schema while preserving field behavior.
- **OCR:** make scanned pages searchable while retaining the visual page.

Do not mix lanes speculatively. Identify page ranges, ordering, output path,
password handling, and preservation requirements before mutation.

## Resource routing

- Read [forms.md](forms.md) only for form inspection, typed field filling,
  annotation fallback, or form-flattening decisions.
- Read [reference.md](reference.md) only when the basic lane does not cover an
  advanced library/API operation, OCR detail, encryption, or troubleshooting.
- Run the smallest matching helper in `scripts/` only after the lane requires
  it. Inspect a script before changing it; do not load every helper.

## Execute

1. Inspect page count, geometry, rotation, encryption, text layer, and form
   presence before editing.
2. Choose one repository-available implementation that preserves the required
   structure. Prefer pypdf/qpdf for page operations, pdfplumber for extraction,
   ReportLab for new authored pages, and Poppler rendering for verification.
3. For create/form work, write the JSON project, call `validate`, then call
   `preview` and inspect every returned image. For other lanes, write to a new
   output file. Never overwrite an uploaded source.
4. Preserve page order, boxes, bookmarks, metadata, fields, annotations,
   links, and accessibility information whenever the requested operation does
   not require changing them.
5. Treat passwords and extracted personal data as sensitive; never echo them
   into logs or final prose.

For ReportLab paragraphs, use `<sub>` and `<super>` markup rather than Unicode
subscript/superscript glyphs that bundled fonts may not contain.

## Verification gate

Check structure with an independent reader, then render pages to images.
Verify:

- expected page count, order, size, and rotation;
- readable text and searchable OCR where required;
- tables, form values, links, bookmarks, and metadata required by the request;
- no clipped text, missing glyphs, blank pages, broken images, shifted fields,
  accidental overlays, or exposed redacted content;
- encryption/decryption behavior using the intended credentials.

For long unchanged documents, inspect every changed page plus the first and
last unchanged boundaries; inspect every page when creating, merging, OCRing,
or globally restyling the document.

## Stop conditions

Stop when the requested structural operation is independently confirmed, the
rendered output is visually correct, the source remains intact, and all
preservation requirements are satisfied.

For Artifact Fabric work, call
`artifact(action="publish", job_id=..., output="...pdf")` only after this gate.

## Deliverable

Return the final PDF path first. State the operation, page count, verification
performed, and any retained limitation such as OCR confidence, unflattened
fields, unsupported encryption, or skipped accessibility validation.
