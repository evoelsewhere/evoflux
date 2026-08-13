# Formulas and workbook QA

Use for models, trackers, dashboards, repairs, and any workbook with derived
values.

## Formula design

- Put assumptions and raw data in dedicated cells or clearly delineated input
  ranges. Preserve a supplied workbook's organization.
- Keep mapping, scoring, threshold, and quality-control rules visible in cells
  or tables and reference them from formulas.
- Derived values must be formulas, with consistent patterns across comparable
  rows or periods.
- Use absolute and relative references deliberately. Quote every cross-sheet
  reference, for example `='Inputs'!B4`.
- Do not embed magic numbers in calculation formulas. Reference a labeled
  assumption such as `=B5*(1+'Inputs'!$B$4)`.
- Prefer helper cells and short auditable formulas to a single opaque formula.
  Add cell comments for important assumptions or non-obvious logic.

## Read-only analysis

Locate a result by its row label, column label, unit, and period. Inspect its
displayed value and formula, then trace precedents to labeled assumptions or raw
inputs instead of stopping at an intermediate total. Explain calculations with
the workbook's units and period conversions. Do not edit or export the workbook
for a question-only request.

## Verification

Reopen the exact output twice when useful: once with formulas and once with
cached values. Check representative ranges and reconcile key totals. Scan for
`#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`, and `#NULL!`; also
check wrong ranges, off-by-one errors, zero and negative cases, broken fill
patterns, and unintended circular references.

Render every worksheet at normal zoom and repair clipped headers, unreadable
formats, blank/broken charts, and content outside the working area. Keep the
verification compact and targeted.

`openpyxl` does not calculate formulas. Cached values may be absent or stale.
Without an available calculation engine, verify syntax, references, and formula
patterns only, and disclose that computed values were not recalculated.
