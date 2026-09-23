# Report Deliverables

Build a durable report with an answer-first narrative, evidence-backed findings, charts or tables, caveats, recommendations, and source context. Run the relevant analysis first; this file owns the reader-facing structure, evidence placement, QA, delivery format, and PDF conversion.

## Contents

- Choose one format
- Build the report
- Recommended structure
- QA and handoff
- Converting to PDF

## Choose one format

Honor an explicit format. Otherwise:

1. **Markdown** — the most portable default.
2. **Self-contained HTML** — when a polished browser-readable report helps. Semantic HTML/CSS, inline SVG or embedded images, optional small vanilla JavaScript; readable with JavaScript disabled; no React, Vite, Recharts, or remote scripts.
3. **PDF, DOCX, XLSX, or slides** — only when requested or required by the destination. Build PDF from the HTML version (see below). For DOCX read the `docx-official` skill, for slides the `pptx-official` skill, for workbooks the `xlsx-official` skill, and keep the same evidence across formats.

If the user asks only for an inline brief or says no file, deliver the same answer-first structure concisely in chat.

## Build the report

1. Confirm audience, decision, scope, comparison window, and format from context; ask only when a missing choice would materially change the result.
2. Keep metric definitions, grain, time range, filters, units, exclusions, and source freshness explicit.
3. Lead with the answer: the most important conclusion and its decision implication before methodology.
4. Build a narrative, not a dump of charts or query results. Include only visuals and tables that support a finding; create charts per `references/visualization.md`.
5. Distinguish verified facts, likely explanations, assumptions, limitations, and open questions.
6. Tie recommendations to evidence, expected impact, owner or next action, and a measurable follow-up.
7. Add a sources section naming real systems, tables or views, files, documents, queries, and access dates when known. Never invent provenance.

## Recommended structure

```markdown
# [Short reader-facing title]

## Executive summary
[Answer, magnitude, and decision implication]

## Key findings
[Evidence-backed findings with charts or tables]

## Recommendations
[Prioritized actions and expected outcomes]

## Risks and limitations
[Data gaps, assumptions, uncertainty, interpretation limits]

## Sources and methodology
[Definitions, scope, source details, reproducibility notes]
```

Adapt headings to the audience but keep the answer-first order. For KPI readouts use the formats in `references/kpi-reporting.md`.

## QA and handoff

- Recalculate headline values and comparisons from the reviewed evidence; every chart matches its source rows.
- Check titles, labels, units, denominators, date ranges, and sorting.
- For HTML, PDF, DOCX, XLSX, or slides, inspect the actual artifact — `browser_use` for HTML, `document_preview` for PDF/DOCX/XLSX/PPTX — and fix clipping, blank charts, overflow, low contrast, and unreadable tables.
- Remove credentials, temporary local paths, placeholder provenance, and implementation noise (renderer names, validation status, debug labels) from the visible report.
- Return the primary artifact path plus only the relevant supporting notebook, SQL, data, or chart files.

A requested report is complete only when the file exists and was inspected, or a concrete blocker is reported.

## Converting to PDF

Use this path when the user wants a PDF of a report, dashboard export, or chart: static HTML -> headless browser print -> PDF verification.

1. **Resolve a static HTML source.** Use a local HTML file (or a local URL serving it). If the only source is a sign-in page, redirect, app shell without report content, or a hosted viewer, create a static HTML version from the validated report content first; do not print an app shell or rebuild the report from memory. Keep visible metadata reader-facing: no renderer IDs, package paths, validation status, or temp paths in the body. Translate data-state caveats into reader language ("synthetic demo data", "partial source coverage").
2. **Find a Chromium-based browser** with `shell`:
   - Linux: `command -v google-chrome chromium chromium-browser microsoft-edge`
   - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` or `/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge`
   - Windows: `where chrome msedge`, or the standard installs `C:/Program Files/Google/Chrome/Application/chrome.exe` and `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe` (Edge ships with Windows)
3. **Print to PDF:**

   ```bash
   "<browser>" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
     --no-pdf-header-footer --print-to-pdf=/absolute/path/report.pdf /absolute/path/report.html
   ```

   Use an `@media print` stylesheet to hide interactive controls and avoid breaking charts or table rows across pages.
4. **Fallback when no browser works:** use another installed renderer that prints the same HTML faithfully, for example `uv run --with weasyprint python -c "import weasyprint; weasyprint.HTML('report.html').write_pdf('report.pdf')"` (needs system Pango libraries), or an already-installed Playwright Chromium. Do not hand-author a new PDF layout or redraw charts as a normal fallback; direct PDF construction (see the `pdf-official` skill) is a last resort the user must accept. If nothing can render the HTML, report the blocker and the source file.
5. **Verify the PDF.** Check it exists, is non-empty, and has the expected page count and size (`document_preview`, or `pdfinfo`/`pdftotext`/`pdftoppm` when installed, or `uv run --with pypdf python -c "..."`). Confirm text is selectable. Inspect every page of short reports and representative pages of long ones for blank or clipped charts, missing tables or source details, leftover controls (share, edit, refresh, menus, drag handles), and leaked internal metadata.
6. **Repair and hand off.** Fix the HTML, print CSS, or invocation and regenerate until checks pass. Return the PDF path and, when useful, the HTML source path. Mention checks only when one failed, was unavailable, or creates a caveat.
