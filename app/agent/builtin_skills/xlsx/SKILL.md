---
name: xlsx
description: "Create, inspect, analyze, or edit XLSX, XLSM, CSV, and TSV files with formulas, formatting, charts, validation, and visual QA. Trigger whenever a spreadsheet is the primary input or deliverable."
---

# XLSX

Create and edit workbooks with `openpyxl` and the Python standard library. Use
native formulas, tables, charts, validations, named ranges, comments, and
styles. Use only the bundled Python toolchain. The deliverable for this skill
is a spreadsheet file.

## Template-first contract

When a workbook exists, edit a copy instead of recreating it. Inspect it and
declare the smallest allowed cell mutation map:

```bash
python "{SKILL_DIR}/scripts/template.py" inspect template.xlsx \
  --out /tmp/template-manifest.json
python "{SKILL_DIR}/scripts/template.py" apply template.xlsx output.xlsx \
  --plan /tmp/template-edit-plan.json
python "{SKILL_DIR}/scripts/template.py" verify template.xlsx output.xlsx \
  --plan /tmp/template-edit-plan.json
```

Each plan entry uses `action: "set_cell"`, an inspected `sheet` and A1 `cell`,
plus `kind` (`string`, `number`, `boolean`, `formula`, or `blank`) and `value`.
The editor patches worksheet XML directly, retains the target cell style ID,
and preserves all unlisted parts byte-for-byte. Styles, theme, drawings,
charts, tables, pivots, and VBA are protected from unexplained changes.

## Workflow

1. Classify inputs as `workbook to edit`, `fillable template`, `structural
   base`, `visual reference`, or `data source`. Never overwrite a source.
2. For an existing workbook, inventory every sheet before writing: order and
   visibility, used ranges, formulas, merges, tables, names, validations,
   conditional formatting, charts, images, freeze panes, print settings, and
   protected/hidden regions.
3. Define a mutation map (`target -> allowed change -> dependencies -> check`).
   Preserve everything outside that map.
4. For a new workbook, plan each sheet's role and calculation flow. Keep raw
   data, assumptions, calculations, and presentation outputs distinguishable.
5. Build one reproducible Python script. Use `scripts/stylekit.py` for
   typography, widths, table styles, number formats, and calculation settings.
6. Save and QA after each logical sheet or cross-sheet calculation block. Run
   final structural/formula QA, render every sheet when available, inspect, and
   deliver only the requested workbook.

Use the package-preserving editor for value/formula substitutions. Use
`openpyxl` only for requested structural changes such as adding rows, tables,
charts, validations, or conditional formatting; after such a change, verify
that the expanded mutation map explains every affected dependency.

## Formula and data rules

- Derived values must be formulas, not pasted Python results.
- Put assumptions and mapping rules in visible cells/tables; formulas should
  reference them instead of embedding magic numbers.
- Use correct relative/absolute references and quote all cross-sheet names:
  `='Revenue Model'!B7`.
- Keep formulas simple and auditable. Prefer helper rows/columns over one
  opaque expression.
- Guard legitimate division-by-zero cases and avoid volatile formulas unless
  needed.
- Store numbers, percentages, currency, and dates as typed values. Text is for
  labels and identifiers.
- Use invariant number formats such as `#,##0`, `0.0%`, `yyyy-mm-dd`, and
  `"$"#,##0;("$"#,##0);"-"`.
- Set workbook calculation mode to automatic/full recalculation on load.
- External data requires a plain-text source URL per row or a dedicated
  `Sources` sheet.

## Workbook design rules

- Use one professional font and a restrained palette; match an existing
  workbook when present.
- Set readable column widths and row heights explicitly. Wrap long headers and
  cap oversized columns.
- Freeze headings on long tables, enable filters, and use Excel Tables for
  structured data.
- Highlight inputs consistently and distinguish them from formulas.
- Use conditional formatting to communicate thresholds, not as decoration.
- Use native editable charts. Select a chart type that matches the question,
  confirm every series has data, label units, and avoid misleading axes.
- Configure print area, orientation, repeating rows, and fit-to-width for any
  sheet intended to print.
- Do not add empty default sheets, hidden calculation junk, or unexplained
  helper artifacts.

## Required QA

Run after each meaningful build block and once more before delivery:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.xlsx --render-dir /tmp/xlsx-render
```

For a template edit, include the unmodified source:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.xlsx \
  --render-dir /tmp/xlsx-render --compare-to template.xlsx
```

The gate checks package integrity, formula/reference errors, suspicious
formula patterns, empty chart series, placeholder residue, and blank default
sheets. Visual QA uses the bundled Chromium OpenXML renderer rather than
LibreOffice and emits one PNG per sheet. It preserves row/column dimensions,
merges, common number formats, fonts, fills, borders, and alignment; DOM lint
reports clipped cells as warnings. The report uses `confidence: medium`
because Excel's full calculation and chart layout engines are not embedded.
Fix every error. Review warnings deliberately.

For a template edit, both `template.py verify` and `qa.py` must pass. Opening
successfully is not proof that formulas, styles, charts, or macros were
preserved.

Then verify representative input, formula, and output ranges against the
source data; reconcile key totals; inspect every rendered sheet for clipped
headers, `###`, unreadable colors, broken charts, and content outside the
printable area. If rendering tools are unavailable, say so instead of claiming
visual QA passed.
