# Workbook design

Use for new workbooks and visual or structural edits. A supplied workbook or
template is the style authority unless the user explicitly asks for a redesign.

## Inspect before editing

Render and review every relevant sheet. Inspect values, formulas, fills, fonts,
borders, alignment, merged cells, number formats, conditional formatting,
validations, tables, charts, filters, freeze panes, dimensions, and hidden
structure. For a visual fix, make the smallest plausible local change. Do not
apply sheet-wide autofit, wrapping, or restyling unless requested.

When extending a range, extend dependent formulas, table ranges, conditional
formatting, validation, and chart sources only where necessary. Leave unrelated
pre-existing issues unchanged unless they break the requested work.

## Build a readable model

- Separate raw data, assumptions, calculations, checks, and presentation
  outputs when the workbook's scale warrants it.
- Make input cells, formulas, summaries, exceptions, and notes visually
  distinct with a restrained, consistent system.
- Store dates, numbers, currency, and percentages as typed values with semantic
  number formats; use text only for identifiers and labels.
- Align and format by data type. Keep important numeric fields out of `General`.
- Preserve filters, tables, totals, and freeze panes that aid navigation.
- Use validation for editable categories and conditional formatting for rules
  that must react to future edits.
- Avoid merged cells in calculation areas and avoid formatting unused rows or
  columns. Prefer whitespace and light structural borders to a border on every
  filled cell.

Size columns and rows for normal zoom. Widen before deep wrapping, then increase
row height only enough to reveal the content. Cap excessive dimensions after
autofit. A numeric column that displays `#####`, a clipped label, or a blank
default sheet is a defect.

## Screenshot or image references

Preserve semantic types even when a screenshot uses locale-specific symbols.
Infer formulas only from exact repeated relationships such as totals, ratios,
differences, or constant multiples; keep inputs as values and derived ranges as
formulas. Match clear visual evidence, but do not infer intentional font weight,
spacing, or color from zoom, antialiasing, or compression artifacts.
