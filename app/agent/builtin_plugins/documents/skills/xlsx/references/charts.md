# Workbook charts

Use a native workbook chart only when it makes a comparison, trend,
distribution, ranking, progress measure, or relationship easier to interpret.
For exact values across a few items, prefer a compact table; for one metric,
prefer a KPI plus a small trend when possible.

## Choose one takeaway

- category comparison or ranking: sorted bar or column;
- trend over time: line, with grouped Year/Quarter/Month/Week labels when raw
  dates crowd the axis;
- part-to-whole: sorted bar or a pie/doughnut only for a few slices where rough
  share is the point;
- distribution: histogram or box-and-whisker when spread and outliers matter.

Use the chart that makes the intended takeaway easiest to see, not the most
decorative type.

## Use auditable data

Chart ranges must be traceable to source cells and formula-backed where
practical. Use helper ranges only to reshape, group, or shorten labels, and make
those helpers reference source cells rather than copied values. Verify headers,
categories, series names, orientation, point counts, date ranges, and blanks
before creating the chart. Do not invent zeroes for unknown values.

## Format and place

Place the chart near the KPI or table it explains without covering data,
controls, notes, or other charts. Keep comparable charts consistent in units,
scale, dates, and color meaning. Make titles state the subject or takeaway;
show units in the title, axis, or labels; and set axis number formats explicitly.

Use data labels only when exact values matter. Avoid dense line-chart labels,
heavy borders, gradients, excessive gridlines, and arbitrary multi-color
single-series charts. Size the chart for its rendered density, not merely the
available grid area.

## Verify

Inspect the chart object, source ranges, formulas, and rendered output. Check
for blank or duplicate charts, stale or disconnected ranges, categories treated
as a series, missing points, clipped labels, crowded ticks, unreadable units,
unsupported types, and overlaps. If the selected chart type does not render
reliably, use the closest clear native alternative and preserve the takeaway.
