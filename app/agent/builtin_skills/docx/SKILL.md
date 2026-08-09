---
name: docx
description: Create, edit, inspect, render, and verify Word DOCX documents. Triggers on DOCX, Word, document, memo, report, proposal, brief, policy, SOP, or uploaded Word template.
---

# Word-native DOCX authoring

Use the deferred `artifact` tool with `format: "docx"`. It has two paths:
design-preset creation for new documents and package-preserving OOXML patches
for uploaded templates. Never turn a document into screenshots, HTML pages,
flattened PDF content, or a fresh generic document when the user asked to edit
their template. Never overwrite the source.

Do not load example projects when this skill activates. Call
`artifact(action="catalog", format="docx")` first and use the live schema as
authoritative.

## Choose the path

- **New document:** choose exactly one design preset and one first-page header
  pattern based on the communication job.
- **Uploaded DOCX used as the template:** call `inspect`; review every page
  preview and the full manifest, then use `mode: "template"` with its exact
  SHA-256 and stable locators.
- **Uploaded DOCX used only as content:** extract its content and create a new
  document without claiming to preserve its design.

The source DOCX is always immutable.

## Required lifecycle

1. Identify the document job, audience, and content structure.
2. Choose a preset/header pattern, or inspect the uploaded template.
3. Write the format-native JSON project and call `validate`.
4. Call `preview` and visually inspect every returned page image.
5. Fix clipping, broken tables, pagination, font substitution, placeholders,
   and every error-severity issue; create a new preview revision.
6. Call `artifact(action="publish", job_id=..., output="...docx")` only for the
   revision that passed review.
7. Return one editable DOCX artifact card.

`publish` reuses the verified immutable bytes and never rebuilds the document.

## New documents

Available presets are `standard_business_brief`, `compact_reference_guide`,
and `narrative_proposal`. Available first-page patterns are `memo_masthead`,
`proposal_centerpiece`, `editorial_cover`, `customer_pack`,
`workshop_agenda`, and `customer_story`.

Use real Word styles and paragraphs for headings and prose, real list styles
for bullets/numbers, fixed-width native tables, native images with alt text,
real hyperlinks, section headers/footers, and a PAGE field. Table column widths
must total 9360 DXA. Do not use fake bullets, manual page numbers, repeated
punctuation as rules, or tables to package normal prose. Do not silently shrink
text to force content into a page.

## Uploaded templates

`inspect` renders every page and inventories body, headers, footers, notes,
comments, content-control tags, paragraph IDs/indexes, styles, table geometry,
fields, and the SHA-256 of every package part.

Template projects may use only:

- `replace_text` for a substring inside a located paragraph;
- `replace_paragraph` when the whole located paragraph is the slot;
- `replace_content_control` for a verified plain-text tagged control;
- `replace_table_cell` for a native table cell by exact part/table/row/column.

Use locators from the manifest; never invent them. Avoid replacing rich-text,
repeating-section, image, or table content controls. An unrelated package part
changing is a hard failure. Preserve styles, numbering, theme, images,
relationships, headers/footers, comments, controls, drawings, and embedded
objects outside the declared editable parts.

## Verification gate

`preview` renders through LibreOffice and Poppler. Structural QA checks package
integrity and required Word parts; template QA additionally checks every
unrelated part hash. Do not publish if any error remains. Placeholder warnings
require deliberate review rather than automatic deletion.
