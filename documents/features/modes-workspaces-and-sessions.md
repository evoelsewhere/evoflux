# Modes, workspaces, and sessions

EvoFlux uses one harness with two execution modes. Mode is durable session
state, not a cosmetic UI toggle, because it changes workspace authorization,
default specialists, tools, verification and navigation.

## Work mode

Work starts from an outcome and gives the session an isolated workspace under
the EvoFlux workspace root. Uploads, generated files and quick scripts live in
that session root. The default team favors execution, exploration, consulting
and debate without requiring a repository.

Work sessions can be organized into user-created folders. A folder may share a
bounded sibling-session digest with the lead; the sessions keep independent
history, models, goals and workspaces. Pinning is client-local, while folder,
title, tags and session metadata are persisted.

## Coding mode

Coding is project-only: every Coding session, scheduled task and worktree
belongs to a Coding project.

- A **project** is a durable named set of one or more authorized repositories
  with ordering, display names and visibility. Opening (or cloning) a folder
  from the Coding sidebar creates a single-repository project named after it;
  a folder some project already owns opens that project instead. Multi-repo
  projects are set up in the project wizard, and repositories can be added to
  or removed from any project later.
- A **repository** is one persistent path in the repository registry, with its
  optional managed worktrees. It is opened only through a project that owns
  it; a worktree belongs to its source repository's project.
- A **focus ID** in the URL is the project id, set before a chat session is
  selected. A folder path from an old bookmark is sent back to `/coding`.
- A **Coding session** persists its owning project and its primary repository
  (the project's first repository, or a worktree of one) so reconnect and
  scheduled tasks cannot silently retarget another repository.

Coding sessions and Coding scheduled tasks with no project — left over from the
standalone workspaces earlier versions had — are handled at startup: one whose
repository (or a worktree's source repository) belongs to exactly one project
is filed under it, and the rest are deleted together with their sub-sessions,
side chats and generated files. Rows created after startup are left alone, and
the scheduler never fires a Coding task with no project. Repository sources are
never touched.

The default team favors coding, exploration, architecture and debate. Coding
adds repository tree/editor, Git, language-server, Problems,
ChangeSet and code-review surfaces.

Workspace authorization rejects missing/non-directory paths, traversal and
project members outside the configured set. A new Coding session is refused
(`422`) unless its repository belongs to the named project, or — when no
project is named — to exactly one project. Multi-repository operations receive
only the project repositories relevant to their contract.

A Coding session's agents may write to its primary repository and to the
project's other repositories. When the primary repository is a managed
worktree, the checkout it was made from is read-only to that session, so the
worktree keeps the session's edits isolated.

## Session lifecycle

A top-level `ChatSession` belongs to the lead. Specialist sessions reference it
through `parent_session_id`; Side Chat also uses a child session with source
metadata. Sessions persist mode, workspace/project, agent/model overrides,
permission mode, title, tags, folder, revert boundaries, scheduling provenance
and timestamps.

Supported user lifecycle actions include:

- create/resolve, rename and tag;
- pin locally and group Work sessions into folders;
- duplicate a top-level session and its visible conversation state;
- undo/revert and redo across snapshot-backed boundaries — in a
  multi-repository project, each turn snapshots every repository the session
  may write to, so undo and redo cover them all;
- queue, edit or cancel input while a turn is running;
- delete a session and cascade child records/artifacts;
- delete a Coding project, or remove a repository from one, which purges the
  project sessions that could reach it.

Session deletion first invalidates in-memory team construction, then stops live
teams and removes durable state so a concurrent cold build cannot resurrect the
session.

## Navigation and state restoration

The frontend remembers the last Work and Coding routes separately. Work routes
are `/` and `/:sessionId`; Coding routes are `/coding/:focusId/:sessionId?`.
Legacy bare Coding session URLs are resolved through the session API when they
do not identify a current project.

The session history endpoint returns the lead transcript, specialist
transcripts and goal projection. Cursor pagination keeps long
history bounded. The live SSE stream then layers current activity over the
durable replay.

The primary transcript starts with a bounded 72-turn render window and reveals
older loaded content in 24-turn batches. Earlier server history begins loading
while the reader is still at least three viewport heights (and no less than
1600px) from the top. A short initial transcript primes one older page after
mount, so network latency is normally paid before fast upward scrolling reaches
the history control. Every prepend restores the visible turn anchor.

## Primary interfaces

- `/api/team/chat`, `/api/team/commands`, session CRUD/history/stream routes
- `/api/team/session-folders`
- `/api/team/projects` and project workspace membership routes
- `/api/team/workspace/*` validation, browse, tree and worktree routes
- React route tree, Work/Coding sidebars and `TeamChatView`

## Source and tests

Primary code: `app/models/chat.py`, `app/api/routes/team/chat.py`,
`app/api/routes/team/folders.py`, `app/api/routes/team/projects.py`,
`app/services/chat_service.py`, `app/services/coding_*`, `web/src/router.ts`.

Focused coverage: team/session/folder/worktree/project API tests, chat and
snapshot service tests, route restoration tests, and Coding sidebar/workspace
component tests.
