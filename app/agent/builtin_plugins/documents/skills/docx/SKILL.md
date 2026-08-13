---
name: docx
description: Create, edit, inspect, render, and verify Word DOCX documents. Triggers on DOCX, Word, document, memo, report, proposal, brief, policy, SOP, or uploaded Word template.
---

# Word-native DOCX authoring

Work directly with DOCX files using Python and `python-docx`. Keep authoring or
template-edit logic in a task-local script, never turn a document into
screenshots or flattened content, and never overwrite the source.

## Choose the path

- **New document:** choose exactly one design preset and one first-page header
  pattern based on the communication job.
- **Uploaded DOCX used as the template:** inspect its styles, sections, package
  parts, relationships, headers, footers, tables, and content controls before
  applying targeted edits.
- **Uploaded DOCX used only as content:** extract its content and create a new
  document without claiming to preserve its design.

The source DOCX is always immutable.

## Required lifecycle

1. Identify the document job, audience, and content structure.
2. Choose a preset/header pattern, or inspect the uploaded template.
3. Write and run a task-local Python authoring script.
4. Reopen the exact saved DOCX and render every page for visual inspection.
5. Fix clipping, broken tables, pagination, font substitution, and placeholders.
6. Return the verified editable DOCX workspace path.

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

Inspect body, headers, footers, notes, comments, content-control tags,
paragraphs, styles, table geometry, fields, relationships, and package parts.

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

Use an independent OOXML reopen plus the bundled semantic renderer when
available. Check package integrity, required Word parts, and every unrelated
template part. Placeholder warnings require deliberate review rather than
automatic deletion.
