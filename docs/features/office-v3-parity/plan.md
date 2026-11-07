# Office documents: v3 behaviour in v4 (native preview, live build, area edits, versions, widgets) — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [Crates](../../architecture/README.md), [Desktop app](../../architecture/README.md) |
| ADRs | [0008 Optional LibreOffice runtime](../../architecture/decisions/0008-optional-libreoffice-runtime.md) (partly superseded), [0009 Native Office preview renderer](../../architecture/decisions/0009-native-office-preview-renderer.md) |

## 1. Context and constraints

The v4 architecture is a Rust engine, a JSONL protocol, a Tauri shell and a
React UI. The source of truth for "v3 behaviour" is tag `v3.1.1`:
`app/services/document_preview/`, `app/services/document_versions.py`,
`app/agent/tools/builtin/{document_preview.py,visualize/}`,
`app/agent/builtin_skills/{docx,pptx,xlsx}-official`,
`app/agent/builtin_skills/office-annotation-edit`,
`web/src/components/{workspace-document-preview,document-annotator,document-version-controls,WidgetRenderer}.tsx`,
`web/src/lib/document-annotations.ts`, and
`documents/features/workbench-files-and-side-chat.md` (lines 90–293).

What v4 has today:

- `crates/evo-office` (runtime install, `convert_to_pdf`), `crates/evo-engine/src/office.rs`
  (`office_status/install/convert`, preview cache, `EVO_SOFFICE`, bundled skills),
  `apps/desktop/src/features/files/document-viewer.tsx` (pdf.js pages, re-render on mtime).
  Exact pages today are LibreOffice → PDF → pdf.js.
- Engine file watching (`crates/evo-engine/src/fs_watch.rs`), shell env with
  the Office shell-env provider (`office::shell_env`), skills loaded through the
  `skill` tool (`crates/evo-engine/src/skill_tool.rs`), desktop-executed tools
  (`configure_external_tools`, `features/browser/agent-tools.ts`, e.g. `show_file`).
- The `read` tool returns images, which the v4 skill text relies on.

Rules: the engine owns agent logic ([ADD](../../architecture/README.md)); protocol
changes update `evo-protocol`, the engine, `apps/desktop/src/engine/` and stores
together; models.dev and naming rules; trust boundaries (document content is
untrusted data).

v3 infrastructure that has no v4 equivalent and is mapped in section 3: the Python
renderer, FastAPI `/api/team/...` routes, SSE `files/watch`, `stream_store.running_session_ids()`,
the Skills hook's synthetic `read`, `EVOFLUX_*` state dirs.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Rendering, inspection, the live check, versions and the agent tools are in `evo-office` and the engine; the desktop shows, selects and sends ([ADR 0009](../../architecture/decisions/0009-native-office-preview-renderer.md)). |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-office` holds the renderer and the version store with no engine or desktop types; the engine wires them to RPCs and tools. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | New RPCs and the `office_file_changed` event land in `evo-protocol`, the engine and the desktop; older clients ignore the event, older engines fall back to pdf.js (3.3). |
| Models come from models.dev; no hardcoded model facts | n/a | No model data involved. |
| Real engine in the app; settings and credentials reload live | ok | `files.autoOpenGenerated` applies live (3.8). |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Document content stays untrusted; preflight before rendering; preview HTML is script-free; widgets run sandboxed with no Tauri IPC (3.7). |
| Desktop UI structure and `DESIGN.md` | ok | Viewer code in `features/files/office/`, the batch in a store, the widget frame in `components/`; `features/chat` uses the store, not the viewer's internals. |

## 3. Design

### 3.1 Overview

```text
                      ┌──────────── evo-office ─────────────┐
 Office file ──► preflight ──► native renderer (pptx/xlsx/docx) ──► HTML (v3 contract) ──► cache
                      │                 ▲ live plan (custom.xml)     │
                      └─ LibreOffice ───┴─► PDF (exact pages) ───────┘
engine: office.rs ── RPC office_preview{path, mode} ──► desktop viewer (iframe HTML | pdf.js)
        document_preview tool ──► inspection(HTML) ──► report text
        doc_versions.rs ◄── fs_watch (settled saves) ──► RPC document_versions_*
        show_widget / visualize_read_me tools ──► transcript ──► desktop WidgetFrame ──► sendPrompt
desktop: viewer + annotator + version controls + composer chip + auto-open on fs events
```

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-office/src/preview/{mod,security,pptx,xlsx,docx,chart_svg,xlsx_formula,inspection,live}.rs` | Port of v3 `document_preview/service.py`, `security.py` (package preflight), `inspection.py`, `live_deck.py`, `xlsx_features.py`, `xlsx_formula.py`; same constants and markup. | FR-1, FR-2, FR-3, FR-7, NFR-1, NFR-2 |
| crate | `crates/evo-office/src/versions.rs` | Port of `document_versions.py` (manifest + content-addressed blobs). | FR-12 |
| engine | `crates/evo-engine/src/office.rs` | RPCs `office_preview`, `document_versions_get/act`; live check against the chat's own running turn. | FR-4, FR-7, FR-12 |
| engine | `crates/evo-engine/src/document_preview_tool.rs` | The agent tool. | FR-3 |
| engine | `crates/evo-engine/src/visualize_tool.rs` | `visualize_read_me`, `show_widget` (guideline text from v3 `visualize/guidelines.py`). | FR-13 |
| engine | `crates/evo-engine/src/fs_watch.rs` | Emits Office file changes to the client and to versions. | FR-7, FR-9, FR-12 |
| skills | `crates/evo-engine/bundled-skills/{docx,pptx,xlsx}-official`, `office-annotation-edit/` | v3 text and scripts, renamed per 3.3: `deck_live.py`, `workbook_live.py`, `office-annotation-edit` with `targets.py` / `cells.py`, `pptx-official/preview.md` (Phase 2.5 widget previews). | FR-6, FR-11, FR-13, FR-14 |
| protocol | `crates/evo-protocol` | New RPCs and the `office_file_changed` event. | FR-4, FR-7, FR-9, FR-12 |
| desktop UI | `apps/desktop/src/features/files/office/` | Port of `workspace-document-preview.tsx`, `document-annotator.tsx`, `document-version-controls.tsx`, thumbnail and search helpers, runtime banner. | FR-4, FR-5, FR-8, FR-9, FR-10, FR-12 |
| desktop UI | `apps/desktop/src/stores/annotations-store.ts`, `features/chat/*` | Batch store, composer chip, user-message chip, block format. | FR-10, FR-11 |
| desktop UI | `apps/desktop/src/components/widget-frame.tsx` | Port of `WidgetRenderer.tsx`. | FR-13, NFR-2, NFR-3 |

### 3.3 Interfaces

Preview markup contract (v3): `data-preview-item`, `data-qa-label`,
`data-shape-id`, `data-source-layer`, `data-cell`, `data-formula`, %
geometry, `data-deck-live`, `data-slide-status`.

RPC (engine):

```jsonc
// office_preview → the HTML file to show, or the PDF for exact pages
{ "type": "office_preview", "path": "deck.pptx", "mode": "native" | "exact" | "auto" }
→ { "kind": "html", "path": "<cache>/<sha>.html", "renderer": "native" | "native-live" }
| { "kind": "pdf",  "path": "<cache>/<sha>.pdf",  "renderer": "libreoffice-26.8.0" }

{ "type": "document_versions_get", "path": "deck.pptx" }
{ "type": "document_versions_act", "path": "deck.pptx",
  "action": "checkpoint" | "undo" | "redo" | "restore", "versionId": "…", "label": "…" }
→ { "path", "head", "canUndo", "canRedo", "versions": [{ "id", "size", "createdAt", "label", "source" }] }
```

Event: `{ "type": "office_file_changed", "changes": [{ "kind": "added" | "modified" | "deleted", "path": "rel/posix" }] }`
(300 ms debounce, dot-segment paths skipped, as v3).

Agent tools: `document_preview` (v3 schema and description verbatim),
`visualize_read_me {modules}`, `show_widget {title, loading_messages, widget_code, i_have_seen_read_me, width?, height?}`.

Annotation message (v3 block, renamed tag, sent as a skill command; the parser also accepts v3's
`$office-annotation-edit` line and `evoflux-annotations`, and the replayed form `/office-annotation-edit …`):

```
/skill:office-annotation-edit <the person's text>

<evo-annotations>
[{"n":1,"file":"deck.pptx","slide":7,"shapes":[{"id":12,"name":"Chart 3"}],"area":{"x":10,"y":20,"w":50,"h":40},"text":"…","instruction":"…"}]
</evo-annotations>
```

Renames (the only intended differences in skill and plan text):

| v3 | v4 |
| --- | --- |
| `EVOFLUX_SOFFICE` | `EVO_SOFFICE` |
| `EVOFLUX_SESSION` | `EVO_CHAT_ID` (set by `office::shell_env`; `EVO_SESSION_ID` is host plumbing and stays out of shells) |
| `$office-annotation-edit` mention | `/skill:office-annotation-edit` command |
| custom property `evoflux.deck` | `evo.deck` (reader accepts both) |
| `<evoflux-annotations>` | `<evo-annotations>` (parser accepts both) |
| `shell` tool | `bash` / `powershell` |
| "load the SKILL.md with `read`" | the `skill` tool |
| "EvoFlux hosts its own preview…" | "evo hosts its own preview…" |

Older clients ignore the new event; older engines answer the new RPCs with an
unknown-type error and the viewer falls back to today's pdf.js path.

### 3.4 Data and storage

- Preview cache: `<agent>/cache/office/previews/<sha>.html` (beside today's PDF cache).
- Versions: `<agent>/document-versions/<chat>/<sha256(rel)[:32]>/manifest.json` + `blobs/<sha256>`; deleted with the chat.
- Live plan: inside the document (`docProps/custom.xml`) plus the scratch copy in the system temp dir (v3).
- Annotation batch: UI memory only (v3).
- Setting `files.autoOpenGenerated` (bool, default true) in the app settings table.

### 3.5 Behaviour

- **Preview choice** (v3 `_render_source`): live → native-live; XLSX → native grid unless Print layout;
  PPTX/DOCX → exact pages when the runtime is installed and the conversion succeeds, else native with the banner.
- **Live**: `office_preview` checks the plan's session against the requesting chat's
  id (`EVO_CHAT_ID` in its shells) and that chat's turn being busy; renders native-live (separate cache key).
  The desktop re-requests on each `office_file_changed` for the open file and when the
  turn starts or ends (v3 `requestKey`). Conversions/renders coalesce per path.
- **Annotations**: v3 flow unchanged; the checkpoint call goes to `document_versions_act`.
  On exact (pdf.js) pages selection uses pdf.js text-layer spans (v3 "exact pages" mode).
- **Skill activation**: an annotated message starts with `/skill:office-annotation-edit `;
  the harness expands it into the skill's instructions with the rest (text + block) as
  arguments, as for any skill command typed in the composer (v3 inserted a `read` for a
  `$name` mention; v4 has no mention syntax).
- **Widgets**: tool result carries `widget_code`; the desktop renders it; `sendPrompt`
  messages are accepted only from that frame and sent as a normal user message.

### 3.6 Errors and edge cases

As v3: unsupported/legacy/password-protected files get named messages; a failing shape is
skipped; mid-write reads keep the last good render; restore after the file changed fails
with "The file changed since, so that version was replaced."; Windows lock → retry, then
"The file is open elsewhere; close it and retry."; an interrupted live build renders plainly
once the turn ends.

### 3.7 Security and trust

Document content stays untrusted (skills say so; the annotation `text` is orientation only).
Preview HTML is script-free with the v3 CSP and preflight (no macros, ActiveX, embedded
executables; zip-bomb limits). Widgets run model-written script in a sandboxed iframe with
the v3 CSP and a postMessage bridge restricted to `sendPrompt`; they get no Tauri IPC.
Versions store copies of user files under the agent dir only.

### 3.8 Configuration

`files.autoOpenGenerated` (Settings → General, live). No other settings; the runtime install
stays in the Files preview.

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Port the renderer to Rust (**chosen**) | — Engine owns it; works for headless chats and the agent tool; no extra runtime. Cost: the largest piece of work (≈5 000 lines of Python). |
| Run the v3 Python renderer via `uv run` | Exact code reuse, but every preview then needs `uv` and a first-run package download; latency of a Python start per live save; a second language in the engine path. |
| Port the renderer to TypeScript in the webview | No Rust work for rendering, but the agent tool and headless chats would depend on the UI (external tool), and the engine could not version or inspect without it. |
| Keep LibreOffice pages only | No shape ids or cell grid: area edits reduce to areas on PPTX and are impossible on XLSX; live builds cost seconds per save; `document_preview` loses geometry. This is today's gap. |

## 5. As-built notes

- **Renderer** (`evo-office/src/preview/`): DOCX, PPTX and XLSX match v3's HTML byte for byte on the
  fixtures, except where v3 was wrong (the owner asked to fix v3 bugs): PPTX list styles, subtitle
  style, doubled field text, scatter labels, automatic markers, lost placeholders/charts/shapes and
  whole-deck failures on malformed values; XLSX chart sizes from anchors, `<col min max>` ranges,
  theme/indexed colours from the workbook's own theme, sheet bounds not grown by formula reads or
  CF ranges, chart-sheet order and hidden label, Excel default column/row sizes, zero sizes hidden;
  DOCX exact line spacing in pt; inspection closes void elements. PDF has no raster (pdf.js shows
  PDFs); its native HTML only gives `document_preview` the page count.
- **Exact pages** are drawn by the desktop from the engine's PDF with pdf.js into v3's exact-page
  markup (text layer from `getTextContent`), so search, thumbnails and area selection work alike.
- **Skill activation**: v4 has no `$name` mentions; an annotated message is the skill command
  `/skill:office-annotation-edit <text>` + `<evo-annotations>` block, which the harness expands.
- **Live build**: plans are stamped with `EVO_CHAT_ID` (from `office::shell_env`); the scripts
  keep other custom document properties (v3 dropped them). Versions skip a live file only for the
  chat's own engine (one engine per chat).
- **Events**: the engine polls the chat folder (no native watcher): 500 ms scans, 300 ms settle,
  dot segments, `~$` and `node_modules` skipped.
- **Widgets**: `sandbox="allow-scripts"` only (v3 also had `allow-same-origin`), loaded as a
  `data:` document, theme variables posted in; no streamed `widget_delta`; the app CSP allows
  `frame-src 'self' data:`.
- **Docs viewer**: DOCX uses the engine's native render (no `docx-preview` in the webview; see
  the spec's resolved DOCX question).
- **Module layout**: the renderer is split further than 3.2 lists. PPTX and XLSX are module folders
  (`preview/pptx/`, `preview/xlsx/`, each with its own chart code; XLSX formulas in
  `preview/xlsx/formula.rs`), the cache is `preview/cache.rs`, and `package.rs`, `html.rs` and
  `pdf.rs` sit beside them; there is no `chart_svg.rs` or `xlsx_formula.rs`.
- **Found while testing**: a reused draft chat with no engine started in the app's working
  directory (`engine-store.ts` `newChat`); fixed to start in the chat's folder.
