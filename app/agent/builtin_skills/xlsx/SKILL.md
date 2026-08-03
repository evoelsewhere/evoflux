---
name: xlsx
description: Create, edit, inspect, render, and verify Excel XLSX workbooks. Triggers on XLSX, Excel, spreadsheet, workbook, worksheet, formula, table, chart, tracker, or dashboard.
---

# Editable XLSX authoring

Use the deferred `xlsx_artifact` tool for every XLSX write. Do not author
workbooks with `openpyxl`, `xlsxwriter`, pandas, HTML tables, screenshots, or
manually assembled OpenXML. Supporting analysis may use Python or JavaScript,
but the final workbook must be imported/created and exported by
`@oai/artifact-tool`.

## Choose the path

- New workbook: create a project with `mode: "new"`. Ask for clarification
  only when the workbook's purpose, inputs, or required outputs are genuinely
  ambiguous; otherwise use the professional baseline below.
- Uploaded XLSX explicitly used as a template: inspect and render it first,
  then use `mode: "template"`, its exact SHA-256, and targeted operations.
- Uploaded XLSX used only as data: inspect it, but create a new workbook rather
  than implying that its format is the template.

Never overwrite the uploaded workbook.

## Required workflow

```text
XLSX workflow
- [ ] 1. Identify inputs, derived outputs, units, and edit expectations
- [ ] 2. Inspect and render every sheet when a workbook was uploaded
- [ ] 3. Write and validate the JSON project
- [ ] 4. Keep assumptions/input cells separate from formula cells
- [ ] 5. Render every sheet and visually inspect the returned images
- [ ] 6. Resolve formula errors, clipped content, and broken charts
- [ ] 7. Compose one final XLSX and return its artifact card
```

Call `xlsx_artifact(action="catalog")` for the exact schema. For a template,
call `inspect` and review every returned sheet preview plus the manifest before
writing the project. `write_range` without `format` deliberately preserves
existing formatting. Add a format only when the user requested a style change
or a new range needs to extend the template's conventions.

For a new workbook, create all referenced worksheets before formulas. Prefer
block writes. Dates use the `dates` matrix with ISO-8601 strings; numbers,
percentages, and currency remain typed values with invariant number formats.
Derived cells must contain formulas, not hard-coded results. Quote every
cross-sheet formula reference, for example `='Inputs'!B4`.

## Professional baseline for new workbooks

- Use a title/summary area, clear section hierarchy, restrained fills, and
  explicit borders instead of default gridlines.
- Distinguish input cells, formulas, summaries, and notes consistently.
- Freeze headers for long tables; use validation for editable categorical
  fields; use conditional formatting where the visual state must react to edits.
- Apply semantic number formats, then size columns with `autofit_columns`
  instead of guessing `column_width`. Avoid formatting unused rows or columns.
- Use native tables and charts only when they improve analysis. Charts must be
  backed by editable worksheet cells and placed outside the data range.
- Avoid merged cells in calculation areas.

## Verification gate

`render` and `compose` scan for `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`,
`#N/A`, `#NUM!`, and `#NULL!`, and render every worksheet. Do not compose until
the previews are readable at normal zoom and all error-severity issues are
resolved. A successfully written file is not sufficient verification.

Both actions also measure every used column against the width its content
needs. A column holding numbers that is too narrow is an error, because Excel
renders `#####` there; a text-only column that is too narrow is a warning. Fix
either by adding an `autofit_columns` operation over the affected range.
