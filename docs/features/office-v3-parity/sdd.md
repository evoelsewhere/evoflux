# Office documents: v3 behaviour in v4 (native preview, live build, area edits, versions, widgets)

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-office`, engine, protocol, desktop shell, desktop UI, bundled skills |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| ADD sections | [Crates](../../architecture/README.md), [Desktop app](../../architecture/README.md) |
| ADRs | [0008 Optional LibreOffice runtime](../../architecture/decisions/0008-optional-libreoffice-runtime.md) (partly superseded), [0009 Native Office preview renderer](../../architecture/decisions/0009-native-office-preview-renderer.md) |
| Related | [Office documents](../office/sdd.md), [Files and Git](../files-git/sdd.md), [Agent tools](../agent-tools/sdd.md), [Customize](../customize-skills-plugins-connectors/sdd.md) |

## 1. Summary

v3 did more with Office files than the v4 port carries. A deck or workbook
built by the agent fills in live in the viewer, one slide or sheet per save. The
person can select a shape, an area or a range of cells and tell the agent what to
change. Every save becomes a version they can undo. The agent checks its layout
with a `document_preview` tool instead of rendering pixels, and can show theme
and slide-grid previews as widgets before building. The v4 port
([Office SDD](../office/sdd.md)) declared these non-goals and rewrote the skills
around them. This feature restores the v3 behaviour on the v4 architecture
(Rust engine, JSONL protocol, Tauri shell, React UI), keeping the v3 skill logic.

The source of truth for "v3 behaviour" is tag `v3.1.1`: `app/services/document_preview/`,
`app/services/document_versions.py`, `app/agent/tools/builtin/{document_preview.py,visualize/}`,
`app/agent/builtin_skills/{docx,pptx,xlsx}-official`, `app/agent/builtin_skills/office-annotation-edit`,
`web/src/components/{workspace-document-preview,document-annotator,document-version-controls,WidgetRenderer}.tsx`,
`web/src/lib/document-annotations.ts`, and `documents/features/workbench-files-and-side-chat.md` (lines 90–293).

## 2. Scope

### 2.1 Goals

- **Native preview renderer** (v3 "built-in renderer"): DOCX, PPTX and XLSX to one
  self-contained, script-free HTML document with the v3 markup contract
  (`data-preview-item`, `data-qa-label`, `data-shape-id`, `data-source-layer`,
  `data-cell`, `data-formula`, % geometry, `data-deck-live`, `data-slide-status`).
  It is the default preview, needs no download, and is what the agent inspects.
- **Exact pages** stay as today (LibreOffice → PDF → pdf.js) and become the
  optional "exact" mode, as in v3: Print layout for XLSX, exact pages for DOCX and
  PPTX once the runtime is installed, with the approximate-preview banner.
- **`document_preview` agent tool**: same description, schema, report text and
  limits as v3.
- **Live build**: `deck_live.py` and `workbook_live.py` restored; the building
  chat sees skeletons for pending slides/sheets while its turn runs; the viewer
  follows the build; finished decks switch to exact pages.
- **Auto-open generated documents**: a new `.pptx/.docx/.xlsx` written during a
  turn opens in Files once (setting, default on).
- **Area edits** ("Select an area to edit" for PPTX, "Select cells to edit" for
  XLSX): selection, popover, batch of up to 20, the `<…-annotations>` block with
  the `/skill:office-annotation-edit` command, the "Annotations: N" chip, shimmer while the agent
  works, and the `office-annotation-edit` skill with `targets.py` / `cells.py`.
- **Document versions**: every settled save of an Office file is a version
  (max 50); undo, redo, restore from the viewer; a checkpoint before each
  annotation; live builds are not versioned until finished.
- **Widgets**: `visualize_read_me` + `show_widget`, rendered in the chat as a
  sandboxed iframe with `sendPrompt()` sending a new user message; restores
  `pptx-official/preview.md` (Phase 2.5).
- **Skills back to v3 text**, changing only what the architecture forces
  (env and tool names). Skills are invoked the v4 way (`/skill:name`), not with v3's `$name` mentions.

### 2.2 Non-goals

- Editing Office files by hand in the app (v3 did not either).
- A Python runtime in the app. The renderer is ported, not embedded (see §6).
- v3 "Work vs Coding" modes: v4 has one kind of chat (see §9, Q2).
- Client-side DOCX rendering with `docx-preview` is optional (see §9, Q3).

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The engine renders DOCX, PPTX and XLSX to HTML with the v3 contract, with the v3 package preflight (`security.py`) and limits (100 MB source, 36 MB HTML, XLSX 500×100 cells). | Golden tests: v3 fixtures render to markup with the same items, labels, shape ids, layers and % boxes as v3 (`tests/services/test_document_preview*.py` ported). |
| FR-2 | The preview cache is keyed by schema, renderer identity, suffix, name and bytes; LRU 96 entries / 512 MB; stale temp files pruned. | Unit tests. |
| FR-3 | `document_preview {path, verbose?}` returns the v3 report text (pages, elements, `OUTSIDE PAGE`, truncation) using the native render. | Tool test against fixtures; report matches v3 output byte for byte for the same file. |
| FR-4 | Files shows Office files from the native render by default; with the runtime installed, PPTX/DOCX switch to exact pages and XLSX offers Print layout; a failed exact render falls back with the v3 banner. | Manual in the app + component tests. |
| FR-5 | Viewer features from v3: zoom 25–300 % and fit modes, search (Ctrl+F), keyboard navigation, thumbnails, PPTX Normal/Sorter/Reading views and notes, XLSX name box, formula bar, sheet tabs, last good render kept while re-rendering. | Manual + component tests. |
| FR-6 | `deck_live.py` / `workbook_live.py` work as in v3 (init/add/mark/finish/rebuild/--replace, plan custom property, scratch copy, atomic save). | v3 tests `test_live_deck_preview.py`, `test_live_workbook_preview.py` ported to the skill's scripts. |
| FR-7 | A deck or workbook renders live (skeletons, `building`/`pending`) only for the chat that builds it and only while that chat's turn runs; everyone else and `document_preview` see the plain file; live renders never use LibreOffice. | Engine tests with two chats; manual. |
| FR-8 | While live, the viewer collapses thumbnails and the file tree, follows the building slide until the user scrolls, and jumps to the last slide on finish. | Manual. |
| FR-9 | A new Office file written during a turn opens in Files once, unless the setting is off or another panel is active. | Manual. |
| FR-10 | Area edits on PPTX (Normal view, native render: shapes; exact pages: text lines and areas) and XLSX (cell grid) produce the v3 annotation items; a message carries up to 20; the chat shows the chip; sent areas shimmer until the turn ends (60 s cap). | UI tests ported from `InputBarAnnotations.test.tsx`; manual. |
| FR-11 | An annotated message is the skill command `/skill:office-annotation-edit <text + block>`, which the engine expands like any skill command; the skill edits only the annotated shapes/cells and reports per item. | Desktop test of the message format; manual end to end. |
| FR-12 | Document versions: record on every settled save, dedupe by hash, max 50, undo/redo/restore, checkpoint before an annotation labels the next change, live builds skipped, mid-write files ignored. | Port `tests/services/test_document_versions.py`. |
| FR-13 | `show_widget` renders HTML in the chat (sandboxed, CSP, theme variables, auto height ≤ 2400 px); `sendPrompt(text)` from that widget sends `text` as a new user message; history replays widgets from the tool arguments. | UI test; manual with `preview.md`. |
| FR-14 | The bundled skills equal v3 except for documented renames; `office-annotation-edit` is bundled. | Diff check in CI: v3 file vs bundled file minus the rename table. |

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | A native render of a 30-slide deck or a 10-sheet workbook takes under 1 s after the file is read; live re-renders are coalesced (one in flight, latest wins). | Bench test. |
| NFR-2 | Rendered HTML runs no script (`script-src 'none'` CSP) and is shown in an iframe with `sandbox="allow-same-origin"`; widgets use the v3 widget CSP. | Review + test that scripts in a document do not run. |
| NFR-3 | No network access for preview; widgets may load only the v3 CDN allowlist. | Review. |
| NFR-4 | Windows, macOS, Linux. | CI. |

## 4. Context and constraints

What v4 has today:

- `crates/evo-office` (runtime install, `convert_to_pdf`), `crates/evo-engine/src/office.rs`
  (`office_status/install/convert`, preview cache, `EVO_SOFFICE`, bundled skills),
  `apps/desktop/src/features/files/document-viewer.tsx` (pdf.js pages, re-render on mtime).
- Engine file watching (`crates/evo-engine/src/fs_watch.rs`), shell env with
  the Office shell-env provider (`office::shell_env`), skills loaded through the
  `skill` tool (`crates/evo-engine/src/skill_tool.rs`), desktop-executed tools
  (`configure_external_tools`, `features/browser/agent-tools.ts`, e.g. `show_file`).
- The `read` tool returns images, which the v4 skill text relies on.

Rules: the engine owns agent logic ([ADD](../../architecture/README.md)); protocol
changes update `evo-protocol`, the engine, `apps/desktop/src/engine/` and stores
together; models.dev and naming rules; trust boundaries (document content is
untrusted data).

v3 infrastructure that has no v4 equivalent and is mapped in §5: the Python
renderer, FastAPI `/api/team/...` routes, SSE `files/watch`, `stream_store.running_session_ids()`,
the Skills hook's synthetic `read`, `EVOFLUX_*` state dirs.

## 5. Design

### 5.1 Overview

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

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| crate | `crates/evo-office/src/preview/{mod,security,pptx,xlsx,docx,chart_svg,xlsx_formula,inspection,live}.rs` | Port of v3 `document_preview/service.py`, `security.py`, `inspection.py`, `live_deck.py`, `xlsx_features.py`, `xlsx_formula.py`; same constants and markup. |
| crate | `crates/evo-office/src/versions.rs` | Port of `document_versions.py` (manifest + content-addressed blobs). |
| engine | `crates/evo-engine/src/office.rs` | RPCs `office_preview`, `document_versions_get/act`; live check against the chat's own running turn. |
| engine | `crates/evo-engine/src/document_preview_tool.rs` | The agent tool. |
| engine | `crates/evo-engine/src/visualize_tool.rs` | `visualize_read_me`, `show_widget` (guideline text from v3 `visualize/guidelines.py`). |
| engine | `crates/evo-engine/src/fs_watch.rs` | Emits Office file changes to the client and to versions. |
| skills | `crates/evo-engine/bundled-skills/{docx,pptx,xlsx}-official`, `office-annotation-edit/` | v3 text and scripts, renamed per §5.3. |
| protocol | `crates/evo-protocol` | New RPCs and the `office_file_changed` event. |
| desktop UI | `apps/desktop/src/features/files/office/` | Port of `workspace-document-preview.tsx`, `document-annotator.tsx`, `document-version-controls.tsx`, thumbnail and search helpers, runtime banner. |
| desktop UI | `apps/desktop/src/stores/annotations-store.ts`, `features/chat/*` | Batch store, composer chip, user-message chip, block format. |
| desktop UI | `apps/desktop/src/components/widget-frame.tsx` | Port of `WidgetRenderer.tsx`. |

### 5.3 Interfaces

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

### 5.4 Data and storage

- Preview cache: `<agent>/cache/office/previews/<sha>.html` (beside today's PDF cache).
- Versions: `<agent>/document-versions/<chat>/<sha256(rel)[:32]>/manifest.json` + `blobs/<sha256>`; deleted with the chat.
- Live plan: inside the document (`docProps/custom.xml`) plus the scratch copy in the system temp dir (v3).
- Annotation batch: UI memory only (v3).
- Setting `files.autoOpenGenerated` (bool, default true) in the app settings table.

### 5.5 Behaviour

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

### 5.6 Errors and edge cases

As v3: unsupported/legacy/password-protected files get named messages; a failing shape is
skipped; mid-write reads keep the last good render; restore after the file changed fails
with "The file changed since, so that version was replaced."; Windows lock → retry, then
"The file is open elsewhere; close it and retry."; an interrupted live build renders plainly
once the turn ends.

### 5.7 Security and trust

Document content stays untrusted (skills say so; the annotation `text` is orientation only).
Preview HTML is script-free with the v3 CSP and preflight (no macros, ActiveX, embedded
executables; zip-bomb limits). Widgets run model-written script in a sandboxed iframe with
the v3 CSP and a postMessage bridge restricted to `sendPrompt`; they get no Tauri IPC.
Versions store copies of user files under the agent dir only.

### 5.8 Configuration

`files.autoOpenGenerated` (Settings → General, live). No other settings; the runtime install
stays in the Files preview.

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| Port the renderer to Rust (**proposed**) | — Engine owns it; works for headless chats and the agent tool; no extra runtime. Cost: the largest piece of work (≈5 000 lines of Python). |
| Run the v3 Python renderer via `uv run` | Exact code reuse, but every preview then needs `uv` and a first-run package download; latency of a Python start per live save; a second language in the engine path. |
| Port the renderer to TypeScript in the webview | No Rust work for rendering, but the agent tool and headless chats would depend on the UI (external tool), and the engine could not version or inspect without it. |
| Keep LibreOffice pages only | No shape ids or cell grid: area edits reduce to areas on PPTX and are impossible on XLSX; live builds cost seconds per save; `document_preview` loses geometry. This is today's gap. |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | Native renderer + preflight + cache + inspection (Rust), golden tests from v3 fixtures | `evo-office/src/preview/*` | FR-1–FR-3 tests pass |
| 2 | `document_preview` tool; skills restored to v3 text (QA via the tool) | engine, `bundled-skills` | FR-3, FR-14 |
| 3 | Viewer port (native HTML + exact pages, banner, all v3 viewer features) | `features/files/office/*` | FR-4, FR-5 |
| 4 | Live build: scripts, live render, events, follow, auto-open | skills, engine, desktop | FR-6–FR-9 |
| 5 | Versions | `evo-office/versions.rs`, engine, desktop | FR-12 |
| 6 | Area edits + `office-annotation-edit` skill (sent as `/skill:` command) | desktop, engine, skills | FR-10, FR-11 |
| 7 | Widgets + `preview.md` | engine, desktop, skills | FR-13 |

Each phase ships on its own; phases 4–7 need 1–3.

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1, FR-2 | `cargo test -p evo-office` (preview_core, preview_docx, preview_pptx, preview_xlsx, lib); golden comparisons against the v3.1.1 Python renderer (3 DOCX, 13 PPTX + 240 fuzzed, 17 XLSX fixtures) | passed (2026-11-07) |
| FR-3 | `cargo test -p evo-engine document_preview_tool`; in the app the agent's QA reported "4 pages, every element inside the page box" | passed (2026-11-07) |
| FR-4, FR-5, FR-8, FR-9 | manual in the running app (owner test) | passed (2026-11-07) |
| FR-6 | v3 live-script checks ported (`check_live.py`, 25 cases) | passed (2026-11-07) |
| FR-7 | engine tests (live only for the building chat while its turn runs) + manual | passed (2026-11-07) |
| FR-10, FR-11 | `bun test` (annotation format, batch store, geometry) + manual in the app | passed (2026-11-07) |
| FR-12 | `cargo test -p evo-office --test versions` (v3 `test_document_versions.py` ported) | passed (2026-11-07) |
| FR-13 | `cargo test -p evo-engine visualize_tool`, `bun test` (widget document) + manual | passed (2026-11-07) |
| FR-14 | rename/diff audit of every bundled skill file against v3 | passed (2026-11-07) |
| All | `cargo clippy` (new files clean), `bun run typecheck`, `bun run build`, `cargo check` in `src-tauri` | passed (2026-11-07) |

## 9. Open questions

1. **Renderer technology** — proposed: Rust port in `evo-office` (§6).
2. **Where area edits and versions apply** — v3 limited them to "Work" sessions (not
   Coding, where Git covers versions). Proposed: every chat; versions only for files
   inside the chat's working folder.
3. **DOCX rendering** — v3 rendered DOCX in the webview with `docx-preview@0.4.1` (patched)
   and used python-docx only as fallback and for the agent tool. Proposed: same (bun
   package + patch) for display; the Rust native DOCX render for fallback and `document_preview`.
4. **Names** — proposed renames in §5.3 (`evo.deck`, `<evo-annotations>`), with readers
   that accept the v3 names so files built by v3 still work.
5. **Skill QA policy** — v3: no pixel pass unless asked, `document_preview` is the layout
   check. v4 port made rendering to PNG the default. Proposed: back to v3; keep
   `pdf_out.py --png` as an extra the skills mention only for "when the user asks".
6. **Settings → Office page** — removed today; v3 had none either (runtime offer lived in
   the viewer banner). Proposed: keep it removed; the banner gets v3's "Update renderer"
   and per-version "hide offer".

## 10. As-built notes

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
- **Docs viewer**: DOCX uses the engine's native render (no `docx-preview` in the webview, §9 Q3).
- **Found while testing**: a reused draft chat with no engine started in the app's working
  directory (`engine-store.ts` `newChat`); fixed to start in the chat's folder.

## 11. History

- 2026-11-07 — Draft, from a study of tag `v3.1.1` (preview service, live decks, annotation
  edits, versions, widgets, skill wiring).
- 2026-11-07 — Accepted by the owner with the proposed answers to §9; In progress.
- 2026-11-07 — Implemented; `$` mentions replaced by `/skill:` commands; v3 bugs fixed on the
  owner's request; tested in the app by the owner.
