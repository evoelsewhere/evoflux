# Office documents: v3 behaviour in v4 (native preview, live build, area edits, versions, widgets) — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

Each phase ships on its own; phases 4–7 need 1–3.

### Phase 1 — Native renderer

Native renderer + preflight + cache + inspection (Rust), golden tests from v3
fixtures.

Done when: FR-1–FR-3 tests pass.

- [x] T1 [FR-1] Port v3's `tests/services/test_document_preview*.py` as golden comparisons against the v3.1.1 Python renderer (3 DOCX, 13 PPTX + 240 fuzzed, 17 XLSX fixtures) — `crates/evo-office` tests (`preview_core`, `preview_docx`, `preview_pptx`, `preview_xlsx`) — check: `cargo test -p evo-office` fails for the right reason
- [x] T2 [FR-1, NFR-2] Port the package preflight and limits — `crates/evo-office/src/preview/security.rs` — check: T1 passes
- [x] T3 [FR-1] Port the PPTX, XLSX and DOCX renderers with charts and XLSX formulas — `crates/evo-office/src/preview/{mod,package,html,pdf,docx}.rs`, `crates/evo-office/src/preview/pptx/`, `crates/evo-office/src/preview/xlsx/` — check: T1 passes
- [x] T4 [FR-2] Preview cache keyed by schema, renderer identity, suffix, name and bytes; LRU 96 entries / 512 MB; stale temp files pruned — `crates/evo-office/src/preview/cache.rs` — check: `cargo test -p evo-office` (`lib`)
- [x] T5 [FR-3] Port the inspection used for the report — `crates/evo-office/src/preview/inspection.rs` — check: `cargo test -p evo-office`

### Phase 2 — `document_preview` tool and skills

`document_preview` tool; skills restored to v3 text (QA via the tool).

Done when: FR-3 and FR-14 pass.

- [x] T6 [FR-3] Add the `document_preview` agent tool with v3's schema, description and report — `crates/evo-engine/src/document_preview_tool.rs` — check: `cargo test -p evo-engine document_preview_tool`; in the app the agent's QA reports "4 pages, every element inside the page box"
- [x] T7 [FR-14] Restore the bundled skills to v3 text with only the renames of plan 3.3; layout QA through `document_preview` — `crates/evo-engine/bundled-skills/{docx,pptx,xlsx}-official` — check: rename/diff audit of every bundled skill file against v3

### Phase 3 — Viewer

Viewer port (native HTML + exact pages, banner, all v3 viewer features).

Done when: FR-4 and FR-5 pass.

- [x] T8 [FR-4] Add the `office_preview` RPC with native / exact / auto modes and fallback — `crates/evo-engine/src/office.rs`, `crates/evo-protocol` — check: manual in the app
- [x] T9 [FR-4, FR-5] Port the viewer: native HTML, exact pages drawn with pdf.js into v3's exact-page markup, runtime banner, zoom, search, keyboard navigation, thumbnails, PPTX views and notes, XLSX name box, formula bar and sheet tabs — `apps/desktop/src/features/files/office/` — check: manual in the running app (owner test)

### Phase 4 — Live build

Live build: scripts, live render, events, follow, auto-open.

Done when: FR-6–FR-9 pass.

- [x] T10 [FR-6] Port v3's live-script checks (`test_live_deck_preview.py`, `test_live_workbook_preview.py`) as `check_live.py` (25 cases; the script is not kept in the repository) — `crates/evo-engine/bundled-skills/{pptx,xlsx}-official/scripts/` — check: `check_live.py` fails for the right reason
- [x] T11 [FR-6] Restore `deck_live.py` / `workbook_live.py`; plans stamped with `EVO_CHAT_ID`; other custom document properties kept — `crates/evo-engine/bundled-skills/pptx-official/scripts/deck_live.py`, `crates/evo-engine/bundled-skills/xlsx-official/scripts/workbook_live.py` — check: T10 passes
- [x] T12 [FR-7] Engine tests: live only for the building chat while its turn runs — `crates/evo-engine` tests — check: `cargo test -p evo-engine`
- [x] T13 [FR-7, NFR-1] Live render (native-live, separate cache key, coalesced per path) and the live check against the chat's own running turn — `crates/evo-office/src/preview/live.rs`, `crates/evo-engine/src/office.rs` — check: T12 passes
- [x] T14 [FR-7, FR-9] Emit `office_file_changed` from the chat-folder scan — `crates/evo-engine/src/fs_watch.rs`, `crates/evo-protocol` — check: manual in the app
- [x] T15 [FR-8] Follow the build in the viewer: collapse thumbnails and file tree, follow the building slide until the user scrolls, jump to the last slide on finish — `apps/desktop/src/features/files/office/` — check: manual in the running app
- [x] T16 [FR-9] Auto-open a new Office file once per turn, with the `files.autoOpenGenerated` setting in **Settings → General** — `apps/desktop/src/` — check: manual in the running app

### Phase 5 — Versions

Done when: FR-12 passes.

- [x] T17 [FR-12] Port v3's `tests/services/test_document_versions.py` — `crates/evo-office/tests/versions.rs` — check: `cargo test -p evo-office --test versions` fails for the right reason
- [x] T18 [FR-12] Port the version store (manifest + content-addressed blobs) — `crates/evo-office/src/versions.rs` — check: T17 passes
- [x] T19 [FR-12] RPCs `document_versions_get` / `document_versions_act`; record settled saves from the file scan; skip a live file for the chat's own engine — `crates/evo-engine/src/office.rs`, `crates/evo-engine/src/fs_watch.rs`, `crates/evo-protocol` — check: manual in the app
- [x] T20 [FR-12] Version controls (undo, redo, restore) in the viewer — `apps/desktop/src/features/files/office/` — check: manual in the running app

### Phase 6 — Area edits

Area edits + `office-annotation-edit` skill (sent as `/skill:` command).

Done when: FR-10 and FR-11 pass.

- [x] T21 [FR-10, FR-11] Port v3's `InputBarAnnotations.test.tsx` cases: annotation format, batch store, geometry — `apps/desktop/src/` tests — check: `bun test` fails for the right reason
- [x] T22 [FR-10] Annotator: shapes on the native render, text lines and areas on exact pages, cell grid on XLSX; shimmer until the turn ends (60 s cap) — `apps/desktop/src/features/files/office/` — check: T21 passes; manual
- [x] T23 [FR-10, FR-11] Batch store, composer chip, user-message chip, block format as a `/skill:office-annotation-edit` command; parser accepts the v3 forms — `apps/desktop/src/stores/annotations-store.ts`, `apps/desktop/src/features/chat/` — check: T21 passes
- [x] T24 [FR-11, FR-14] Bundle the `office-annotation-edit` skill with `targets.py` / `cells.py` — `crates/evo-engine/bundled-skills/office-annotation-edit/{SKILL.md,scripts/targets.py,scripts/cells.py}` — check: manual end to end in the app

### Phase 7 — Widgets

Widgets + `preview.md`.

Done when: FR-13 passes.

- [x] T25 [FR-13] Add `visualize_read_me` and `show_widget` with v3's guideline text — `crates/evo-engine/src/visualize_tool.rs` — check: `cargo test -p evo-engine visualize_tool`
- [x] T26 [FR-13, NFR-2, NFR-3] Widget frame: sandboxed `data:` document, theme variables, auto height, `sendPrompt` bridge — `apps/desktop/src/components/widget-frame.tsx` — check: `bun test` (widget document); manual
- [x] T27 [FR-13, FR-14] Restore the pptx skill's preview step (Phase 2.5) — `crates/evo-engine/bundled-skills/pptx-official/preview.md` — check: manual with `preview.md` in the app

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-office` (preview_core, preview_docx, preview_pptx, preview_xlsx, lib); golden comparisons against the v3.1.1 Python renderer (3 DOCX, 13 PPTX + 240 fuzzed, 17 XLSX fixtures) | passed (2026-11-07) |
| FR-2 | `cargo test -p evo-office` (lib) | passed (2026-11-07) |
| FR-3 | `cargo test -p evo-engine document_preview_tool`; in the app the agent's QA reported "4 pages, every element inside the page box" | passed (2026-11-07) |
| FR-4 | manual in the running app (owner test) | passed (2026-11-07) |
| FR-5 | manual in the running app (owner test) | passed (2026-11-07) |
| FR-6 | v3 live-script checks ported (`check_live.py`, 25 cases) | passed (2026-11-07) |
| FR-7 | engine tests (live only for the building chat while its turn runs) + manual | passed (2026-11-07) |
| FR-8 | manual in the running app (owner test) | passed (2026-11-07) |
| FR-9 | manual in the running app (owner test) | passed (2026-11-07) |
| FR-10 | `bun test` (annotation format, batch store, geometry) + manual in the app | passed (2026-11-07) |
| FR-11 | `bun test` (annotation format) + manual in the app | passed (2026-11-07) |
| FR-12 | `cargo test -p evo-office --test versions` (v3 `test_document_versions.py` ported) | passed (2026-11-07) |
| FR-13 | `cargo test -p evo-engine visualize_tool`, `bun test` (widget document) + manual | passed (2026-11-07) |
| FR-14 | rename/diff audit of every bundled skill file against v3 | passed (2026-11-07) |
| NFR-1 | Bench test | not run |
| NFR-2 | Review + test that scripts in a document do not run | not run |
| NFR-3 | Review | not run |
| NFR-4 | CI on Windows, macOS, Linux | not run |
| All | `cargo clippy` (new files clean), `bun run typecheck`, `bun run build`, `cargo check` in `src-tauri` | passed (2026-11-07) |
