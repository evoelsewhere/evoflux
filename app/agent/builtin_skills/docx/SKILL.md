---
name: docx
description: Create, edit, inspect, render, and verify Word DOCX documents. Triggers on DOCX, Word, document, memo, report, proposal, brief, policy, SOP, or uploaded Word template.
---

# Word-native DOCX authoring

Use the deferred `docx_document` tool for DOCX deliverables. It has two
separate paths: design-preset creation for new documents and package-preserving
OOXML patches for uploaded templates. Never turn a document into screenshots,
HTML pages, flattened PDF content, or a fresh generic document when the user
asked to edit their template.

## Choose the path

- New document: choose exactly one design preset and one first-page header
  pattern based on the communication job. Call `catalog` for the schemas.
- Uploaded DOCX explicitly used as the template: call `inspect`, review every
  page preview and the full manifest, then use `mode: "template"` with its
  exact SHA-256 and stable locators from the manifest.
- Uploaded DOCX used only as content: extract the content but create a new
  document; do not claim to preserve its design.

The source DOCX is always immutable.

## Required workflow

```text
DOCX workflow
- [ ] 1. Identify the document job, audience, and content structure
- [ ] 2. Choose one preset/header pattern, or inspect the uploaded template
- [ ] 3. Write and validate the JSON project
- [ ] 4. Render every page and visually inspect the returned images
- [ ] 5. Fix clipping, broken tables, pagination, or font substitution
- [ ] 6. Compose only after structural and visual QA pass
- [ ] 7. Return one editable DOCX artifact card
```

## New documents

Available presets are `standard_business_brief`, `compact_reference_guide`,
and `narrative_proposal`. Available first-page patterns are `memo_masthead`,
`proposal_centerpiece`, `editorial_cover`, `customer_pack`,
`workshop_agenda`, and `customer_story`.

Use real Word styles and paragraphs for headings and prose, real list styles
for bullets/numbers, fixed-width native tables for tabular content, native
images with alt text, real hyperlinks, section headers/footers, and a PAGE
field. Table column widths must total 9360 DXA. Do not use fake bullets,
manual page numbers, repeated punctuation as rules, or tables to package normal
prose. Do not silently shrink text to force content into a page.

## Uploaded templates

`inspect` renders every page and inventories body, headers, footers, notes,
comments, content-control tags, paragraph IDs/indexes, styles, table geometry,
fields, and the SHA-256 of every package part.

Template projects may use only:

- `replace_text` for a substring inside a located paragraph; prefer this when
  surrounding rich text must remain intact.
- `replace_paragraph` when the whole located paragraph is the slot.
- `replace_content_control` for a verified plain-text tagged control.
- `replace_table_cell` for a native table cell by exact part/table/row/column.

Use IDs and indexes from the manifest; never invent locators. Avoid replacing
rich-text, repeating-section, image, or table content controls. An unrelated
package part changing is a hard failure. Template mode preserves styles,
numbering, theme, images, relationships, headers/footers, comments, controls,
drawings, and embedded objects outside the declared editable parts.

## Verification gate

Both paths render through LibreOffice and Poppler after composition. Structural
QA checks package integrity and required Word parts; template QA additionally
checks the SHA-256 of every unrelated part. Do not deliver if any error-severity
issue remains. Placeholder warnings require deliberate review rather than
automatic deletion.
