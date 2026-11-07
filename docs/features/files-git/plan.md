# Git in the Files tool — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [Desktop app](../../architecture/README.md) |
| ADRs | none |

## 1. Context and constraints

- `git_status` (`apps/desktop/src-tauri/src/worktrees.rs` →
  `evo_worktrees::repo_status`) already returns the repo root and
  `files: FileChange[]` (status, added, removed) for the chat summary; the
  tree can reuse it. `repo_status` and `FileChange` are shared with
  [Subagents and nested sessions](../subagents-and-nested-sessions/plan.md).
- `git` is run through the CLI (`crates/evo-worktrees`), no libgit2.
- The Files tool reloads changed files on disk
  (`apps/desktop/src/stores/files-store.ts`); the editor is CodeMirror 6
  (`apps/desktop/src/features/files/code-editor.tsx`), which supports gutters
  via `@codemirror/view`.
- Rules: the shell provides native features, no agent decisions; git paths
  from untrusted repos are data (argument-passed, never
  shell-interpolated); the Files tool stays read-only for git.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Git reads are a native shell feature; no agent decisions in the shell. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | The git helpers live in `evo-worktrees` and know nothing of the desktop. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | n/a | No protocol or engine change; only shell commands. |
| Models come from models.dev; no hardcoded model facts | n/a | No model data. |
| Real engine in the app; settings and credentials reload live | n/a | No engine involvement and no settings. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Read-only git calls, argv-passed paths checked to be inside the root, output capped, `core.fsmonitor` disabled (3.7). |
| Desktop UI structure and `DESIGN.md` | ok | Tree state lives in `files-store`; colours use existing tokens at indicator scale (section 5). |

## 3. Design

### 3.1 Overview

```text
files-store ── git_status(cwd) ───────► tree decorations (map path → state)
files-store ── git_file_base(path) ───► HEAD text of the open file
code-editor ── diff(HEAD text, doc) ──► gutter markers (CodeMirror extension)
```

The tree reads a per-root `Map<absolute path, state>` from the store. The
editor gets the file's `HEAD` content once per open/refresh and diffs it
against the live document in the browser, so markers follow typing without
calling git again.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-worktrees/src/lib.rs` | `file_at_head(dir, path)` (`git show HEAD:<path>`), `ignored_paths(dir)` (`git ls-files --others --ignored --exclude-standard --directory`). | FR-3, FR-4, FR-6, NFR-3 |
| desktop shell | `apps/desktop/src-tauri/src/worktrees.rs` | Commands `git_file_base`, `git_ignored`; `git_status` unchanged. | FR-1, FR-3, FR-4, FR-6, NFR-2 |
| desktop UI | `apps/desktop/src/lib/git.ts` | Typed wrappers. | FR-1, FR-3, FR-4 |
| desktop UI | `apps/desktop/src/features/files/git-state.ts` | Pure: status + ignored list → decorations (file states, folder dots, ignored sets); `rowGit` per row. | FR-1, FR-2, FR-3 |
| desktop UI | `apps/desktop/src/stores/files-store.ts` | `git` decorations for the tree's folder; `refreshGit` (one read at a time, unchanged results not set again). | FR-1, FR-2, FR-6, NFR-1 |
| desktop UI | `apps/desktop/src/features/files/files-panel.tsx` | Polling, row letter, folder dot, dimming; `useGitBase` reads the open file's HEAD text. | FR-1, FR-2, FR-3, FR-4, FR-7 |
| desktop UI | `apps/desktop/src/features/files/git-gutter.ts` | Myers line diff; CodeMirror extension: gutter markers, hunk peek. | FR-4, FR-5, FR-7, FR-8 |
| desktop UI | `apps/desktop/src/features/files/code-editor.tsx` | Mounts the gutter between line numbers and folding; `gitBase` prop. | FR-4 |
| tests | `apps/desktop/tests/files-git.test.ts` | `bun test`: line diff and tree decorations. | FR-1, FR-2, FR-3, FR-4, FR-5 |
| desktop UI | `apps/desktop/README.md` | The Files row of the UI map describes the git decorations. | — |

### 3.3 Interfaces

```ts
git.fileBase(cwd: string, path: string): Promise<string | null>; // HEAD text; null if untracked, binary, > 1 MB or outside the repo
git.ignored(cwd: string): Promise<string[] | null>;               // absolute, forward slashes, folders end with "/"; null outside a repo
type RowGit = "" | "modified" | "added" | "deleted" | "ignored" | "folder-modified" | "folder-added";
```

Rust: `git_file_base(cwd, path) -> Result<Option<String>, String>`,
`git_ignored(cwd) -> Result<Option<Vec<String>>, String>`. `path` is checked
to lie inside the repository root (no `..` segments). No protocol or engine
change; older shells never see them.

### 3.4 Data and storage

None persistent. In memory: the decorations of the tree's folder, replaced
only when the status or the ignored list changed; the open file's HEAD text
in its view, read again when `head` (from `repo_status`) changes or the file
starts or stops being new.

### 3.5 Behaviour

- Refresh: on opening Files or changing its folder, every 2 s while the
  window is visible, on window focus, and on Refresh (which also re-reads the
  ignored list; otherwise it is re-read every fifth status read). One read
  runs at a time; requests made meanwhile collapse into one follow-up read.
  This covers changes by the agent, the person and other tools alike.
- Tree: a changed file ends with a letter — `M` (`status-warn`), `A` for new
  or untracked (`status-ok`), `D` (`status-error`) — and its tooltip names
  the state. A folder holding changes ends with a dot: green when everything
  inside is new, orange otherwise. Ignored paths are dimmed like build
  output.
- Editor markers: a local Myers line diff between the HEAD text and the
  document, recomputed 300 ms after the last edit (markers move with the text
  meanwhile). Marker kinds: added (green bar), modified (accent bar), removed
  (small red wedge between lines). Past 2000 edits the changed middle is one
  hunk.
- Clicking a marker shows the hunk's HEAD lines (muted, struck through) under
  it; clicking again, Esc or an edit closes it.
- An untracked or newly added file: every line is "added".
- A deleted file stays out of the tree (it no longer exists); its folders
  keep their dot.

### 3.6 Errors and edge cases

- Not a repository, `git` missing, or command error: decorations are cleared
  and a single log line is written; no toast.
- Merge conflicts: shown as "modified" (no separate letter, see section 5).
- CRLF vs LF only changes: compared after normalising line endings so a
  `.gitattributes` conversion does not mark every line.
- Renames: new path shown as "added", old path not listed.

### 3.7 Security and trust

Read-only git calls with arguments passed as an argv list; `path`
canonicalised and checked to be inside the root; output size capped (1 MB per
file). Repo config such as `core.fsmonitor` or hooks is not executed by
`status`/`show` beyond git's own behaviour; calls use
`-c core.fsmonitor=false`.

### 3.8 Configuration

None in the first version. A Settings toggle "Show git changes in Files" may
follow if the status call proves costly (spec section 6.2).

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| libgit2 / `gix` crate | Adds a heavy dependency; the project already shells out to `git`. |
| Diff in Rust per keystroke | A round trip per edit; the browser can diff two strings. |
| Reuse the chat summary's `git_status` result only | It is per chat and refreshed on turn end; Files needs its own root and cadence (it may reuse the command). |

## 5. As-built notes

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
