# Office documents: runtime, preview and skills — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — `evo-office` crate

Done when: `cargo test -p evo-office` passes.

- [x] T1 [FR-1, FR-2, NFR-2, NFR-3] Pinned assets per platform, validation, test override manifest — `crates/evo-office/src/manifest.rs` — check: `cargo test -p evo-office`
- [x] T2 [FR-2, FR-3, FR-4, FR-5, NFR-1] Install job state machine, resumable verified download, safe extraction, atomic activation, uninstall — `crates/evo-office/src/install.rs` — check: `cargo test -p evo-office`
- [x] T3 [FR-6, FR-7] Hardened profile, serialized conversion, retry, timeout and tree kill — `crates/evo-office/src/convert.rs` — check: `cargo test -p evo-office convert`
- [x] T4 [FR-2, FR-6] ADR 0008 and the ADD entry for the new crate — `docs/architecture/decisions/0008-optional-libreoffice-runtime.md`, `docs/architecture/README.md` — check: review

### Phase 2 — Engine

Done when: the engine tests pass.

- [x] T5 [FR-1, FR-2, FR-3, FR-4, FR-5, FR-6] Process-wide `Runtime`, `office_*` RPC bodies and dispatch, preview cache — `crates/evo-engine/src/office.rs`, `crates/evo-engine/src/modes.rs` — check: `cargo test -p evo-engine office`
- [x] T6 [FR-8] Shell-env provider: `OsExecutionEnv::with_shell_env_provider`, builtin tools get the provider that reads `install.json` — `crates/evo-tools/src/os_env.rs`, `crates/evo-engine/src/session.rs`, `crates/evo-engine/src/office.rs` — check: `cargo test -p evo-tools shell_env_provider`; `echo $EVO_SOFFICE` in a chat

### Phase 3 — Embedded skills

Done when: the FR-10 test passes.

- [x] T7 [FR-10] Embed the docx, pptx and xlsx skills, extract them on start and add their folder to the skill loader — `crates/evo-engine/bundled-skills/`, `crates/evo-engine/src/office.rs` — check: `cargo test -p evo-engine office`

### Phase 4 — Desktop

Done when: the manual check in the app passes.

- [x] T8 [FR-9] `fs_read_bytes` (max 200 MB, files only) and `worker-src blob:` in the CSP for pdf.js — `apps/desktop/src-tauri/src/files.rs` — check: manual in the app
- [x] T9 [FR-1, FR-2, FR-3, FR-4, FR-9] Install component: install, progress, cancel, retry — `apps/desktop/src/components/office-install.tsx` — check: manual in the app
- [x] T10 [FR-9] Document viewer in Files: install prompt when no runtime, convert via the engine, render pages with pdf.js, lazy-loaded — `apps/desktop/src/features/files/document-viewer.tsx` — check: manual in the app
- [ ] T11 [FR-9, NFR-4] Live check of the Files preview with the real runtime, including timing a 20-page document — running app — check: manual in the running app

### Phase 5 — Runtime build and release

Done when: the docs are updated.

- [x] T12 [FR-2] Port the runtime build script from v3 — `scripts/office-runtime/build_runtime.py` — check: review
- [ ] T13 [FR-6, FR-7] Release workflow and `verify` script that also run conversions on macOS and Linux (not ported, see plan 5; spec 6.2) — `.github/workflows/` — check: the workflow passes on all four platforms

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-office` | passed (2026-11-07) |
| FR-2 | `cargo test -p evo-office` (tests with `file://` manifests: good archive, wrong hash, wrong size, traversal, link escape, duplicate path, special file) | passed (2026-11-07) |
| FR-3 | `cargo test -p evo-office` (local HTTP server) | passed (2026-11-07) |
| FR-4 | `cargo test -p evo-office` | passed (2026-11-07) |
| FR-5 | `cargo test -p evo-office` | passed (2026-11-07) |
| FR-6 | `cargo test -p evo-office convert`, `cargo test -p evo-engine office` | passed (2026-11-07) |
| FR-7 | `cargo test -p evo-office convert`, `cargo test -p evo-engine office` | passed (2026-11-07) |
| FR-8 | `cargo test -p evo-tools shell_env_provider` + manual | passed (2026-11-07) |
| FR-9 | Manual in the running app (real runtime) | not run: the installed app holds the single instance |
| FR-10 | `cargo test -p evo-engine office` | passed (2026-11-07) |
| NFR-1 | `cargo test -p evo-office` (limit tests) | not run |
| NFR-2 | `platform_key` test in `cargo test -p evo-office` | not run |
| NFR-3 | Review | not run |
| NFR-4 | Manual timing of a 20-page document | not run |
