---
name: xlsx
description: Create, edit, inspect, or verify editable Microsoft Excel .xlsx workbooks. Use when an XLSX or Excel workbook is an input or required output, including formula, table, chart, tracker, or dashboard work; do not trigger for analysis or visualization with no XLSX input or output.
---

# Author an editable XLSX workbook

Work directly with XLSX files using Python and `openpyxl`. Keep authoring logic
in a small task-local script so the result is reproducible. Never overwrite an
uploaded workbook; write a new output file.

EvoFlux no longer provides a workbook-authoring tool, durable validation job,
or publish step. Confirm `openpyxl` is available in the workspace environment
before authoring; do not silently add it to the user's project.

## Choose the path

- **New workbook:** create native cells, formulas, tables, charts, validation,
  conditional formatting, and named styles only when they serve the analysis.
  Read [workbook design](references/workbook-design.md).
- **Uploaded XLSX used as a template:** inspect sheets, dimensions, formulas,
  tables, charts, merged cells, validations, styles, row heights, and column
  widths before making targeted edits. Read
  [workbook design](references/workbook-design.md).
- **Uploaded XLSX used only as data:** read its values, then create a separate
  workbook without implying that its formatting was preserved.
- **Read or analyze only:** inspect labeled values, formulas, and precedents;
  answer without modifying or exporting the workbook unless asked.

Read [formulas and QA](references/formulas-and-qa.md) for formula-driven work.
Read [workbook charts](references/charts.md) before creating or editing charts.

## Required workflow for create or edit

1. Identify inputs, derived outputs, units, and edit expectations.
2. Inspect every source sheet when a workbook was uploaded.
3. Write and run a deterministic task-local Python authoring script.
4. Reopen the exact saved XLSX with `openpyxl` and verify sheet names, formulas,
   ranges, tables, charts, validation rules, and number formats.
5. Render every worksheet with an available renderer and inspect the images at
   normal zoom. Treat EvoFlux's semantic renderer as an approximation of Excel.
6. Resolve formula errors, clipped content, unreadable columns, and broken
   charts. Rerun authoring and verification on the exact final bytes.

For templates, assigning values without assigning styles preserves existing
formatting. Copy or create styles only when requested or when a new range must
extend the template's conventions. Minimize edits around drawings, slicers,
pivots, external links, and macros that `openpyxl` cannot safely round-trip.

Create referenced worksheets before formulas. Prefer block writes. Use real
date/datetime values, typed numbers, percentages, and currency with explicit
number formats. Derived cells must contain formulas rather than hard-coded
results. Quote cross-sheet references, for example `='Inputs'!B4`.

`openpyxl` writes formulas but does not calculate them. A `data_only=True`
reopen reads cached values, which may be absent or stale. Do not claim formula
results are verified unless a calculation engine has recalculated the exact
final workbook. If no engine is available, verify formula syntax, references,
and expected formulas, then disclose that computed values were not recalculated.

## Professional baseline

- Use a clear title/summary area, restrained fills, and explicit borders rather
  than default gridlines.
- Distinguish inputs, formulas, summaries, and notes consistently.
- Freeze long-table headers; use validation and conditional formatting where
  edit behavior requires them.
- Apply semantic number formats and practical column widths. Avoid formatting
  unused rows or columns and avoid merged cells in calculation areas.
- Use native tables and data-backed charts only when they improve analysis.

## Verification gate

Scan formulas and displayed values for `#REF!`, `#DIV/0!`, `#VALUE!`,
`#NAME?`, `#N/A`, `#NUM!`, and `#NULL!`. A too-narrow numeric column is an
error because Excel renders `#####`. Stop only after the exact final XLSX
reopens and every rendered worksheet is readable. If rendering or recalculation
is unavailable, report the missing QA step instead of calling it fully verified.
