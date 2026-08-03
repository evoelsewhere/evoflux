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

XLSX verification also measures every used column against the width its content
needs, because a numeric cell narrower than its formatted text renders as `#####`
in Excel — a broken cell that no formula scan detects. The measurement applies
autofit on a clone imported from the export blob, so the published workbook keeps
the widths the project declared. A narrow numeric column is an error and a narrow
text column a warning; the fix is an `autofit_columns` operation, which is
preferred over guessing `column_width`.

Both workers write export bytes directly instead of calling artifact-tool's
`save()`. That helper also writes every sidecar next to the target as
`<output>.inspect.ndjson` and announces it on stdout, which would leave a stray
dump of workbook contents beside each published file and add noise to the
protocol's stdout channel.

`app/services/office/rendering.py` owns the LibreOffice-to-PNG conversion shared
by DOCX verification and PPTX round-trip verification. Callers pass a code prefix
so failures stay attributable to the pipeline that asked, and `renderer_available()`
lets a caller treat rasterisation as optional evidence rather than a hard
dependency.

`app/services/office/runtime.py` owns the plumbing every Office pipeline needs:
source hashing, external executable discovery, and the Node worker protocol
(`node <worker>.mjs <action> <action>-request.json`, last JSON object on stdout
wins, non-zero exit surfaces stderr). Sharing it is deliberately limited to
that plumbing — the pipelines still keep their own project schemas, operations,
and verification rules, so there is no generic Office compiler. Executable
lookup order is the environment override (`EVOFLUX_NODE_BIN`,
`EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT`, `EVOFLUX_SOFFICE_BIN`,
`EVOFLUX_PDFTOPPM_BIN`), then `PATH` and the workspace's own `node_modules`,
then the EvoFlux checkout, and only last the Codex primary-runtime cache, which
is an external layout EvoFlux does not own.

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
