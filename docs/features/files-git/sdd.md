# Git in the Files tool

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-worktrees`, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| ADD sections | [Desktop app](../../architecture/README.md) |
| ADRs | none |
| Related | [Subagents and nested sessions](../subagents-and-nested-sessions/sdd.md) (`repo_status`, `FileChange`) |

## 1. Summary

The Files tool (Ctrl+F) knows nothing about git: the tree and the editor look
the same for a clean and a dirty repository. This feature marks changed files
in the tree (colour and a status letter, like other editors) and marks the
changed lines of the open file in the editor gutter, so the person sees what
the agent or they changed without leaving Files.

## 2. Scope

### 2.1 Goals

- Tree: files that are modified, added/untracked or deleted get a status colour
  and letter; folders containing changes get a dot; ignored files are dimmed.
- Editor: a gutter marker per changed line against `HEAD` (added, modified,
  deleted-above), updated as the person types and when the file changes on disk.
- Clicking a gutter marker shows the old text of that hunk (read-only peek).
- Refreshes by itself when files change, without a manual button.

### 2.2 Non-goals

- Staging, committing, discarding hunks or any write to the repository. Files
  stays read-only with respect to git.
- A full diff view or blame (a later feature).
- Multi-repository trees: the repository of the folder shown at the tree's root.

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Tree entries show M / A (or U for untracked) / D state from `git status`. | Edit a tracked file: its row turns "modified" within 2 s. |
| FR-2 | A folder with changed descendants shows a change dot, also when collapsed. | Collapse the folder of a modified file: the dot remains. |
| FR-3 | Gitignored paths are dimmed. | `node_modules`, `dist` appear dimmed. |
| FR-4 | The editor gutter marks added, modified and removed lines against `HEAD`. | Add, change and delete a line in a tracked file: three marker kinds. |
| FR-5 | Markers follow unsaved edits within 300 ms and reset after Save. | Type a line: marker appears before saving. |
| FR-6 | Outside a repository nothing is drawn and no error shows. | Open a non-git folder: tree and editor look as today. |
| FR-7 | Colours use design tokens (`status-*`, `brand`), not new hues; dark and light themes both readable. | Visual check in both themes. |

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Status is one `git status` per refresh, debounced; never per tree row. | Network of calls: one `git_status` per burst of changes. |
| NFR-2 | A repository with 50k files does not freeze the UI; git runs off the UI thread. | Command runs via `blocking`. |
| NFR-3 | Files over 1 MB or binary skip line markers. | Open a large file: no markers, no lag. |

## 4. Context and constraints

- `git_status` (`src-tauri/src/worktrees.rs` → `evo_worktrees::repo_status`)
  already returns the repo root and `files: FileChange[]` (status, added,
  removed) for the chat summary; the tree can reuse it.
- `git` is run through the CLI (`crates/evo-worktrees`), no libgit2.
- The Files tool reloads changed files on disk (`files-store.ts`); the editor
  is CodeMirror 6 (`code-editor.tsx`), which supports gutters via `@codemirror/view`.
- Rules: the shell provides native features, no agent decisions; git paths from
  untrusted repos are data (argument-passed, never shell-interpolated); the
  Files tool stays read-only for git.

## 5. Design

### 5.1 Overview

```text
files-store ── git_status(cwd) ───────► tree decorations (map path → state)
files-store ── git_file_base(path) ───► HEAD text of the open file
code-editor ── diff(HEAD text, doc) ──► gutter markers (CodeMirror extension)
```

The tree reads a per-root `Map<absolute path, state>` from the store. The
editor gets the file's `HEAD` content once per open/refresh and diffs it
against the live document in the browser, so markers follow typing without
calling git again.

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| crate | `crates/evo-worktrees/src/lib.rs` | `file_at_head(dir, path)` (`git show HEAD:<path>`), `ignored_paths(dir)` (`git ls-files --others --ignored --exclude-standard --directory`). |
| desktop shell | `apps/desktop/src-tauri/src/worktrees.rs` | Commands `git_file_base`, `git_ignored`; `git_status` unchanged. |
| desktop UI | `src/lib/git.ts` | Typed wrappers. |
| desktop UI | `src/features/files/git-state.ts` | Pure: status + ignored list → decorations (file states, folder dots, ignored sets); `rowGit` per row. |
| desktop UI | `src/stores/files-store.ts` | `git` decorations for the tree's folder; `refreshGit` (one read at a time, unchanged results not set again). |
| desktop UI | `src/features/files/files-panel.tsx` | Polling, row letter, folder dot, dimming; `useGitBase` reads the open file's HEAD text. |
| desktop UI | `src/features/files/git-gutter.ts` | Myers line diff; CodeMirror extension: gutter markers, hunk peek. |
| desktop UI | `src/features/files/code-editor.tsx` | Mounts the gutter between line numbers and folding; `gitBase` prop. |
| tests | `apps/desktop/tests/files-git.test.ts` | `bun test`: line diff and tree decorations. |
| desktop UI | `apps/desktop/README.md` | Update the Files row of the UI map. |

### 5.3 Interfaces

```ts
git.fileBase(cwd: string, path: string): Promise<string | null>; // HEAD text; null if untracked, binary, > 1 MB or outside the repo
git.ignored(cwd: string): Promise<string[] | null>;               // absolute, forward slashes, folders end with "/"; null outside a repo
type RowGit = "" | "modified" | "added" | "deleted" | "ignored" | "folder-modified" | "folder-added";
```

Rust: `git_file_base(cwd, path) -> Result<Option<String>, String>`,
`git_ignored(cwd) -> Result<Option<Vec<String>>, String>`. `path` is checked
to lie inside the repository root (no `..` segments). No protocol or engine
change; older shells never see them.

### 5.4 Data and storage

None persistent. In memory: the decorations of the tree's folder, replaced
only when the status or the ignored list changed; the open file's HEAD text in
its view, read again when `head` (from `repo_status`) changes or the file
starts or stops being new.

### 5.5 Behaviour

- Refresh: on opening Files or changing its folder, every 2 s while the window
  is visible, on window focus, and on Refresh (which also re-reads the ignored
  list; otherwise it is re-read every fifth status read). One read runs at a
  time; requests made meanwhile collapse into one follow-up read. This covers
  changes by the agent, the person and other tools alike.
- Tree: a changed file ends with a letter — `M` (`status-warn`), `A` for new
  or untracked (`status-ok`), `D` (`status-error`) — and its tooltip names the
  state. A folder holding changes ends with a dot: green when everything inside
  is new, orange otherwise. Ignored paths are dimmed like build output.
- Editor markers: a local Myers line diff between the HEAD text and the
  document, recomputed 300 ms after the last edit (markers move with the text
  meanwhile). Marker kinds: added (green bar), modified (accent bar), removed
  (small red wedge between lines). Past 2000 edits the changed middle is one
  hunk.
- Clicking a marker shows the hunk's HEAD lines (muted, struck through) under
  it; clicking again, Esc or an edit closes it.
- An untracked or newly added file: every line is "added".
- A deleted file stays out of the tree (it no longer exists); its folders keep
  their dot.

### 5.6 Errors and edge cases

- Not a repository, `git` missing, or command error: decorations are cleared
  and a single log line is written; no toast.
- Merge conflicts: shown as "modified" (no separate letter, see section 10).
- CRLF vs LF only changes: compared after normalising line endings so a
  `.gitattributes` conversion does not mark every line.
- Renames: new path shown as "added", old path not listed.

### 5.7 Security and trust

Read-only git calls with arguments passed as an argv list; `path` canonicalised
and checked to be inside the root; output size capped (1 MB per file). Repo
config such as `core.fsmonitor` or hooks is not executed by `status`/`show`
beyond git's own behaviour; calls use `-c core.fsmonitor=false`.

### 5.8 Configuration

None in the first version. A Settings toggle "Show git changes in Files" may
follow if the status call proves costly (open question 2).

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| libgit2 / `gix` crate | Adds a heavy dependency; the project already shells out to `git`. |
| Diff in Rust per keystroke | A round trip per edit; the browser can diff two strings. |
| Reuse the chat summary's `git_status` result only | It is per chat and refreshed on turn end; Files needs its own root and cadence (it may reuse the command). |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | Tree status colours/letters, folder dots, ignored dimming | `files-store.ts`, `files-panel.tsx`, `git_ignored` | FR-1…3, 6, 7 |
| 2 | Editor gutter markers vs HEAD | `git_file_base`, `git-gutter.ts`, `code-editor.tsx` | FR-4, 5 |
| 3 | Hunk peek of the old text | `git-gutter.ts` | Click marker shows old lines |

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1…3 | `bun test tests/files-git.test.ts` (tree decorations); running app over CDP: `M` on changed files, dots on their folders, green dot on an untracked folder, `node_modules` / `dist` / `.evo` dimmed | pass |
| FR-4, 5 | `bun test` (line diff: add / change / delete / CRLF / fallback / 300 random edits); running app: an unsaved change and deletion show the modified bar and removed wedge within 500 ms; Reload restores the HEAD markers | pass |
| Phase 3 | Running app: clicking the modified marker shows the committed line | pass |
| FR-6 | `cargo test -p evo-worktrees` (`head_text_and_ignored_paths`, non-repo case); running app: `git_status` / `git_ignored` / `git_file_base` return `null` outside a repository, no console errors | pass |
| `file_at_head` | `cargo test -p evo-worktrees` (tracked, relative path, untracked, outside root, `..`) | pass (binary case not covered by a test) |
| FR-7 | Screenshots, dark and light | pass |

## 9. Open questions

Answered as proposed when the SDD was accepted (2026-11-07):

1. Letters in the tree: yes, a right-aligned letter in a status colour.
2. Settings toggle: not in the first version.
3. Peek of old text: yes, in the first release.

## 10. As-built notes

- No `U` letter and no conflict letter `!`: `repo_status` reports untracked
  and staged-new files both as `added`, and unmerged files as `modified` (the
  chat summary reads the same values). Splitting them would change
  `FileChange.status` for every consumer; left for a later change if needed.
- Following `DESIGN.md`, colour stays at indicator scale: the file name stays
  neutral (only the letter is coloured) and the peek is a muted neutral block,
  not a red background.
- The status colours are not CSS variables (`@theme inline`), so the gutter
  markers carry Tailwind classes (`bg-status-ok`, `bg-brand`,
  `border-l-status-error`) instead of `var(--…)` colours.
- Refresh is a 2 s poll (paused while the window is hidden) instead of a file
  watcher: the tree has none, and one `git status` per tick meets FR-1.
- A file outside the tree folder's repository (opened from a link) gets no
  markers; multiple repositories are a non-goal.

## 11. History

- 2026-11-07 — Draft.
- 2026-11-07 — Accepted with the proposed answers; implemented (phases 1–3).
