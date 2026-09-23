# Visualization

Create, revise, or QA quantitative charts for reports, dashboards, notebooks, slides, files, or inline answers. A chart is evidence for a takeaway, not decoration.

## Workflow

1. State the analytical question and the takeaway the chart must support.
2. Verify grain, measures, dimensions, units, missing values, filters, time window, sample size, and source of the plotted data.
3. Choose the chart from the relationship:

   | Relationship | Chart |
   |---|---|
   | Change over ordered time | Line or area |
   | Category comparison | Bar (horizontal for long labels) |
   | Distribution | Histogram, box plot, density |
   | Relationship between numeric measures | Scatter |
   | Composition | Stacked bar or area; pie only for a few meaningful parts |
   | Funnel progression | Funnel or ordered bars with stage conversion |
   | Contribution to change | Waterfall or bridge |
   | Exact lookup values | Table, optionally with inline bars or sparklines |

4. Define encodings, sorting, aggregation, scales, labels, units, colors, annotations, and uncertainty treatment explicitly.
5. Render with the destination's native chart system when one is chosen (BI tool, spreadsheet, slide tool). Otherwise:
   - files and reports: reproducible Python/Matplotlib saved as PNG or SVG, or hand-written inline SVG;
   - notebooks: notebook-native plotting;
   - self-contained HTML: inline SVG or canvas, or a static image with a fallback data table;
   - inline interactive visual in the conversation: the `show_widget` tool when it is available and the user wants an in-chat visual.
6. Inspect the rendered output (open the image with `read`, or view HTML with `browser_use` when available) and fix what you see.

Do not install React, Recharts, Vite, or other frontend toolchains for a chart. Avoid remote scripts unless the user accepts the dependency.

## Visual quality

- Answer-oriented title ("Paid Search activation fell from 57% to 40% in May"); subtitle only for a distinct second point.
- Label axes and units; every visible series has a legend entry or direct label (prefer direct labels).
- Consistent scales across compared charts; no truncated value axis on bars unless justified and labeled.
- Restrained color; reserve semantic colors for meaning (positive, warning, negative); do not rely on color alone.
- Selective, evidence-backed annotations for events that explain the pattern.
- For dense data, aggregate, facet, filter, or switch to a table instead of shrinking text.
- Accessible contrast, alt text, and a data table where the destination supports them.
- Provenance in a source note under the chart, not in the title.

## QA

- Recompute plotted values from the reviewed rows.
- The chart answers the stated question and does not imply unsupported causality.
- Check ordering, scales, labels, clipping, overlap, empty states, and narrow-screen behavior where relevant.
- The exported file opens and contains the expected marks and text.
- Keep the code or notebook that reproduces the chart when the user needs an auditable artifact.
