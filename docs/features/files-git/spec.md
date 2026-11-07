# Git in the Files tool — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-worktrees`, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Subagents and nested sessions](../subagents-and-nested-sessions/spec.md) |

## 1. Summary

Without this feature the Files tool (Ctrl+F) knows nothing about git: the tree
and the editor look the same for a clean and a dirty repository. The feature
marks changed files in the tree (colour and a status letter, like other
editors) and marks the changed lines of the open file in the editor gutter,
so the person sees what the agent or they changed without leaving Files.

## 2. Scope

### 2.1 Goals

- Tree: files that are modified, added/untracked or deleted get a status
  colour and letter; folders containing changes get a dot; ignored files are
  dimmed.
- Editor: a gutter marker per changed line against `HEAD` (added, modified,
  deleted-above), updated as the person types and when the file changes on
  disk.
- Clicking a gutter marker shows the old text of that hunk (read-only peek).
- Refreshes by itself when files change, without a manual button.

### 2.2 Non-goals

- Staging, committing, discarding hunks or any write to the repository. Files
  stays read-only with respect to git.
- A full diff view or blame (a later feature).
- Multi-repository trees: only the repository of the folder shown at the
  tree's root counts. A file outside it (opened from a link) gets no markers.

## 3. User scenarios

### US-1 See which files changed (priority P1)

A person working with the agent wants the Files tree to show which files are
modified, new or deleted so that they see what changed without leaving Files.

Acceptance scenarios:

1. **Given** a repository open in Files, **when** a tracked file is edited
   (by the agent, the person or another tool), **then** its row ends with `M`
   within 2 s, with no manual refresh.
2. **Given** a modified file inside a folder, **when** the folder is
   collapsed, **then** the folder still shows a change dot.
3. **Given** a repository with ignored build output, **when** the tree shows
   it, **then** `node_modules` and `dist` are dimmed.

### US-2 See which lines changed in the open file (priority P1)

A person reading or editing a file wants the changed lines marked against the
last commit so that they see what the agent or they changed in it.

Acceptance scenarios:

1. **Given** a tracked file open in the editor, **when** the person adds,
   changes and deletes a line, **then** three different marker kinds appear.
2. **Given** an unsaved edit, **when** the person stops typing, **then** the
   marker appears before saving, and after Save the markers match the saved
   file.

### US-3 Peek at the committed text (priority P2)

A person looking at a changed line wants to see what it was before so that
they can judge the change without a diff tool.

Acceptance scenarios:

1. **Given** a modified line, **when** the person clicks its marker, **then**
   the committed lines show read-only under it; clicking again, Esc or an
   edit closes the peek.

### US-4 Work in a folder that is not a repository (priority P2)

A person opening Files on a folder without git wants it to look and behave
as before, with no errors.

Acceptance scenarios:

1. **Given** a folder that is not a git repository, **when** Files opens it,
   **then** the tree and the editor show no git decorations and no error.

### Edge cases

- An untracked or newly added file: every line is "added".
- A deleted file is not in the tree (it no longer exists); its folders keep
  their dot.
- Merge conflicts show as "modified".
- A rename shows the new path as "added"; the old path is not listed.
- A change that only converts line endings (CRLF vs LF) marks no lines.
- Files over 1 MB or binary get no line markers.
- `git` missing or failing: decorations are cleared, no toast.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Tree entries show M / A / D state from `git status`; untracked files show as A. | Edit a tracked file: its row turns "modified" within 2 s. |
| FR-2 | A folder with changed descendants shows a change dot, also when collapsed. | Collapse the folder of a modified file: the dot remains. |
| FR-3 | Gitignored paths are dimmed. | `node_modules`, `dist` appear dimmed. |
| FR-4 | The editor gutter marks added, modified and removed lines against `HEAD`. | Add, change and delete a line in a tracked file: three marker kinds. |
| FR-5 | Markers follow unsaved edits within 300 ms and reset after Save. | Type a line: marker appears before saving. |
| FR-6 | Outside a repository nothing is drawn and no error shows. | Open a non-git folder: tree and editor look as they do without this feature. |
| FR-7 | Colours use design tokens (`status-*`, `brand`), not new hues; dark and light themes both readable. | Visual check in both themes. |
| FR-8 | Clicking a gutter marker shows the hunk's `HEAD` text read-only under it. | Click the marker of a modified line: the committed line shows. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Status is one `git status` per refresh, debounced; never per tree row. | Watch the calls: one status read per burst of changes. |
| NFR-2 | A repository with 50k files does not freeze the UI; git runs off the UI thread. | Git commands run on a background thread, not the UI thread. |
| NFR-3 | Files over 1 MB or binary skip line markers. | Open a large file: no markers, no lag. |

## 5. Success criteria

- SC-1 A file changed by the agent, the person or another tool shows as
  changed in the tree within 2 s, without pressing anything.
- SC-2 A typed change shows its line marker in well under a second, before
  the file is saved.
- SC-3 Browsing a large repository (50k files) stays responsive.
- SC-4 A folder that is not a repository looks exactly as it did before the
  feature.

## 6. Clarifications

### 6.1 Open

n/a — no open questions.

### 6.2 Resolved

- 2026-11-07 — Q: Letters in the tree? → A: Yes, a right-aligned letter in a
  status colour (FR-1).
- 2026-11-07 — Q: A Settings toggle "Show git changes in Files"? → A: Not in
  the first version; it may follow if the status call proves costly.
- 2026-11-07 — Q: Peek of the old text in the first release? → A: Yes
  (FR-8).
- 2026-11-07 — Q: Separate letters for untracked (`U`) and conflicted (`!`)
  files? → A: No; untracked files show as `A` and conflicts as modified, as
  the chat summary reports them (FR-1; plan section 5).

## 7. History

- 2026-11-07 — Draft.
- 2026-11-07 — Accepted with the proposed answers; implemented (phases 1–3).
- 2026-11-07 — Moved to the spec / plan / tasks format. FR-1 now states that
  untracked files show as A (as built); the hunk peek goal got its own ID,
  FR-8.
