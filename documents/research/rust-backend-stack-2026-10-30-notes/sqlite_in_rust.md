# SQLite in Rust for EvoFlux (local-first desktop backend, incl. BEGIN CONCURRENT)

Research date: 2026-10-30. Some sources are 2024-2025 and are flagged where relevant. Items marked "(from prior knowledge, unverified)" were not confirmed by a fetched source in this session.

## Q1. Which crate: rusqlite vs sqlx vs diesel vs sea-orm vs others

### Takeaway
rusqlite (sync, thin, on libsqlite3-sys) is the best fit: it is the most direct way to link a custom SQLite build (such as a begin-concurrent amalgamation), it is what Zed's own wrapper is built on, and it lets EvoFlux keep its explicit single-writer design. sqlx 0.9 is the main async alternative and gives compile-time-checked SQL, but it shares the same libsqlite3-sys link and adds its own pooling and worker threads, which a strict FIFO writer does not need. Diesel and SeaORM add ORM layers with no benefit for a schema inherited from Alembic.

### Cited Findings
- Latest libsqlite3-sys is 0.39.1 (released 2026-10-25). It bundles SQLite 3.54.0 (as of rusqlite 0.41.0 / libsqlite3-sys 0.39.0), and the base package supports SQLite 3.45.3 or newer — [docs.rs libsqlite3-sys](https://docs.rs/crate/libsqlite3-sys/latest). An earlier search snapshot showed rusqlite 0.40.1 / libsqlite3-sys 0.38.1 bundling 3.53.2 and libsqlite3-sys 0.37.0 published 2026-03-15, so releases are frequent — [ecosyste.ms](https://packages.ecosyste.ms/api/v1/registries/crates.io/packages/libsqlite3-sys).
- libsqlite3-sys features: `bundled`, `bundled-full`, `sqlcipher`, `bundled-sqlcipher`, `bundled-sqlcipher-vendored-openssl`, `buildtime_bindgen`, `modern_sqlite`, plus runtime API features: `hooks`, `preupdate_hook`, `unlock_notify`, `serialize`, `session`, `backup`, `blob`, `functions`, `window`, `uuid`, `serde_json`, `chrono`, `time`, `jiff` — [docs.rs libsqlite3-sys](https://docs.rs/crate/libsqlite3-sys/latest).
- Ways to link a custom SQLite: `SQLITE3_LIB_DIR` and `SQLITE3_INCLUDE_DIR` (point at your own built library and `sqlite3.h`), `SQLITE3_STATIC=1` for static linking, `LIBSQLITE3_FLAGS` to set or unset compile flags in bundled builds (with an optional `-D`/`-U` prefix), and `VCPKGRS_DYNAMIC=1` for vcpkg on MSVC — [docs.rs libsqlite3-sys](https://docs.rs/crate/libsqlite3-sys/latest). The docs page does not describe swapping in a custom amalgamation under `bundled`.
- sqlx 0.9.0 was released around 2026-05-06, and the repo was moving to the `transact-rs` GitHub org. SQLite changes in 0.9: libsqlite3-sys is now a version range, extension loading is `unsafe`, and there are new optional features `sqlite-deserialize`, `sqlite-load-extension` and `sqlite-unlock-notify`. MSRV is 1.94.0 — [SQLx 0.9.0 discussion](https://gh.r-mj.com/transact-rs/sqlx/discussions/4271); [tauri-plugin-sqlite PR](https://github.com/silvermine/tauri-plugin-sqlite/pull/48). One conflicting May-4-2026 PR comment says no stable 0.9 existed yet; it predates the release.
- Diesel 2.3.12 was last updated 2026-08-07. 2.3.0 added SQLite JSON/JSONB support, wasm32-unknown-unknown for the SQLite backend, and batch insert/upsert with RETURNING for SQLite — [crates.io diesel](https://crates.io/api/v1/crates/diesel/versions); [diesel 2.3.0 changelog](https://diesel.rs/changelog/version/diesel-2-3-0/).
- SeaORM 2.0 was still at release candidates (2.0.0-rc.29 seen) and includes a `sea-orm-sync` variant for SQLite CLI programs; no stable 2.0 was found — [sea-orm rc.29 README](https://docs.rs/crate/sea-orm/2.0.0-rc.29/source/README.md); [SeaQL sneak peek](https://dev.to/seaql/a-sneak-peek-at-seaorm-20-3473).
- Atuin's workspace pins `sqlx = "0.9"` (runtime-tokio, time, uuid) and also `rusqlite = "0.32"` (unlock_notify), with `libsqlite3-sys = ">=0.30.1, <0.38.0"` — [Atuin Cargo.toml](https://raw.githubusercontent.com/atuinsh/atuin/main/Cargo.toml).
- Other crates exist, for example `sqll`, a rewrite of the `sqlite` crate — [sqll README](https://docs.rs/crate/sqll/0.14.3/source/src/lib.rs).

### Inferences
- Every mainstream option (rusqlite, sqlx-sqlite, diesel's sqlite backend through libsqlite3-sys, sea-orm through sqlx) ends at libsqlite3-sys. So the custom-build question is the same for all of them: build a begin-concurrent `libsqlite3` and point `SQLITE3_LIB_DIR`/`SQLITE3_INCLUDE_DIR` at it (with `SQLITE3_STATIC=1`), or vendor a patched libsqlite3-sys whose `sqlite3/` directory holds the branch amalgamation. Cargo allows only one crate linking `sqlite3` per binary, so every crate in the graph must agree on one libsqlite3-sys version. Atuin's explicit range pin shows this happening in practice.
- rusqlite exposes raw handles and extended error codes, so code can match `SQLITE_BUSY_SNAPSHOT` and retry. sqlx's error abstraction also exposes the code but makes it harder to control which connection runs a transaction.
- sqlx's compile-time `query!` checks need a database or offline `.sqlx` metadata at build time. With 53+ Alembic revisions, that means keeping a schema snapshot DB in CI. This is a real cost but workable.
- Async is not a reason to choose sqlx: SQLite calls are blocking file I/O, and sqlx-sqlite itself runs each connection on a worker thread (prior knowledge, unverified).

### Gaps
- Exact rusqlite 0.41.0 release date and crates.io download stats were not fetched.
- I did not verify whether sqlx 0.9 exposes `SQLITE_BUSY_SNAPSHOT` distinctly or how it handles `BEGIN CONCURRENT` (its transaction API issues plain `BEGIN`, so custom SQL would be needed).
- No benchmark comparing rusqlite and sqlx-sqlite was found this session.

## Q2. Connection pooling and single-writer patterns

### Takeaway
The Rust version of EvoFlux's current design is one dedicated writer thread that owns a rusqlite `Connection` and takes closures over a bounded mpsc channel (FIFO, with the 5 s admission timeout as a `send_timeout`/oneshot deadline), plus a small read pool of `query_only` connections (deadpool-sqlite, r2d2_sqlite, or a hand-rolled pool). Existing crates (deadpool-sqlite, async-sqlite, tokio-rusqlite) provide these pieces but do not enforce single-writer semantics on their own.

### Cited Findings
- deadpool-sqlite (0.13.0 latest seen) is a deadpool manager for rusqlite. It runs each connection on a separate thread, you call it through `interact()`, and its tests cover recovery after a callback panics — [deadpool-sqlite docs](https://docs.rs/deadpool-sqlite); [tests](https://docs.rs/crate/deadpool-sqlite/latest/source/tests/sqlite.rs).
- async-sqlite offers a `Client` (one connection on a background thread) and a `Pool`. File-backed pools default to the logical CPU count, and it is tested on tokio and smol — [async-sqlite docs](https://docs.rs/async-sqlite).
- Zed's `sqlez` crate is an in-house wrapper over `libsqlite3-sys` (with `thread_local`, `parking_lot`, `futures`), not rusqlite or sqlx — [Zed sqlez Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/crates/sqlez/Cargo.toml).
- The BEGIN CONCURRENT doc itself recommends an application-level mutex or similar so only one writer commits at a time under heavy contention, and notes this is easier when all writers are in one process — [begin_concurrent.md](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md).

### Inferences
- Recommended layout:
  - Writer: `std::thread` owning `Connection`, receiving `Box<dyn FnOnce(&mut Connection) -> R + Send>` with a `tokio::sync::oneshot` reply.
  - Reads: N connections opened with `PRAGMA query_only=ON`, run through `spawn_blocking` or deadpool `interact`.
  - This matches the existing Python semantics exactly, including "transactions contain DB work only", because a closure cannot await network I/O.
- Later BEGIN CONCURRENT path: grow the writer from 1 to K connections, each running `BEGIN CONCURRENT ... COMMIT` inside a retry loop on `SQLITE_BUSY_SNAPSHOT`, and keep the commit itself serialized (SQLite already serializes COMMIT). The closure-based API makes retries safe only if closures are idempotent and free of side effects, which the "DB work only" rule already guarantees.
- tokio-rusqlite (prior knowledge, unverified) is the same pattern: one connection on a background thread with a `call()` closure API. It is a good fit for the writer if you would rather not hand-roll it.

### Gaps
- No fetched source for tokio-rusqlite's current version or maintenance status, r2d2_sqlite, or bb8-based SQLite pools.
- No 2024-2026 engineering blog posts on Rust SQLite single-writer designs were retrieved.

## Q3. BEGIN CONCURRENT status (2026), building it, compatibility, conflicts and keys

### Takeaway
BEGIN CONCURRENT is still an unmerged branch that the SQLite developers maintain by merging in trunk. It is tagged per release (for example `begin-concurrent-3.51`, with a 3.51.3 version for the branch on 2026-03-13). There is no announced plan to merge it into trunk. It works in plain `wal` mode with optimistic page-level conflict detection, so time-ordered keys (rowid or uuid7) on the same B-tree page will conflict.

### Cited Findings
- The sqlite.org timeline shows the branch kept current with trunk into 2026. The newest tag seen was `begin-concurrent-3.51` (2026-03-13, user drh), and there is a "Version 3.51.3 for the begin-concurrent branch" check-in — [SQLite timeline begin-concurrent](https://www.sqlite.org/src/timeline?r=begin-concurrent). A related branch, `begin-concurrent-pnu`, also exists — [timeline](https://sqlite.org/src/timeline?r=begin-concurrent-pnu).
- Official stance (2024-2025, older material): "not on any written-down roadmap" (Aug 2024), and the branch "continues to get actively updated from trunk" but "there are currently no concrete plans to merge them to the trunk" (Oct 2024, Stephan Beal). SQLite's testing guarantees do not cover non-trunk branches. The way to influence priorities is a SQLite Consortium membership (Apr 2025) — [SQLite forum: Official support for BEGIN CONCURRENT](https://sqlite.org/forum/info/84fe63b7b3).
- Users: the forum mentions "at least one highly-active user" of the bedrock branch (unnamed; Bedrock is Expensify's), zerosync.dev evaluating it in 2024, and a Go package by Nuno Cruces for testing the bedrock branch — [SQLite forum](https://sqlite.org/forum/info/84fe63b7b3).
- Turso (Aug 3, 2026) still describes it as "an experimental BEGIN CONCURRENT branch that has never been merged into mainline" — [Turso blog](https://turso.tech/blog/concurrent-writes-on-turso-cloud).
- Semantics:
  - Works if the database is in "wal" or "wal2" mode, and the system still serializes COMMIT.
  - Locking is deferred to COMMIT.
  - Uses "optimistic page-level-locking". At COMMIT, if any page the transaction read was modified after its BEGIN, the commit fails with SQLITE_BUSY_SNAPSHOT and "all the client can do is ROLLBACK".
  - Conflicts are logged through `sqlite3_log` with the page and the table or index involved.
  - A writer that can't get the commit lock uses the busy handler.
  — [begin_concurrent.md](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md)
- Key layout: "Two transactions that write to different sets of tables never conflict." Writes to the same table or index conflict when keys are close. Monotonic rowids are "terrible for concurrency, as it all but ensures that all new rows are added to the same database page". The doc recommends random INTEGER PRIMARY KEY values, or inserting 9223372036854775807 to get a random rowid. Indexes on monotonic values such as timestamps also contend. On Unix, the `unix-excl` VFS is suggested for single-process use — [begin_concurrent.md](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md).

### Inferences
- EvoFlux's uuid7 PKs on normal rowid tables:
  - **Table b-tree:** the table b-tree is keyed by the implicit rowid, which is assigned monotonically. Every insert into a table therefore hits the rightmost leaf page, so concurrent inserts into the same table will nearly always conflict.
  - **PK index:** the separate unique index on the uuid7 column is also time-ordered, so it creates a second hotspot.
  - **WITHOUT ROWID:** converting a table to WITHOUT ROWID would key it by uuid7 directly, which is still time-ordered and still a hotspot.
  - **Real fix:** keys with random high bits (uuid4, or explicitly assigned random rowids). This trades away locality and adds page splits.
  - **What does parallelize:** writes to different tables, and updates to existing rows spread across the keyspace.
- File format: BEGIN CONCURRENT does not change the on-disk format in `wal` mode, so files stay readable by stock SQLite (prior knowledge; the doc only states the wal/wal2 requirement). Do not use `wal2`: stock SQLite cannot open wal2 databases (prior knowledge, unverified). Mixing processes that run a branch build and a stock build on the same live file is untested territory.
- Building: fetch the tagged check-in (for example `begin-concurrent-3.51`) from sqlite.org Fossil (or the GitHub mirror), run `./configure && make sqlite3.c` to produce the amalgamation, then compile it with the same flags libsqlite3-sys uses (`-DSQLITE_ENABLE_*`, THREADSAFE=1) for Windows (MSVC), macOS (universal) and Linux. Link it through `SQLITE3_LIB_DIR` + `SQLITE3_STATIC=1`, or through a vendored libsqlite3-sys fork. Either way, the team takes over upgrade cadence and testing that SQLite does not guarantee for branches.
- Expected gain for a single-user desktop app is modest: one human plus several agents rarely saturates a single writer if transactions contain DB work only. Measure writer queue wait (the 503 rate) before adopting.

### Gaps
- No published real-world conflict-rate measurements for BEGIN CONCURRENT were found.
- Not confirmed: whether the branch has a 3.52+/3.54 tag yet. The latest tag seen was the 3.51 series, which suggests branch tags may lag trunk releases.
- An authoritative statement on file-format compatibility of branch-written `wal` databases was not retrieved.

## Q4. Alternatives with concurrent writes: libSQL and Turso Database

### Takeaway
Neither is a safe 2026 choice for opening existing user files in place. Turso's own manual labels its MVCC/BEGIN CONCURRENT mode "not production ready" and lists large compatibility gaps (no triggers, savepoints or multi-process access; indexes experimental). libSQL is in maintenance mode, with new features going to Turso.

### Cited Findings
- Turso Database manual:
  - MVCC is enabled with `PRAGMA journal_mode = mvcc;`, and BEGIN CONCURRENT is only available under MVCC. MVCC is "not production ready" and should not be used for critical data.
  - Changes written under MVCC are invisible to non-MVCC opens until they are checkpointed.
  - `wal_checkpoint(TRUNCATE)` blocks readers and writers. Passive checkpoint is experimental.
  - Indexes on WITHOUT ROWID tables are not supported under MVCC.
  - General gaps: no multi-process access or multi-threading, no savepoints or triggers, views only behind a flag, indexes experimental and off by default, UTF-8 only, and only a subset of the C API.
  — [Turso manual](https://github.com/tursodatabase/turso/blob/main/docs/manual.md)
- Turso Cloud opened an early preview of BEGIN CONCURRENT on 2026-08-03. Turso detects conflicts per row, not per page. The open-source engine had supported MVCC concurrent writes for "a couple of months" — [Turso blog Aug 2026](https://turso.tech/blog/concurrent-writes-on-turso-cloud); [Turso concurrent writes docs](https://docs.turso.tech/tursodb/concurrent-writes); [Turso blog](https://turso.tech/blog/beyond-the-single-writer-limitation-with-tursos-concurrent-writes). A third-party ActiveRecord adapter also labels MVCC experimental — [activerecord-turso](https://www.rubydoc.info/gems/activerecord-turso/0.3.3).
- libSQL README: maintained, but "new features are being developed in Turso". An April 2026 commit deprecated the `sync()` APIs in favour of the `turso` crate. Pre-release 0.10.0-pre.x exists. These details come from mirror sites, not the official repo — [libSQL mirror](https://upd.dev/tursodatabase/libsql).

### Inferences
- Turso lacks triggers and multi-process support, and MVCC writes stay invisible to stock SQLite until checkpointed. Each of these breaks the "open existing DBs in place and keep them readable by standard SQLite" requirement, and an Alembic-built schema may well use triggers.
- Row-level MVCC would solve the uuid7 hotspot problem that page-level BEGIN CONCURRENT has, so Turso is worth re-evaluating in 2027+.

### Gaps
- No Turso version number or 1.0/GA date was found. No libSQL BEGIN CONCURRENT status was found (libSQL historically carried some of these patches; unverified).

## Q5. Migrations and taking over from Alembic

### Takeaway
Keep Alembic's `alembic_version` table as the source of truth during transition. Write a small custom migrator (or use refinery with a baseline) that maps Alembic revision ids to Rust migrations. Avoid rusqlite_migration unless `user_version` is guaranteed untouched.

### Cited Findings
- rusqlite_migration stores state in SQLite's `user_version` field (an integer at a fixed offset in the file), not in a table. Behavior is unspecified if anything else changes `user_version`. It depends on rusqlite ^0.40.0 — [rusqlite_migration docs](https://docs.rs/rusqlite_migration/latest/rusqlite_migration/).
- refinery keeps a table of applied versions and metadata, checks for divergent or missing migrations, has no down-migrations, and supports rusqlite natively (sqlx through a Config). Changing the version type on an existing history table breaks checksums — [refinery README](https://docs.rs/crate/refinery/0.9.1/source/README.md).

### Inferences
- Takeover procedure:
  1. On open, read `SELECT version_num FROM alembic_version`.
  2. Refuse to open (or run a legacy path) if the revision is not one of the known-final Alembic revisions.
  3. Stamp the Rust migrator's baseline (refinery: insert baseline row(s); sqlx: insert rows into `_sqlx_migrations` with matching checksums; custom: own table).
  4. From then on, apply only Rust migrations.
  5. Optionally keep writing the Alembic revision for downgrade or back-compat with the Python app.
- A hand-rolled migrator (~150 LOC over rusqlite) gives full control over the Alembic bridge and avoids checksum lock-in. That is reasonable given 53+ legacy revisions that will never re-run.
- SQLite ALTER limitations mean Rust migrations will still need the "create new table, copy, drop, rename" pattern Alembic batch mode uses. Run it with `foreign_keys=OFF` + `PRAGMA foreign_key_check` inside the migration, since `foreign_keys` cannot be toggled inside a transaction (prior knowledge).

### Gaps
- sqlx migrate and diesel_migrations baselining specifics were not retrieved this session.

## Q6. SQLite tuning and Windows pitfalls

### Takeaway
Use WAL + synchronous=NORMAL + busy_timeout, keep foreign_keys=ON per connection, make checkpoints explicit to avoid WAL growth from long-lived read connections, and treat SQLITE_IOERR_LOCK and other transient I/O errors as retryable on Windows because of antivirus mandatory locks.

### Cited Findings
- WAL mode persists in the file. Auto-checkpoint runs at 1000 pages and when the last connection closes. A checkpoint can only reset the WAL when no reader is using it. With always-overlapping readers the WAL "will grow without bound"; mitigate with reader gaps or RESTART/TRUNCATE checkpoints, which may block — [SQLite WAL](https://www.sqlite.org/wal.html).
- With synchronous=NORMAL the WAL is not synced per commit, only at checkpoint, so transactions "might rollback following a power failure or hard reset". The database stays consistent — [SQLite WAL](https://www.sqlite.org/wal.html).
- WAL does not work over network filesystems. `-shm` is an mmapped file in the database directory (Windows has no nameless shared memory). `-wal` is part of the persistent state and must not be separated from the database — [SQLite WAL](https://www.sqlite.org/wal.html).
- SQLite's Windows test suite targets "transient mandatory locks that sometimes appear on database files due to anti-virus software", which surface as SQLITE_IOERR_LOCK ("disk I/O error"), not SQLITE_BUSY — [win32lock.test](https://www.sqlite.org/src/artifact/71642fa56e9b06e5). Leftover undeletable `-wal`/`-journal` side files can also cause disk I/O errors on Windows (described in a Python filelock advisory) — [CVE advisory](https://corgea.com/advisories/vulnerabilities/CVE-2026-112913).

### Inferences
- Recommended per-connection setup: `journal_mode=WAL` (once), `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `temp_store=MEMORY`, a moderate `cache_size` and `mmap_size` (for example 256 MB; mmap gives little benefit on Windows and fails badly on I/O errors, so keep it optional). Readers additionally get `query_only=ON`.
- Run a periodic or idle `PRAGMA wal_checkpoint(PASSIVE)` from the writer, and use `TRUNCATE` at shutdown. Run `PRAGMA optimize` on close.
- `auto_vacuum=INCREMENTAL` only takes effect on existing DBs after a full VACUUM (prior knowledge), so for user DBs created by Python this is a one-time migration decision.
- Store the DB under the local app-data dir (`%LOCALAPPDATA%` on Windows), not a synced or roaming folder such as OneDrive or a network share.

### Gaps
- No primary source on Windows Defender exclusion guidance or mmap behaviour on Windows was fetched.

## Q7. Production Rust local apps and their SQLite crate

### Takeaway
Zed uses its own wrapper over libsqlite3-sys. Atuin uses sqlx 0.9 (plus rusqlite). Tauri's official SQL plugin uses sqlx. All of them share libsqlite3-sys as the linking layer.

### Cited Findings
- Zed: `crates/sqlez` depends on `libsqlite3-sys` (workspace) with `thread_local`, `parking_lot` and `futures`, an in-house thin wrapper — [Zed sqlez Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/crates/sqlez/Cargo.toml).
- Atuin: `sqlx = "0.9"` (runtime-tokio), `rusqlite = "0.32"` (unlock_notify), and a pinned `libsqlite3-sys` range — [Atuin Cargo.toml](https://raw.githubusercontent.com/atuinsh/atuin/main/Cargo.toml).
- tauri-plugin-sql 2.6.0 uses `sqlx = "0.8"`, with the `sqlite` feature mapping to `sqlx/sqlite` + `sqlx/runtime-tokio` — [plugin-sql Cargo.toml](https://raw.githubusercontent.com/tauri-apps/plugins-workspace/v2/plugins/sql/Cargo.toml). A third-party `silvermine/tauri-plugin-sqlite` was upgrading to sqlx 0.9 — [PR #48](https://github.com/silvermine/tauri-plugin-sqlite/pull/48).

### Inferences
- The two most performance-sensitive desktop apps (Zed, and Atuin's mixed use) both reach below sqlx for some paths. This supports a rusqlite-centred design for EvoFlux.

### Gaps
- Signal's Rust SQLite usage (Signal Desktop's DB is SQLCipher through Node/C++, not Rust, from prior knowledge) and other apps (for example Spacedrive, Mozilla application-services, which uses rusqlite per prior knowledge) were not verified this session.
