# Code intelligence (language servers) — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — Language server library

Done when: `evo-lsp` finds, installs, starts and queries servers, and
`examples/lsp-try.rs` answers from a real server.

- [x] T1 [FR-5] Server catalog — `crates/evo-lsp/src/catalog.rs` — check: `cargo test -p evo-lsp files_map_to_servers`
- [x] T2 [P] [FR-11] Project language detection — `crates/evo-lsp/src/detect.rs` — check: `cargo test -p evo-lsp a_mixed_project_is_detected`
- [x] T3 [P] [FR-6, FR-7, FR-8, NFR-1, NFR-2] Locate and install servers — `crates/evo-lsp/src/install.rs` — check: `cargo test -p evo-lsp binaries_are_found_in_unpacked_folders`, `missing_programs_are_reported`
- [x] T4 [FR-3, FR-4] LSP client over stdio with indexing waits and diagnostics — `crates/evo-lsp/src/client.rs` — check: manual run with rust-analyzer
- [x] T5 [FR-10] Server pool per (server, root) — `crates/evo-lsp/src/pool.rs` — check: `cargo test -p evo-lsp roots_are_the_nearest_marker_folder`
- [x] T6 [FR-1, FR-2, FR-3, NFR-3] Operations and positions — `crates/evo-lsp/src/ops.rs` — check: `cargo test -p evo-lsp positions_find_symbols_on_word_boundaries`, `diagnostics_read_well`, `locations_take_every_shape`
- [x] T7 Terminal tryout — `crates/evo-lsp/examples/lsp-try.rs` — check: runs against a scratch Cargo project

### Phase 2 — Engine tool and RPC

Done when: a chat's agent can call `lsp`, and the RPC commands list,
install, uninstall and switch servers.

- [x] T8 [FR-1, FR-2, FR-9] The `lsp` tool and `disabledLanguageServers` — `crates/evo-engine/src/lsp_tool.rs` — check: manual run with a real model
- [x] T9 [FR-7, FR-8, FR-9] RPC `list_language_servers`, `install_language_server`, `uninstall_language_server`, `set_language_server_enabled` — `crates/evo-engine/src/lsp_tool.rs` — check: `cargo test -p evo-engine the_list_names_every_server`

### Phase 3 — Desktop

Done when: the page manages servers, the notice appears once per folder, and
transcript rows read in words.

- [x] T10 [P] [FR-12] **Customize → Code intelligence** page — `apps/desktop/src/features/customize/languages-section.tsx` — check: manual in the running app
- [x] T11 [P] [FR-13] Once-per-folder notice — `apps/desktop/src/stores/engine-store.ts` — check: manual in the running app
- [x] T12 [P] [FR-14] Transcript row labels — `apps/desktop/src/components/ai-elements/tool.tsx` — check: manual in the running app

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | Manual: real rust-analyzer on a scratch Cargo project — diagnostics, references (definition and three calls with their lines), hover (signature and doc comment), definition (jumped to `math.rs`) | passed (2026-11-06) for those four operations; the others not run |
| FR-2 | `cargo test -p evo-lsp positions_find_symbols_on_word_boundaries` | not run |
| FR-3 | Manual: diagnostics returned the compiler's E0308 with its hints from a cold start | passed (2026-11-06) |
| FR-4 | Manual: edit a file in a scratch Cargo project, then ask for diagnostics | not run |
| FR-5 | `cargo test -p evo-lsp files_map_to_servers`; `cargo test -p evo-engine the_list_names_every_server` | not run |
| FR-6 | `cargo test -p evo-lsp binaries_are_found_in_unpacked_folders` | not run |
| FR-7 | Manual: Install from npm and GitHub in the running app | not run (installs download and run code; done only on the person's press) |
| FR-8 | Manual: Uninstall an evo install in the running app | not run |
| FR-9 | Manual: switch a server off on the page, then call `lsp` | not run |
| FR-10 | `cargo test -p evo-lsp roots_are_the_nearest_marker_folder` | not run |
| FR-11 | `cargo test -p evo-lsp a_mixed_project_is_detected` | not run |
| FR-12 | Manual: **Customize → Code intelligence** in the running app | not run |
| FR-13 | Manual: open a chat in a project with three or more files of a language without a server | not run |
| FR-14 | Manual: transcript rows after `lsp` calls | not run |
| NFR-1 | Review: installs start only from `install_language_server` | not run |
| NFR-2 | Review of `install.rs`; manual install on Windows | not run |
| NFR-3 | `cargo test -p evo-lsp positions_find_symbols_on_word_boundaries` | not run |
| SC-1 | Manual: cold-start diagnostics on a scratch Cargo project | passed (2026-11-06, about 7 s) |
| SC-2 | Manual: a real model used diagnostics and references in parallel on its own and answered correctly | passed (2026-11-06) |
