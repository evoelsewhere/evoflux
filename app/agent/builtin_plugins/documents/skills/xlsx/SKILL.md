---
name: xlsx
description: Create, edit, inspect, render, and verify Excel XLSX workbooks. Triggers on XLSX, Excel, spreadsheet, workbook, worksheet, formula, table, chart, tracker, or dashboard.
---

# Editable XLSX authoring

Use the deferred `artifact` tool with `format: "xlsx"` for every XLSX write.
Artifact Fabric's typed OpenXML engine creates or imports and exports the
workbook. Do not bypass it with ad-hoc scripts, HTML tables, or screenshots;
supporting analysis may still use Python.

Do not load examples when this skill activates. Call
`artifact(action="catalog", format="xlsx")` first and treat the live schema as
authoritative.

## Choose the path

- **New workbook:** use `mode: "new"`; clarify only genuinely ambiguous
  purpose, inputs, or outputs.
- **Uploaded XLSX used as the template:** call `inspect`, review every sheet
  preview and the manifest, then use `mode: "template"`, the exact source
  SHA-256, and targeted operations.
- **Uploaded XLSX used only as data:** inspect it, then create a new workbook
  without implying that its formatting is the template.

Never overwrite the uploaded workbook.

## Required lifecycle

1. Identify inputs, derived outputs, units, and edit expectations.
2. Inspect and render every sheet when a workbook was uploaded.
3. Write the format-native JSON project and call `validate`.
4. Keep assumptions/input cells separate from formula cells.
5. Call `preview` and visually inspect every returned sheet image.
6. Resolve formula errors, clipped content, and broken charts; create a new
   preview revision.
7. Call `artifact(action="publish", job_id=..., output="...xlsx")` only for the
   accepted revision, then return its artifact card.

`publish` reuses the verified immutable bytes and never rebuilds the workbook.

For a template, `write_range` without `format` preserves existing formatting.
Add a format only when the user requested a style change or a new range must
extend the template's conventions.

Create all referenced worksheets before formulas. Prefer block writes. Dates
use the `dates` matrix with ISO-8601 strings; numbers, percentages, and currency
remain typed values with invariant number formats. Derived cells must contain
formulas, not hard-coded results. Quote cross-sheet references, for example
`='Inputs'!B4`.

## Professional baseline

- Use a title/summary area, clear hierarchy, restrained fills, and explicit
  borders instead of default gridlines.
- Distinguish inputs, formulas, summaries, and notes consistently.
- Freeze long-table headers; use validation and conditional formatting where
  edit behavior requires them.
- Apply semantic number formats, then use `autofit_columns`. Avoid formatting
  unused rows or columns.
- Use native tables and data-backed charts only when they improve analysis.
- Avoid merged cells in calculation areas.

## Verification gate

`preview` scans for `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`,
and `#NULL!`, and renders every worksheet. Do not publish until previews are
readable at normal zoom and every error is resolved.

QA also measures used columns against content width. A too-narrow numeric
column is an error because Excel renders `#####`; a too-narrow text-only column
is a warning. Fix either with `autofit_columns` over the affected range.
