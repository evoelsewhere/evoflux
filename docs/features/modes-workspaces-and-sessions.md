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

Coding requires an authorized filesystem repository or a Coding project.

- A **workspace** is one persistent repository path and its optional managed
  worktrees.
- A **project** is a durable named set of authorized repositories with ordering,
  display names and visibility.
- A **focus ID** in the URL identifies the workspace path or project before a
  chat session is selected.
- A **Coding session** persists its owning workspace/project so reconnect and
  scheduled tasks cannot silently retarget another repository.

The default team favors coding, exploration, architecture and debate. Coding
adds repository tree/editor, Git, code context, language-server, Problems,
ChangeSet and code-review surfaces.

Workspace authorization rejects missing/non-directory paths, traversal and
project members outside the configured set. Multi-repository operations receive
only the project repositories relevant to their contract.

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
- undo/revert and redo across snapshot-backed boundaries;
- queue, edit or cancel input while a turn is running;
- delete a session and cascade child records/artifacts;
- purge a Coding workspace only through conflict-aware ownership checks.

Session deletion first invalidates in-memory team construction, then stops live
teams and removes durable state so a concurrent cold build cannot resurrect the
session.

## Navigation and state restoration

The frontend remembers the last Work and Coding routes separately. Work routes
are `/` and `/:sessionId`; Coding routes are `/coding/:focusId/:sessionId?`.
Legacy bare Coding session URLs are resolved through the session API when they
do not identify a current workspace/project.

The session history endpoint returns the lead transcript, specialist
transcripts, goal and live workflow projection. Cursor pagination keeps long
history bounded. The live SSE stream then layers current activity over the
durable replay.

## Primary interfaces

- `/api/team/chat`, `/api/team/commands`, session CRUD/history/stream routes
- `/api/team/session-folders`
- `/api/team/projects` and project workspace membership routes
- `/api/team/workspace/*` validation, visibility, tree and worktree routes
- React route tree, Work/Coding sidebars and `TeamChatView`

## Source and tests

Primary code: `app/models/chat.py`, `app/api/routes/team/chat.py`,
`app/api/routes/team/folders.py`, `app/api/routes/team/projects.py`,
`app/services/chat_service.py`, `app/services/coding_*`, `web/src/router.ts`.

Focused coverage: team/session/folder/worktree/project API tests, chat and
snapshot service tests, route restoration tests, and Coding sidebar/workspace
component tests.
