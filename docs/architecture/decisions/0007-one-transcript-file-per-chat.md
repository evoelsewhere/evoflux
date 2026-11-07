# 0007. Each chat's transcript is a SQLite file of its own, written only by that chat's engine

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-06 |
| ADD sections | [4. Process view](../README.md#4-process-view), [7. Data view](../README.md#7-data-view) |
| Related | [0003](0003-engine-runs-as-a-child-process-per-chat.md), [App database spec](../../features/app-database/spec.md), [Session mesh spec](../../features/session-mesh-protocol/spec.md) |

## Context

- `~/.evo/agent/evo.db` (SQLite, WAL) held both the app's data (chats,
  workspaces, settings, run log, mail, provider settings, models.dev cache)
  and every session's transcript and progress frames. The shell and every
  engine (one per open chat, [ADR 0003](0003-engine-runs-as-a-child-process-per-chat.md))
  opened it with `--session-db evo.db` and wrote to it.
- Engines write the most: history entries and progress frames while a turn
  streams. Their other writes to `evo.db` are rare: provider settings the
  person changes and the models.dev cache, refreshed every few hours
  (`crates/evo-engine/src/provider_settings.rs`, `models_dev.rs`).
- SQLite lets one writer at a time into a database file. When many engines
  start or stream at once, the busy handler gives up with "database is
  locked"; `crates/evo-harness/src/session/sqlite/busy.rs` retries operations
  for up to 60 seconds with backoff so a turn does not fail.
- The writers queued behind each other although they never touch the same
  rows: a chat's transcript has exactly one writer, the engine running that
  chat. The contention came from sharing a file, not from the data.
- evo-harness's `SqliteSessionRepo` (one `sessions` row with the reducer
  snapshot, plus progress tables) works on any SQLite file. The experimental
  native store also keeps one file per session, but serves only fresh
  `--print` runs behind a build feature.
- Constraints: storage is local, needs no install and stays small; the app is
  desktop only ([ADR 0001](0001-desktop-app-is-the-only-front-end.md)).

## Decision

We stay on SQLite and give each chat's transcript a file of its own, written
only by the engine running that chat.

- **One transcript file per chat**:
  `~/.evo/agent/transcripts/<chat id>.db`. The shell starts a chat's engine
  with `--session-db <that file>`; the engine keeps the session there through
  the existing `SqliteSessionRepo`. Chat ids become file names only when they
  are ASCII letters, digits, `-` and `_` (they are UUIDs).
- **Identity:** a transcript file carries `application_id` "evoT" (`evo.db` is
  "evo1"). The engine refuses any other SQLite file; `evo.db` itself is still
  accepted for `--session-db`, as older desktops passed it.
- **The shell only reads transcript files** (search, fork) and removes them
  with their chat, after stopping the chat's engine. It never writes into a
  file another process has open; a fork is a new file built beside the target
  and renamed into place.
- **Search** cannot join transcripts any more. `evo.db` keeps each chat's
  searchable text (`chat_search`, migration 7) with a fingerprint of the file
  it was read from (size and modification time of the file and its WAL). A
  search first re-reads the transcripts whose fingerprint changed, so results
  are never stale and nothing needs to watch the engines.
- **Moving old data:** at startup, before any engine runs, the shell moves
  transcripts older builds kept in `evo.db` into their own files, one chat at
  a time: write the file, flush it, rename it into place, then delete the
  rows. A chat whose transcript is still in `evo.db` is refused an engine, so
  no engine ever starts an empty transcript beside the real one.
- **The engines' rare writes to `evo.db` stay direct**, each in a
  `BEGIN IMMEDIATE` transaction with the busy timeout; reads need no lock
  (WAL).
- **SQLite settings stay:** bundled `rusqlite`, WAL, `synchronous = NORMAL`,
  short transactions.

## Consequences

- Engines never wait on another engine's write lock for their transcript;
  the busy retry loop remains a safety net for `evo.db`.
- Backing up, inspecting or deleting one chat is one file. Deleting a chat
  stops its engine and removes its file; a file still in use (Windows refuses
  to delete it) is removed by the sweep at the next startup, which also drops
  the files of drafts that never got a prompt and partial files a crash left.
- Search reads only the transcripts that changed since the last search; the
  search text duplicates the transcripts' words (not images or signatures)
  inside `evo.db`.
- `evo.db` keeps its now-empty `sessions` and `progress_*` tables: dropping
  them in a migration could lose a transcript the move had not reached.
- Settings → Data & logs shows the transcripts folder, its size and file count.

## Trade-offs

What changed compared with one shared `evo.db`:

| Aspect | Before: one `evo.db` | After: one file per chat | Net |
| --- | --- | --- | --- |
| Many chats writing at once | engines queue on one write lock; bursts retry for up to 60 s | each engine writes its own file; no waiting | gain (the reason for this ADR) |
| Deleting a chat or workspace | one transaction removed the chat and its transcript | a row in `evo.db`, then the file once the engine stopped; not atomic, the startup sweep removes what a crash or a busy file left | cost: cleanup code |
| Forking a chat | one `INSERT … SELECT` | a new file built from a snapshot of the source, renamed into place, then the chat row | cost: more code, same behaviour |
| Searching chat content | `LIKE` over every `state_json` | `LIKE` over `chat_search`, refreshed from changed files first | cost: a second copy of the text; gain: identifiers, image data and signatures no longer match |
| Consistency after a crash | one file and one WAL always agree | the search text follows the files' fingerprints, so it heals by itself; a moved transcript is never deleted from `evo.db` before its file is complete | neutral |
| Engine writes to app data | direct | direct, `BEGIN IMMEDIATE` | unchanged |
| Backup, export, delete one chat | extract from the shared database | one file | gain |
| Corruption | a damaged `evo.db` lost every chat | a damaged file loses one chat | gain |
| Files and handles | one file | one plus one per chat; one more connection per open chat | neutral for a desktop app |
| Debugging by hand | one database shows everything | find the chat's file by its id | neutral |

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep one `evo.db`, longer busy timeouts and more retries | hides the contention; turns still stall during bursts |
| The shell writes everything, transcripts included | every streamed frame crosses the protocol twice; one process becomes the bottleneck for every chat's durability |
| Route the engines' provider-settings and models.dev writes through the shell too | rare writes that never caused the contention; it would add protocol requests and a second path for engines without a shell |
| Promote the experimental native store now | serves only fresh `--print` runs today; the existing `SqliteSessionRepo` already works per file |
| JSONL file per session | a full scan on every open; checkpoints, indexes and torn-write handling written by hand; no atomic multi-record writes |
| Embedded PostgreSQL | real concurrent writers, but a server process to start, stop and recover, major-version upgrades on users' machines, and a rewrite of storage and tests |
| Turso Database or SQLite `BEGIN CONCURRENT` | still experimental; support for several processes on one file is unproven |
| LMDB or redb | key-value without SQL; redb allows one process per file; both still have a single writer |
| FTS5 search index | changes match semantics (tokens instead of substrings) and needs a tokenizer the bundled SQLite may not build; `LIKE` over the stored text keeps today's behaviour |
