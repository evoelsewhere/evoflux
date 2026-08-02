# Editable XLSX and DOCX pipelines

EvoFlux treats spreadsheets and Word documents as different authoring systems.
Both expose the same agent workflow—catalog, inspect, validate, render, and
compose—but they do not share a generic Office compiler.

## XLSX: artifact-tool workbook model

The deferred `xlsx_artifact` tool is the only XLSX write path. Its service
starts `xlsx_artifact_worker.mjs`, which imports `@oai/artifact-tool` from the
configured runtime. New workbooks start from `Workbook.create()`; template
workbooks start from `SpreadsheetFile.importXlsx()`.

The JSON project applies bounded operations to named worksheets:

- typed value, date, and formula matrices;
- targeted range formats, merges, clears, and frozen panes;
- data validation and conditional formatting;
- native tables and charts backed by worksheet ranges.

Value/formula writes do not carry a format unless the project explicitly asks
for one, so template formatting is not accidentally reset. Before export, the
worker scans for Excel error values and renders every worksheet. A compose with
any error-severity issue does not publish an XLSX.

Template lineage is an immutable SHA-256 stored in the project. The uploaded
workbook is read-only and the composed workbook is always a separate path.

## DOCX: Word-native creation and package patches

The deferred `docx_document` tool has two deliberately separate modes.

New documents use `python-docx` with an explicit preset and first-page pattern.
The builder writes real Word styles, paragraphs, list definitions, fixed-width
tables, hyperlinks, images with alt text, headers, footers, and PAGE fields.
The supported presets encode their page, typography, spacing, list, and table
tokens rather than relying on viewer defaults.

Uploaded templates are never rebuilt through the new-document builder. Inspect
renders every page and inventories all editable content parts, paragraph
indexes/IDs, styles, content controls, tables, fields, and package-part hashes.
A template project may then target only an inspected paragraph, plain-text
content control, or table cell. The service patches those text nodes in a copy
of the ZIP package.

After a template edit, every unrelated package part must have the same SHA-256
as the source. This protects styles, numbering, themes, relationships, images,
drawings, comments, controls, and embedded objects outside the edit scope. Page
count must also remain stable unless the project explicitly allows a pagination
change.

## Verification and runtime dependencies

XLSX authoring verification uses artifact-tool's renderer. DOCX authoring
verification uses a unique LibreOffice profile to produce PDF and Poppler to
rasterize one PNG per page. Missing required authoring runtimes are blockers;
neither pipeline silently falls back to HTML screenshots or a lower-fidelity
writer.

Workspace and coding file previews are a separate desktop WebView concern:

- XLSX files are imported client-side by SpreadJS in a protected, read-only
  workbook. Set `VITE_SPREADJS_LICENSE_KEY` at web build time for licensed
  desktop distributions. The engine and Excel I/O module are lazy-loaded only
  after a workbook is selected.
- PDF files are displayed by EmbedPDF/PDFium WebAssembly with virtualized
  scrolling, search, selection, zoom, and print. The viewer disables mutation
  tools and all remote font loading; it is also lazy-loaded.
- Both readers fetch the original permission-scoped file URL. They do not use
  Playwright, Chromium headless, or the Python OpenXML-to-HTML XLSX renderer.

Generated previews and request manifests live under `.evoflux/` and are ignored
by Git. Final files are published only to workspace paths and are returned as
downloadable, previewable attachment cards.
