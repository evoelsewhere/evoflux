# Git in the Files tool — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — Tree status

Scope: status colours and letters, folder dots, ignored dimming.

Done when: FR-1, FR-2, FR-3, FR-6 and FR-7 pass — changed files show their
letter, their folders a dot, ignored paths are dimmed, and a non-git folder
looks unchanged.

- [x] T1 [FR-3, FR-6] Add `ignored_paths(dir)` (`git ls-files --others --ignored --exclude-standard --directory`), `None` outside a repository — `crates/evo-worktrees/src/lib.rs` — check: `cargo test -p evo-worktrees head_text_and_ignored_paths` (incl. the non-repo case)
- [x] T2 [FR-3, FR-6, NFR-2] Add the `git_ignored` command on a blocking thread; keep `git_status` unchanged — `apps/desktop/src-tauri/src/worktrees.rs` — check: running app: `git_status` / `git_ignored` return `null` outside a repository
- [x] T3 [FR-1, FR-3] Typed wrapper `git.ignored` — `apps/desktop/src/lib/git.ts` — check: `bun run typecheck`
- [x] T4 [FR-1, FR-2, FR-3] Write the tree decoration tests — `apps/desktop/tests/files-git.test.ts` — check: `bun test tests/files-git.test.ts`
- [x] T5 [FR-1, FR-2, FR-3] Pure decorations: status + ignored list → file states, folder dots, ignored sets; `rowGit` per row — `apps/desktop/src/features/files/git-state.ts` — check: T4 passes
- [x] T6 [FR-1, FR-6, NFR-1] Store the tree folder's `git` decorations; `refreshGit` runs one read at a time, collapses requests into one follow-up and does not set unchanged results; errors clear decorations with one log line — `apps/desktop/src/stores/files-store.ts` — check: running app over CDP
- [x] T7 [FR-1, FR-2, FR-3, FR-7] Panel: refresh on open, folder change, every 2 s while visible, on focus and on Refresh (ignored list re-read on Refresh and every fifth read); row letter, folder dot, dimming, tooltip — `apps/desktop/src/features/files/files-panel.tsx` — check: running app over CDP; screenshots in dark and light

### Phase 2 — Editor gutter markers

Scope: gutter markers against `HEAD`.

Done when: FR-4 and FR-5 pass — added, modified and removed lines are marked
and follow unsaved edits.

- [x] T8 [FR-4, FR-6, NFR-3] Add `file_at_head(dir, path)` (`git show HEAD:<path>`): path canonicalised and kept inside the root, no `..`, 1 MB cap, `-c core.fsmonitor=false` — `crates/evo-worktrees/src/lib.rs` — check: `cargo test -p evo-worktrees` (tracked, relative path, untracked, outside root, `..`)
- [x] T9 [FR-4, NFR-2] Add the `git_file_base` command and the `git.fileBase` wrapper — `apps/desktop/src-tauri/src/worktrees.rs`, `apps/desktop/src/lib/git.ts` — check: running app: `git_file_base` returns `null` outside a repository
- [x] T10 [FR-4, FR-5] Write the line diff tests (add / change / delete / CRLF / fallback / 300 random edits) — `apps/desktop/tests/files-git.test.ts` — check: `bun test tests/files-git.test.ts`
- [x] T11 [FR-4, FR-5, FR-7] Myers line diff (CRLF normalised, one hunk past 2000 edits) and the CodeMirror gutter extension, recomputed 300 ms after the last edit — `apps/desktop/src/features/files/git-gutter.ts` — check: T10 passes
- [x] T12 [FR-4] Mount the gutter between line numbers and folding with a `gitBase` prop; `useGitBase` reads the open file's HEAD text again when `head` changes or the file starts or stops being new — `apps/desktop/src/features/files/code-editor.tsx`, `apps/desktop/src/features/files/files-panel.tsx` — check: running app: an unsaved change and deletion show the modified bar and removed wedge within 500 ms; Reload restores the HEAD markers

### Phase 3 — Hunk peek

Scope: peek of the old text.

Done when: clicking a marker shows the old lines (FR-8).

- [x] T13 [FR-8] Hunk peek: the hunk's HEAD lines muted and struck through under the marker; clicking again, Esc or an edit closes it — `apps/desktop/src/features/files/git-gutter.ts` — check: running app: clicking the modified marker shows the committed line
- [x] T14 [FR-1, FR-4, FR-8] Update the Files row of the UI map — `apps/desktop/README.md` — check: the row describes letters, dots, dimming, gutter markers and the peek

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `bun test tests/files-git.test.ts` (tree decorations); running app over CDP: `M` on changed files | passed (2026-11-07) |
| FR-2 | `bun test tests/files-git.test.ts` (tree decorations); running app over CDP: dots on the folders of changed files, green dot on an untracked folder | passed (2026-11-07) |
| FR-3 | `bun test tests/files-git.test.ts` (tree decorations); running app over CDP: `node_modules` / `dist` / `.evo` dimmed | passed (2026-11-07) |
| FR-4 | `bun test` (line diff: add / change / delete / CRLF / fallback / 300 random edits); `cargo test -p evo-worktrees` (`file_at_head`: tracked, relative path, untracked, outside root, `..`); running app: an unsaved change and deletion show the modified bar and removed wedge; Reload restores the HEAD markers | passed (2026-11-07) |
| FR-5 | Running app: an unsaved change shows its marker within 500 ms | passed (2026-11-07) |
| FR-6 | `cargo test -p evo-worktrees` (`head_text_and_ignored_paths`, non-repo case); running app: `git_status` / `git_ignored` / `git_file_base` return `null` outside a repository, no console errors | passed (2026-11-07) |
| FR-7 | Screenshots, dark and light | passed (2026-11-07) |
| FR-8 | Running app: clicking the modified marker shows the committed line | passed (2026-11-07) |
| NFR-1 | Watch the calls: one `git_status` per burst of changes | not run |
| NFR-2 | A 50k-file repository: the UI stays responsive; commands run on a blocking thread | not run |
| NFR-3 | Open a file over 1 MB and a binary file: no markers, no lag (the `file_at_head` tests do not cover the binary case) | not run |
