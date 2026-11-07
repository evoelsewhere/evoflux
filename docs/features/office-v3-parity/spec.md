# Office documents: v3 behaviour in v4 (native preview, live build, area edits, versions, widgets) — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-office`, engine, protocol, desktop shell, desktop UI, bundled skills |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Office documents](../office/spec.md), [Files and Git](../files-git/spec.md), [Agent tools](../agent-tools/spec.md), [Customize](../customize-skills-plugins-connectors/spec.md) |

## 1. Summary

v3 did more with Office files than the v4 port carries. A deck or workbook
built by the agent fills in live in the viewer, one slide or sheet per save. The
person can select a shape, an area or a range of cells and tell the agent what to
change. Every save becomes a version they can undo. The agent checks its layout
with a `document_preview` tool instead of rendering pixels, and can show theme
and slide-grid previews as widgets before building. The v4 port
([Office documents](../office/spec.md)) declared these non-goals and rewrote the
skills around them. This feature restores the v3 behaviour on the v4
architecture, keeping the v3 skill logic. "v3 behaviour" means the behaviour of
tag `v3.1.1` (the sources studied are listed in [plan 1](plan.md#1-context-and-constraints)).

## 2. Scope

### 2.1 Goals

- **Native preview renderer** (v3 "built-in renderer"): DOCX, PPTX and XLSX to one
  self-contained, script-free HTML document with the v3 markup contract
  ([plan 3.3](plan.md#33-interfaces)). It is the default preview, needs no
  download, and is what the agent inspects.
- **Exact pages** stay as today (LibreOffice → PDF) and become the optional
  "exact" mode, as in v3: Print layout for XLSX, exact pages for DOCX and PPTX
  once the runtime is installed, with the approximate-preview banner.
- **`document_preview` agent tool**: same description, schema, report text and
  limits as v3.
- **Live build**: the v3 live-build scripts (`deck_live.py`, `workbook_live.py`)
  restored; the building chat sees skeletons for pending slides/sheets while its
  turn runs; the viewer follows the build; finished decks switch to exact pages.
- **Auto-open generated documents**: a new `.pptx/.docx/.xlsx` written during a
  turn opens in Files once (setting, default on).
- **Area edits** ("Select an area to edit" for PPTX, "Select cells to edit" for
  XLSX): selection, popover, batch of up to 20, the annotations block with the
  `/skill:office-annotation-edit` command, the "Annotations: N" chip, shimmer
  while the agent works, and the `office-annotation-edit` skill.
- **Document versions**: every settled save of an Office file is a version
  (max 50); undo, redo, restore from the viewer; a checkpoint before each
  annotation; live builds are not versioned until finished.
- **Every chat**: area edits and versions work in every chat (v4 has no
  "Work" vs "Coding" split); versions cover only files inside the chat's
  working folder.
- **Widgets**: `visualize_read_me` + `show_widget`, rendered in the chat as a
  sandboxed frame with `sendPrompt()` sending a new user message; restores the
  pptx skill's preview step (Phase 2.5).
- **Skills back to v3 text**, changing only what the architecture forces
  (env and tool names). Skills are invoked the v4 way (`/skill:name`), not with
  v3's `$name` mentions.

### 2.2 Non-goals

- Editing Office files by hand in the app (v3 did not either).
- A Python runtime in the app. The renderer is ported, not embedded (see
  [plan 4](plan.md#4-alternatives-considered)).
- v3 "Work vs Coding" modes: v4 has one kind of chat (see 6.2).
- Client-side DOCX rendering in the webview (see 6.2).

## 3. User scenarios

### US-1 Watch a document being built (priority P1)

A person who asks the agent for a deck or workbook wants to see it fill in as
the agent works, without opening anything by hand.

Acceptance scenarios:

1. **Given** a turn that writes a new `.pptx`, **when** the file appears,
   **then** it opens in Files once (unless the setting is off or another panel
   is active).
2. **Given** a deck being built live, **when** the agent adds slides, **then**
   the building chat shows skeletons for pending slides, the viewer collapses
   thumbnails and the file tree and follows the building slide until the
   person scrolls.
3. **Given** the build finishes, **when** the turn ends, **then** the viewer
   jumps to the last slide, and with the runtime installed the deck switches to
   exact pages.
4. **Given** another chat opens the same file during the build, **when** it
   previews it, **then** it sees the plain file, not the live state.

### US-2 Preview Office files without installing anything (priority P1)

A person opening an Office file wants to read it right away, and exact pages
when they have the runtime.

Acceptance scenarios:

1. **Given** no runtime installed, **when** the person opens a DOCX, PPTX or
   XLSX, **then** it shows from the native render, with the v3 viewer
   features (zoom, search, thumbnails, PPTX views and notes, XLSX name box,
   formula bar and sheet tabs).
2. **Given** the runtime installed, **when** the person opens a PPTX or DOCX,
   **then** exact pages show; a failed exact render falls back with the v3
   banner.

### US-3 Point at part of a document and ask for a change (priority P1)

A person wants to select shapes, an area or cells and tell the agent what to
change there, so that only those parts change.

Acceptance scenarios:

1. **Given** a PPTX in Normal view, **when** the person selects a shape and
   writes an instruction, **then** the item joins a batch and the composer
   shows "Annotations: N".
2. **Given** a batch of annotations, **when** the person sends it, **then**
   the message is the `office-annotation-edit` skill command with the
   annotations, the sent areas shimmer until the turn ends (60 s cap), and the
   agent edits only the annotated shapes/cells and reports per item.

### US-4 Undo the agent's change to a document (priority P2)

A person wants to step back to an earlier version of an Office file the agent
changed.

Acceptance scenarios:

1. **Given** several settled saves of a file, **when** the person clicks undo
   in the viewer, **then** the previous version is restored; redo brings it
   back.
2. **Given** a version older than a later change to the file, **when** the
   person restores it after the file changed again, **then** they see "The file
   changed since, so that version was replaced."

### US-5 Let the agent check its own layout (priority P2)

A person wants the agent to catch shapes outside the page without pixel
renders.

Acceptance scenarios:

1. **Given** a generated document, **when** the agent calls
   `document_preview`, **then** it gets the v3 report (pages, elements,
   `OUTSIDE PAGE`, truncation).

### US-6 Choose a design from widget previews (priority P3)

A person wants to see theme and slide-grid options in the chat and pick one
before the build starts.

Acceptance scenarios:

1. **Given** the pptx skill's preview step, **when** the agent shows a
   widget, **then** it renders in the chat, and a choice made in it is sent as
   a new user message.

### Edge cases

- Unsupported, legacy or password-protected files get named messages.
- A file read mid-write keeps the last good render.
- A live build interrupted by the end of the turn renders plainly afterwards.
- On Windows a locked file is retried, then the person is asked to close it
  elsewhere.
- Files built by v3 (old property and tag names) still work.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The engine renders DOCX, PPTX and XLSX to HTML with the v3 contract, with the v3 package preflight and limits (100 MB source, 36 MB HTML, XLSX 500×100 cells). | Golden tests: v3 fixtures render to markup with the same items, labels, shape ids, layers and % boxes as v3 (v3 preview tests ported). |
| FR-2 | The preview cache is keyed by schema, renderer identity, suffix, name and bytes; LRU 96 entries / 512 MB; stale temp files pruned. | Unit tests. |
| FR-3 | `document_preview {path, verbose?}` returns the v3 report text (pages, elements, `OUTSIDE PAGE`, truncation) using the native render. | Tool test against fixtures; report matches v3 output byte for byte for the same file. |
| FR-4 | Files shows Office files from the native render by default; with the runtime installed, PPTX/DOCX switch to exact pages and XLSX offers Print layout; a failed exact render falls back with the v3 banner. | Manual in the app + component tests. |
| FR-5 | Viewer features from v3: zoom 25–300 % and fit modes, search (Ctrl+F), keyboard navigation, thumbnails, PPTX Normal/Sorter/Reading views and notes, XLSX name box, formula bar, sheet tabs, last good render kept while re-rendering. | Manual + component tests. |
| FR-6 | `deck_live.py` / `workbook_live.py` work as in v3 (init/add/mark/finish/rebuild/--replace, plan custom property, scratch copy, atomic save). | v3 live-preview tests ported to the skill's scripts. |
| FR-7 | A deck or workbook renders live (skeletons, `building`/`pending`) only for the chat that builds it and only while that chat's turn runs; everyone else and `document_preview` see the plain file; live renders never use LibreOffice. | Engine tests with two chats; manual. |
| FR-8 | While live, the viewer collapses thumbnails and the file tree, follows the building slide until the user scrolls, and jumps to the last slide on finish. | Manual. |
| FR-9 | A new Office file written during a turn opens in Files once, unless the setting is off or another panel is active. | Manual. |
| FR-10 | Area edits on PPTX (Normal view, native render: shapes; exact pages: text lines and areas) and XLSX (cell grid) produce the v3 annotation items; a message carries up to 20; the chat shows the chip; sent areas shimmer until the turn ends (60 s cap). | UI tests ported from v3's composer annotation tests; manual. |
| FR-11 | An annotated message is the skill command `/skill:office-annotation-edit <text + block>`, which the engine expands like any skill command; the skill edits only the annotated shapes/cells and reports per item. | Desktop test of the message format; manual end to end. |
| FR-12 | Document versions: record on every settled save, dedupe by hash, max 50, undo/redo/restore, checkpoint before an annotation labels the next change, live builds skipped, mid-write files ignored. | v3 document-version tests ported. |
| FR-13 | `show_widget` renders HTML in the chat (sandboxed, CSP, theme variables, auto height ≤ 2400 px); `sendPrompt(text)` from that widget sends `text` as a new user message; history replays widgets from the tool arguments. | UI test; manual with the pptx skill's preview step. |
| FR-14 | The bundled skills equal v3 except for documented renames; `office-annotation-edit` is bundled. | Diff check in CI: v3 file vs bundled file minus the rename table. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | A native render of a 30-slide deck or a 10-sheet workbook takes under 1 s after the file is read; live re-renders are coalesced (one in flight, latest wins). | Bench test. |
| NFR-2 | Rendered HTML runs no script (`script-src 'none'` CSP) and is shown in an iframe with `sandbox="allow-same-origin"`; widgets use the v3 widget CSP. | Review + test that scripts in a document do not run. |
| NFR-3 | No network access for preview; widgets may load only the v3 CDN allowlist. | Review. |
| NFR-4 | Windows, macOS, Linux. | CI. |

## 5. Success criteria

- SC-1 A person can open any DOCX, PPTX or XLSX the agent produced and read it
  without downloading anything.
- SC-2 A 30-slide deck or a 10-sheet workbook shows in under 1 s after the
  file is read.
- SC-3 While the agent builds a deck, the person sees each slide appear without
  reopening the file.
- SC-4 A person can undo any of the last 50 settled saves of an Office file.
- SC-5 An area edit changes only the shapes or cells the person selected.

## 6. Clarifications

### 6.1 Open

n/a — none open.

### 6.2 Resolved

- 2026-11-07 — Q: Renderer technology? → A: A Rust port in the engine's
  Office crate ([plan 4](plan.md#4-alternatives-considered)).
- 2026-11-07 — Q: Where do area edits and versions apply? v3 limited them to
  "Work" sessions (not Coding, where Git covers versions). → A: Every chat;
  versions only for files inside the chat's working folder (section 2.1).
- 2026-11-07 — Q: DOCX rendering? v3 rendered DOCX in the webview with
  `docx-preview@0.4.1` (patched) and used python-docx only as fallback and for
  the agent tool. → A: Accepted proposal was the same (bun package + patch) for
  display and the native DOCX render for fallback and `document_preview`. As
  built, DOCX display also uses the native render, with no client-side DOCX
  library ([plan 5](plan.md#5-as-built-notes)).
- 2026-11-07 — Q: Names? → A: The renames in [plan 3.3](plan.md#33-interfaces)
  (`evo.deck`, `<evo-annotations>`), with readers that accept the v3 names so
  files built by v3 still work.
- 2026-11-07 — Q: Skill QA policy? v3: no pixel pass unless asked,
  `document_preview` is the layout check; the v4 port made rendering to PNG the
  default. → A: Back to v3; keep `pdf_out.py --png` as an extra the skills
  mention only for "when the user asks" (FR-3, FR-14).
- 2026-11-07 — Q: Settings → Office page? It is removed today; v3 had none
  either (the runtime offer lived in the viewer banner). → A: Keep it removed;
  the banner gets v3's "Update renderer" and per-version "hide offer" (FR-4).

## 7. History

- 2026-11-07 — Draft, from a study of tag `v3.1.1` (preview service, live decks, annotation
  edits, versions, widgets, skill wiring).
- 2026-11-07 — Accepted by the owner with the proposed answers to the open questions; In progress.
- 2026-11-07 — Implemented; `$` mentions replaced by `/skill:` commands; v3 bugs fixed on the
  owner's request; tested in the app by the owner.
- 2026-11-07 — Moved to the spec / plan / tasks format.
