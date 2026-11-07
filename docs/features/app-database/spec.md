# Application database (`evo.db`) and provider settings — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-store` · engine · desktop shell |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Usage and cost](../usage-and-cost/spec.md), [Subagents and nested sessions](../subagents-and-nested-sessions/spec.md), [Session mesh](../session-mesh-protocol/spec.md) |

## 1. Summary

evo keeps the state the app owns — provider settings and model lists, the
model database, workspaces and chats, preferences, mail between sessions,
usage history and the run log — in one on-device SQLite database, `evo.db`,
and each chat's transcript in a SQLite file of its own. The desktop and every
chat's engine (one process each) read and write it at the same time, so it
needs atomic multi-row writes, concurrent readers and a schema that only
moves forward. Secrets never go in it. This document also fixes how later
features add tables (plan, section 3.4) so they land in the same shape.

## 2. Scope

### 2.1 Goals

- One database file for host-owned application state, safe to use from the
  desktop and several engines at once.
- One transcript file per chat with a single writer, so chats never contend
  for one write lock.
- A schema that migrates forward on open, refuses tampered or newer
  schemas, and keeps old databases upgradable.
- Provider settings and model lists shared by every window, with model facts
  from models.dev only.
- Chat search over transcript text, chat fork and delete that keep
  transcript files and chat rows consistent, and recovery after a crash.
- No secret in the database, so it can be inspected, backed up or attached to
  a bug report.

### 2.2 Non-goals

- Storing secrets: API keys, OAuth tokens and IAM keys stay in `auth.json`
  (moving them to the OS keychain is planned).
- The transcript format itself: the session store owns it; this feature only
  places it in one file per chat.
- The planned tables (model curation, overrides, spend limits, provider
  health, full-text search, …): each arrives with its own feature and
  migration; this document only fixes their shape.

## 3. User scenarios

### US-1 Several windows, one set of settings (priority P1)

A person has several chats open (one engine each) and changes a provider's
settings in one window.

Acceptance scenarios:

1. **Given** two engines running, **when** one writes provider settings or
   the model cache, **then** both see a consistent state, and neither turn
   fails with "database is locked".

### US-2 Upgrade without losing anything (priority P1)

A person installs a newer build over an older one.

Acceptance scenarios:

1. **Given** a database at an older version, **when** the new build opens
   it, **then** pending migrations apply once and existing chats survive.
2. **Given** transcripts an older build kept inside `evo.db`, **when** the
   new build starts, **then** each moves into its own file before any engine
   runs, and nothing is lost if the move is interrupted.
3. **Given** a database written by a newer build, **when** an older build
   opens it, **then** it is refused rather than written.

### US-3 Find, fork and delete chats (priority P2)

A person searches old chats, forks one and deletes another.

Acceptance scenarios:

1. **Given** chats with transcripts, **when** the person searches a word in
   the command palette, **then** chats whose title, preview or text contain it
   are listed, including text written since the last search.
2. **Given** a chat (even a running one), **when** it is forked, **then** the
   fork has its own transcript file with the committed history.
3. **Given** a chat, **when** it is deleted, **then** its row and transcript
   file go; a file Windows still holds open is removed by the next sweep.

### US-4 Inspect data and logs (priority P3)

A person opens **Settings → Data & logs**.

Acceptance scenarios:

1. **Given** the page, **then** it shows the transcripts folder, the files'
   total size and count, and the run log, which can be exported.

### Edge cases

- Opening a SQLite file that is not evo's: refused.
- A migration whose SQL changed after it was applied: refused as tampered;
  a change of line endings only is not a change.
- A crash between moving a legacy transcript into its file and deleting its
  rows: the next start finishes the move; a file that disagrees is set aside
  for the person, not overwritten.
- A transcript file busy past the timeout: the write is retried for up to
  60 s.
- A chat id that is not a safe file name: refused.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Host-owned application state lives in one SQLite file in the agent folder, marked as evo's; opening a foreign SQLite file is refused. Sessions keep their own storage; `evo.db` never holds transcripts written by an engine. | Given a foreign SQLite file at the path, when it is opened, then it is refused. |
| FR-2 | The desktop and several engines use the database at once: concurrent readers, writes as single transactions, and a read-then-write transaction takes the write lock up front so it cannot fail half-way with "database is locked". | Given two processes writing, then neither fails with "database is locked". |
| FR-3 | Opening the database applies pending migrations in order, each once even when two processes open it together; versions are contiguous from 1 and each applied migration is recorded with a checksum of its SQL. A migrated database reopens without taking a write lock. | Given a database at version N-1, when opened, then migration N applies once and the data survives. |
| FR-4 | Migrations are append-only: an applied migration whose SQL changed is refused as tampered, except for a change of line endings; a database at a version this build does not know is refused rather than written by older code. | Given an edited migration or a newer schema, then opening fails with that error. |
| FR-5 | `evo.db` never holds a secret: API keys, OAuth tokens and Bedrock IAM keys stay in `auth.json` (owner-only file, written atomically). | No table or column holds a key or token. |
| FR-6 | Each chat's transcript is a file of its own, written only by that chat's engine; the shell opens files only to read them and removes them once the engine has stopped. A transcript file is stamped as evo's transcript and any other SQLite file is refused; a chat id becomes a file name only when it is 1–128 ASCII letters, digits, `-` or `_`. Two chats' files never share a lock. | Given an unsafe id, then no file is made; given two chats, then their writes do not block each other. |
| FR-7 | Forking a chat copies a snapshot of the source's committed transcript into a new file under the new id before the chat row exists; a failed insert removes the file. The source may be running; a streaming turn's progress is not copied. | Given a running chat, when it is forked, then the fork opens with the committed history. |
| FR-8 | Deleting a chat (or removing a workspace) removes the chat row (its search row with it), stops the chat's engine, then removes the transcript file and its `-wal`, `-shm` and `-journal` companions; a file still open stays for the sweep. | Given a deleted chat, then its file and companions are gone, or swept on the next start. |
| FR-9 | At startup, before any engine runs: transcripts older builds kept in `evo.db` move into their own files one chat at a time (a crash in between is finished on the next start; a file that disagrees is set aside, not overwritten; rows without a chat are dropped; the space is given back once); then files whose chat no longer exists and partial files a crash left are removed (files in use are reported and retried next time). | Given legacy rows, then each chat gets its file and the rows go; given a disagreeing file, then it is kept beside the adopted one. |
| FR-10 | A chat's engine does not start while `evo.db` still holds that chat's transcript and moving it fails, so an engine never starts an empty transcript beside the real one. | Given a failed move, when the engine would start, then it is refused. |
| FR-11 | Chats can be searched by title, preview and transcript text (every string of the transcript except ids, type tags, image data and signatures). A search first re-reads transcripts that changed since they were indexed and drops the text of chats whose file is gone. Substring match. The command palette shows only the latest query's answer. | Given text written after the last search, when searching for it, then the chat is found. |
| FR-12 | Provider settings (enabled, base URL override, non-secret options such as extra headers, a display account, a region) are kept per provider the person touched; models a provider reports are replaced on every refresh, models the person adds are kept; the last discovery attempt per provider is shown on the settings page. Removing a provider removes its models. | Given a refresh, then discovered models are replaced and custom models stay. |
| FR-13 | No model is written in code or in the provider catalog: model facts come from models.dev, revalidated in the background every 6 h or on demand (**Settings → Providers → Refresh**), with provider runtimes swapped live when it changes; a bundled snapshot seeds a machine that has never been online. A provider's live model list decides which models it serves when available; models.dev still supplies their metadata. | Given a changed models.dev document, then providers reload without a restart. |
| FR-14 | Workspaces (folders chats run in), chats (title, preview, model, pinned, unread, archived, totals), preferences shared across windows, mail between sessions, and one usage row per model response are stored in `evo.db`. | Given a chat's lifecycle (create, rename, pin, archive, delete), then the row follows it. |
| FR-15 | The run log keeps entries from the shell, engines, providers, UI and database for 14 days or 50,000 rows, shown in **Settings → Data & logs** and exportable to the agent folder's `logs/`. **Settings → Data & logs** also shows the transcripts folder, the files' total size and count. | Given old entries, then pruning keeps 14 days / 50k rows. |
| FR-16 | The providers in the support matrix (plan, section 3.3) can be configured with the listed sign-in methods; plan usage is shown for Codex, Copilot and OpenCode Go (**Settings → Providers**); discovery reads each provider's model list and drops models without text output or tool calls. FPT (FCI) is deliberately not offered. | Manual check per provider in **Settings → Providers**. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Writes stay fast under streaming: transcript writes do not fsync every streamed frame. | Code review of the connection settings. |
| NFR-2 | Crash safety: no transcript is lost when a move, fork or delete is interrupted; partial files are cleaned up. | Crash-in-the-middle tests for adopt and sweep. |
| NFR-3 | Old databases stay upgradable: every schema change is a new migration with a test that the data survives. | A migration test per version. |
| NFR-4 | The database file works on every platform checkout: a migration's checksum matches its SQL with LF or CRLF line endings. | `line_endings_do_not_change_a_migration`. |

## 5. Success criteria

- SC-1 Several chats can stream at the same time without a turn failing on a
  locked database.
- SC-2 Upgrading the app never loses a chat or a transcript.
- SC-3 The database can be attached to a bug report without exposing a
  secret.
- SC-4 A word typed in a chat a moment ago is found by chat search.

## 6. Clarifications

### 6.1 Open

n/a — no open questions are recorded; planned tables are listed in the plan
(section 3.4) and the tasks (Phase 6).

### 6.2 Resolved

- 2026-11-06 — Q: One database for transcripts or one file per chat? → A:
  one transcript file per chat
  ([ADR 0007](../../architecture/decisions/0007-one-transcript-file-per-chat.md));
  now FR-6 – FR-10.
- 2026-11-06 — Q: Where do model facts come from? → A: models.dev only
  ([ADR 0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md));
  now FR-13.

## 7. History

- 2026-11-06 — Design recorded: provider settings, models.dev cache,
  workspaces, chats, logs; read-then-write transactions take the write lock
  up front ("database is locked" under load).
- 2026-11-06 — Schema v9 (chat parents, chat worktrees, mail, chat search,
  usage history) with one transcript file per chat.
- 2026-11-07 — Moved to the spec / plan / tasks format.
