---
name: pdf
description: Read, extract, create, transform, fill, OCR, render, or verify PDF files. Use whenever a PDF is an input, required output, or visual source of truth; do not trigger for Word, spreadsheet, slide, or web deliverables with no PDF work.
---

# Work directly with PDFs

Preserve source files and produce the smallest requested PDF result. Structural
success is not visual proof: render and inspect the required pages before
delivery. Load only the reference or helper required by the selected lane.

EvoFlux's Documents plugin provides read-only preview, not a PDF authoring or
publish API. Confirm each required executable and Python package exists in the
workspace environment. Do not silently install packages or claim OCR,
encryption, redaction, or rendering succeeded when its engine is unavailable.

## Choose one lane

- **Inspect or extract:** read metadata, text, tables, images, annotations,
  page geometry, forms, or accessibility structure without changing the source.
- **Transform:** merge, split, reorder, rotate, crop, watermark, redact,
  encrypt, decrypt, or optimize an existing PDF.
- **Create:** author a new PDF with ReportLab or another available PDF library.
- **Form:** inspect or fill AcroForm fields while preserving field behavior.
- **OCR:** use only when an OCR engine is available; preserve the original
  raster and add a searchable text layer.

Do not mix lanes speculatively. Identify page ranges, ordering, output path,
password handling, and preservation requirements before mutation.

## Resource routing

- Read [forms.md](forms.md) only for form inspection, typed field filling,
  annotation fallback, or form-flattening decisions.
- Read [reference.md](reference.md) only when the basic lane does not cover an
  advanced library/API operation, OCR detail, encryption, or troubleshooting.
- For AcroForms, use [field detection](scripts/check_fillable_fields.py),
  [field inspection](scripts/extract_form_field_info.py), and
  [typed filling](scripts/fill_fillable_fields.py) only as routed by the form
  guide.
- For non-fillable forms, use
  [structure extraction](scripts/extract_form_structure.py),
  [box validation](scripts/check_bounding_boxes.py),
  [validation overlays](scripts/create_validation_image.py), and
  [annotation filling](scripts/fill_pdf_form_with_annotations.py) only as
  routed by the form guide.
- Use [PDF-to-image rendering](scripts/convert_pdf_to_images.py) when visual
  inspection requires page PNGs. Inspect a helper before modifying it; do not
  load every script.

## Execute

1. Inspect page count, geometry, rotation, encryption, text layer, and form
   presence before editing.
2. Choose one available implementation that preserves the required structure.
   Prefer `pypdf` or an available `qpdf` for page operations, `pdfplumber` for
   extraction, ReportLab for new pages, and PDFium for raster verification.
3. Write to a new output file, reopen it with an independent PDF reader, render
   the required pages, and inspect the images. Never overwrite the source.
4. Preserve page order, boxes, bookmarks, metadata, fields, annotations,
   links, and accessibility information unless the request requires a change.
5. Treat passwords and extracted personal data as sensitive; never echo them
   into logs or final prose.

For ReportLab paragraphs, use `<sub>` and `<super>` markup rather than Unicode
subscript or superscript glyphs that bundled fonts may not contain.

## Verification gate

Check structure with an independent reader, then render pages to images. Verify:

- expected page count, order, size, and rotation;
- readable text and searchable OCR where required;
- required tables, form values, links, bookmarks, and metadata;
- no clipped text, missing glyphs, blank pages, broken images, shifted fields,
  accidental overlays, or exposed redacted content;
- encryption or decryption behavior using the intended credentials.

For long unchanged documents, inspect every changed page plus the first and
last unchanged boundaries. Inspect every page when creating, merging, OCRing,
redacting, or globally restyling the document. A visual black box is not a
redaction check: independently confirm underlying text and objects were removed.

## Deliverable

Return the absolute final PDF path first. State the operation, page count,
verification performed, and any retained limitation such as OCR confidence,
unflattened fields, unsupported encryption, or skipped visual/accessibility QA.
