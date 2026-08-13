---
name: xlsx
description: Create, edit, inspect, render, and verify Excel XLSX workbooks. Triggers on XLSX, Excel, spreadsheet, workbook, worksheet, formula, table, chart, tracker, or dashboard.
---

# Editable XLSX authoring

Work directly with XLSX files from the workspace using Python and `openpyxl`.
Keep all authoring logic in a small task-local script so the result is
reproducible. Never overwrite an uploaded workbook; write a new output file.

## Choose the path

- **New workbook:** create a workbook with native cells, formulas, tables,
  charts, validation, conditional formatting, and named styles.
- **Uploaded XLSX used as the template:** open it with `load_workbook`, inspect
  sheet names, dimensions, formulas, tables, charts, merged cells, validations,
  styles, row heights, and column widths before making targeted edits.
- **Uploaded XLSX used only as data:** read its values, then create a separate
  workbook without implying that its formatting was preserved.

## Required workflow

1. Identify inputs, derived outputs, units, and edit expectations.
2. Inspect every source sheet when a workbook was uploaded.
3. Write and run a task-local Python authoring script.
4. Reopen the saved XLSX with `openpyxl` and verify sheet names, formulas,
   ranges, tables, charts, validation rules, and number formats.
5. Render every worksheet to PNG with the bundled document renderer when it is
   available, and inspect the images at normal zoom.
6. Resolve formula errors, clipped content, unreadable columns, and broken
   charts before returning the final workspace path.

For templates, assigning values without assigning styles preserves existing
formatting. Copy or create styles only when the user requested a style change
or a new range must extend the template's conventions.

Create all referenced worksheets before formulas. Prefer block writes. Use
real date/datetime values, typed numbers, percentages, and currency with
explicit number formats. Derived cells must contain formulas rather than
hard-coded results. Quote cross-sheet references, for example
`='Inputs'!B4`.

## Professional baseline

- Use a title/summary area, clear hierarchy, restrained fills, and explicit
  borders instead of default gridlines.
- Distinguish inputs, formulas, summaries, and notes consistently.
- Freeze long-table headers; use validation and conditional formatting where
  edit behavior requires them.
- Apply semantic number formats and calculate practical column widths. Avoid
  formatting unused rows or columns.
- Use native tables and data-backed charts only when they improve analysis.
- Avoid merged cells in calculation areas.

## Verification gate

Scan formulas and displayed values for `#REF!`, `#DIV/0!`, `#VALUE!`,
`#NAME?`, `#N/A`, `#NUM!`, and `#NULL!`. A too-narrow numeric column is an
error because Excel renders `#####`; widen it before delivery. Stop only after
the exact final XLSX reopens successfully and every rendered worksheet is
readable.
