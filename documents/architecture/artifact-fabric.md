# Artifact Fabric

Status: active and sole document-authoring architecture.

Artifact Fabric gives DOCX, XLSX, PPTX, and PDF one durable lifecycle while
keeping a format-specific schema and engine for each format. The control plane owns
jobs, immutable candidate revisions, QA evidence, review, and exact-byte
publication. Rendering is in-process and does not depend on applications
installed on the host.

The publication invariant is:

> `publish` materializes the exact content-addressed bytes that passed QA during
> `preview`; it never runs the authoring engine again.

## Impact

| Area | Result | Control |
| --- | --- | --- |
| Agent tools | One deferred `artifact` surface for every built-in format | One lifecycle and permission boundary |
| Storage | Candidate bytes live in a SHA-256 content-addressed store | Atomic copy plus pre/post-copy hash checks |
| DOCX | Word-native creation and package-preserving template edits | Package integrity, part hashes, semantic page previews |
| XLSX | Typed OpenXML import/create/export | Formula scan and every-sheet previews |
| PPTX | HTML/Tailwind hybrid and inherited-template lanes | WebView fidelity, selective editability, every-slide previews |
| PDF | Native creation and hash-pinned AcroForm filling | Structural parsing and every-page PDFium previews |
| Desktop | Python sidecar plus wheel dependencies | No separate document-runtime archive or host executables |

## Architecture

```mermaid
flowchart LR
    A["Agent or UI"] --> T["artifact tool / Artifact API"]
    T --> C["Artifact lifecycle service"]
    C --> J["Job + revision ledger"]
    C --> R["Format engine registry"]
    R --> D["DOCX: python-docx + direct OOXML"]
    R --> X["XLSX: openpyxl OpenXML engine"]
    R --> P["PPTX: HTML/Tailwind WebView + thin OOXML packer"]
    R --> F["PDF: ReportLab + pypdf + PDFium"]
    D --> Q["Normalized QA evidence"]
    X --> Q
    P --> Q
    F --> Q
    Q --> S["SHA-256 content-addressed store"]
    S --> V["Immutable candidate revision"]
    V --> B["Exact-byte atomic publish"]
```

Format engines exchange typed Python models and return normalized issues. They
do not select published paths or mutate lifecycle records.

## Portable rendering core

Most document preview is part of the Python sidecar:

- DOCX is rendered from paragraphs, tables, styles, and pagination signals in
  its OOXML model.
- XLSX is rendered from workbook cells, dimensions, fills, fonts, and charts.
- New PPTX decks are rendered by the already-running desktop WebView from inert,
  local HTML/Tailwind. The sidecar receives immutable PNG evidence and computed
  bounds for explicitly editable overlays. Existing/template PPTX preview stays
  in the sidecar.
- PDF pages are rasterized by `pypdfium2`.
No document path launches an office suite or bundles a browser, Node runtime,
or host PDF command. The PPTX new-deck lane reuses the Tauri WebView already
running the desktop UI; without a connected renderer it fails explicitly and
does not fall back to a lower-fidelity engine. Release CI does not download a
separate document runtime or require URL/SHA secrets.

## Lifecycle

The public actions are `catalog`, `inspect`, `validate`, `preview`, `publish`,
`status`, and `cancel`. Template workflows pass a completed `inspect_job_id`
into validation or preview so the service can reuse its durable manifest.

```mermaid
flowchart LR
    Q["queued"] --> R["running"]
    R --> C["completed: inspect/validate passed"]
    R --> V["review_ready: preview passed"]
    R --> F["failed"]
    R --> X["cancelled"]
    V --> P["published: exact revision materialized"]
    V --> X
```

A QA failure never creates an accepted revision. An engine that reports
success without candidate bytes fails its contract.

## Persistence and storage

`artifact_jobs` stores lifecycle state and request/result metadata.
`artifact_revisions` stores immutable content hash, size, storage key,
normalized QA, previews, manifest, provenance, engine version, and protocol
version. `artifact_reviews` records approval and publication evidence.

```text
artifact-fabric/
  blobs/sha256/<prefix>/<full-sha256>
  revisions/<revision-id>/previews/preview-001.png
  work/<job-id>/...
```

CAS writes and publish operations use destination-local temporary files,
verify hash and size, and rename atomically.

## Native format engines

### DOCX

New-document and template-safe lanes use real Word paragraphs, styles, tables,
images, headers, footers, fields, and direct package edits. Template lineage
and unrelated package parts are preserved.

### XLSX

The OpenXML engine creates or imports an editable workbook and applies typed
range, formula, style, validation, table, chart, merge, freeze, clear, and
autofit operations. Formula tokens are scanned before publication and Excel is
asked to recalculate formulas when the workbook opens.

### PPTX

Schema version 4 uses one new-deck representation. Each slide is an inert
1280×720 HTML fragment plus optional project-local CSS and declared assets.
The WebView supplies a curated build-time Tailwind utility runtime, renders the
complete visual preview, hides supported editable objects, and renders the
flattened shell. It also returns computed bounds and simple typography for
explicit `data-pptx-editable` text and raster images. A thin `python-pptx`
packer writes the shell and native overlays, then opens the package again to
verify slide count and OpenXML structure.

Scripts, event handlers, forms, frames, canvas, media, network URLs, CSS
imports, and paths outside the project are rejected. Unsupported editable CSS
is kept visually correct in the shell with a warning. Blank, low-information,
wrong-size, broken-asset, and overflow previews fail QA. Embedded PPTX
thumbnails are never preview evidence.

The template lane clones slide XML and relationships directly, retaining
masters, layouts, themes, transitions, timing, and untouched objects. It edits
only stable shape IDs emitted during inspection.

### PDF

The `new` lane generates native PDF flow blocks. The `form` lane fills a
hash-pinned inspected AcroForm. Both are parsed structurally and rendered page
by page with PDFium.

## Security boundary

The `/api/artifacts` HTTP surface exposes catalog, job status, immutable
revision download, and immutable preview download. It does not accept arbitrary
server-side publication destinations. The agent tool requires publication to
remain inside the primary workspace with the correct extension.

## Extending formats

A new document family implements the engine contract, registers its media type,
extension, catalog, inspect/validate/build behavior, and returns normalized QA
evidence. It automatically inherits durable jobs, immutable revisions, CAS
integrity, status/cancel, API reads, and exact-byte publication.
