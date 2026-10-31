# EvoFlux v4 — Rust backend migration design

Status: draft for approval · 2026-10-30 · Base: `main` at v3.1.1 (`8fd844d5`)

## 1. Intent

Replace the Python FastAPI sidecar (`app/`, ~167k lines) with a Rust backend so
EvoFlux is faster and stops becoming unresponsive. The React UI (`web/`) and the
Tauri shell (`desktop/src-tauri/`) stay. Users upgrading from v3 must notice
only that the app is faster and no longer freezes: same screens, same data,
same behaviour.

The owner observed the app staying alive in the background while the UI stops
responding. The working hypothesis (unverified) is that the single uvicorn
asyncio loop (`app/server.py`) gets blocked: 32 files under `app/` call
`subprocess.run`/`time.sleep`. The Rust backend must make that class of failure
structurally impossible (§6.3), otherwise the rewrite can reproduce it.

The work is split by API/feature area so many AI agents, tools and apps
(EvoFlux itself, Claude Code, Codex, etc.) can work in parallel, nonstop, on a
separate branch. `main` holds until v4 is fully migrated and tested, then
receives one merge.

## 2. Goals, non-goals, anti-goals

**Goals**
- Every `/api/*`, `/metrics`, SSE and WebSocket endpoint served by Rust.
- Same HTTP contract: paths, methods, status codes, JSON shapes, SSE event
  envelopes, WebSocket frames, auth rules, error codes (e.g. `503 database_busy`).
- Opens every existing v3.x user database and config directory in place.
- Measurably faster than v3.1.1 (§8), and the UI never stalls because of the backend.
- Parallel lanes that cannot break each other or the core (§5, §6).

**Non-goals (during the migration)**
- No UI changes, no new features, no API changes, no database schema changes.
- No "while I'm here" behaviour fixes. A Python bug is ported as-is unless the
  fix is approved and recorded in `server/KNOWN_DIFFERENCES.md` with a contract test.
- No change to the Tauri shell beyond launching the new backend binary.

**Anti-goals (failure even if it "works")**
- A user's sessions, memory, settings, credentials or repositories lost or
  silently changed after upgrading.
- Rust code that passes tests but behaves differently for real use (drift).
- A v4 that can freeze the same way v3 does.
- A half-migrated `main`.

## 3. Architecture: the gateway (strangler pattern)

```text
Tauri shell ──spawns──> evoflux-server (Rust, the only port the UI sees)
                           │  routes owned by Rust  → Rust handlers
                           │  routes owned by Python → reverse proxy (HTTP, SSE, WS)
                           └──spawns──> Python sidecar on a private loopback port
```

- New Rust binary `evoflux-server`. It prints the same handshake line the shell
  already parses (`HANDSHAKE_PREFIX` + JSON, `desktop/src-tauri/src/sidecar.rs`)
  and enforces the same desktop/access-key auth, so `sidecar.rs` only changes
  which binary it starts.
- Unported routes are proxied byte-for-byte to the Python sidecar, which the
  gateway starts, health-checks and stops. Python's *behaviour* stays the
  reference, but it needs one Phase 0 shared PR (owner-reviewed) with exactly
  three startup-level changes:
  1. listen on a gateway-chosen private loopback port and accept only requests
     carrying a gateway-issued secret;
  2. trust caller identity forwarded by the gateway, reusing the existing
     trusted-proxy mechanism (`embedded_remote_proxy_secret` in
     `app/core/desktop_auth.py`) instead of re-authenticating;
  3. `EVOFLUX_DISABLE_SERVICES=<service,...>` to skip starting a background
     service in the lifespan (`app/api/app.py`) once its unit has moved to
     Rust, so the scheduler, dream, conductor, MCP manager, WebBridge cleanup
     etc. never run in both processes.
- **Ingress:** the gateway owns all ingress from Phase 0, including the remote
  path. The `evoflux-tailnet` helper is pointed at the gateway port, not
  Python's. *(My call.)*
- **Rust never calls Python.** The gateway proxies UI/remote requests to
  Python, and Rust code never calls Python to reach unported state. **Python may
  call Rust** for areas that have already moved, through temporary adapters
  (§3.4, [ADR 0001](../architecture/decisions/0001-rust-migration-python-calls-rust.md)).
- **Routing table** `server/routing.toml` maps each route family to an owner:
  `python`, `rust`, or `shadow` (Python answers; Rust also runs the read-only
  request and logs differences; GET routes only).
- **Rollback switch**: `EVOFLUX_ROUTE_OVERRIDE=<unit>=python,...` forces units
  back to Python at runtime with no rebuild. It works until Python is removed (Phase 4).
- Separate process, not inside the Tauri process: a backend crash can't take
  down the window, and the API-only server distribution stays possible.

### 3.1 Cutover units

Routes can only move as a group when they share in-memory state. Example: chat
ingress queues into the team manager, and the SSE stream comes from the
in-memory stream store, so chat ingress, SSE, `team_manager` and the agent
runtime are **one unit**. Background services belong to units too: the task
scheduler (`app/scheduler/scheduler.py` dispatches through `team_manager`) and
dream (`app/services/dream.py` builds an agent and provider in-process)
both join the agent-runtime unit. Phase 0 produces `server/CUTOVER_UNITS.md`:
every route family **and every lifespan background service** assigned to
exactly one unit, with the in-memory state that pins it there. A unit's routes
flip to Rust and its Python services are disabled in one change, never piecemeal.

### 3.1a Breaking pins with adapters (owner decision, 2026-10-30)

Phase 0 mapping found 91 % of routes pinned to the agent-runtime unit,
because Python agent tools share in-memory state with those routes. Units are
therefore split again, and each split is made possible by §3.4: once a unit
moves, Python's agent code reaches it through a Rust API adapter instead of
the in-process object.

### 3.2 Database during the migration

- Same SQLite file, WAL mode, `PRAGMA foreign_keys=ON`.
- The schema is frozen at the v3.1.1 Alembic head. Alembic stays the schema
  owner until Phase 4. Rust never runs DDL before then.
- Rust reproduces the read lane and rules in
  `documents/architecture/sqlite-concurrency.md` (5-connection `query_only`
  read pool, 5 s admission timeout → `503 database_busy`, no
  filesystem/Git/model/process work inside a transaction). It replaces the
  single writer with the concurrent and exclusive write lanes in §3.3.
- While both processes write, they contend at the SQLite file lock. Both set
  `busy_timeout`, and the contract suite includes a two-process write test.
- Phase 4: Rust takes over migrations. **Upgrade baseline (my call):** v4
  opens a database from any v3.x release. The Alembic revisions between the
  v3.0.0 head and the v3.1.1 head are ported into Rust's embedded migrations.
  Databases older than v3.0.0 get a clear "upgrade to v3.1.1 first" error.
  These fixtures don't exist yet (`tests/fixtures` has none): Phase 0 builds
  every v3.x tag, generates a populated database and config dir from each,
  and stores them under `contract-tests/fixtures/upgrade/`.

### 3.3 SQLite concurrent writes with `BEGIN CONCURRENT` (owner decision: implement)

The owner wants concurrent writes implemented in v4, **without breaking
compatibility with existing SQLite databases**. Reference:
[`BEGIN CONCURRENT`](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md).

**How it works.** Several write transactions run at the same time with
optimistic page-level locking. At `COMMIT`, if a page the transaction read was
changed by another commit since it began, the commit fails with
`SQLITE_BUSY_SNAPSHOT`. The transaction must roll back and be retried. `COMMIT`
itself is still serialized. Writes to different tables never conflict.

**Compatibility rules (non-negotiable)**
1. **`wal` journal mode only, never `wal2`.** In `wal` mode the database and
   WAL files have the standard format. `wal2` files can't be opened by standard SQLite.
2. **No schema change.** Conflict reduction (below) works with the v3.1.1 schema as-is.
3. **Compatibility gate** (Phase 0, then every PR touching `core::db`): after a
   concurrent-write stress run, the database must pass `PRAGMA integrity_check`
   and `PRAGMA foreign_key_check` with stock SQLite (latest release), open and
   pass the contract suite under v3.1.1 Python, and match the expected row
   counts. If this gate ever fails, the feature stays off (rule 5).
4. **Pinned build.** `BEGIN CONCURRENT` exists only on SQLite's
   `begin-concurrent` branch, which tracks trunk but isn't in release builds.
   `crates/core` statically links a SQLite amalgamation built from a pinned
   branch tag (e.g. `begin-concurrent-3.51.x`) through `libsqlite3-sys`. A
   monthly CI job compares it with the latest SQLite release and opens a
   shared PR to rebuild when security fixes land. Only Rust uses this build;
   Python and other tools keep using stock SQLite on the same file.
5. **Off switch.** `EVOFLUX_DB_CONCURRENT_WRITES=off` sends every write through
   the single FIFO writer, without a rebuild (§10).

**Write lanes in `crates/core::db`**
- **Concurrent lane** (default for ordinary writes): a small pool of writer
  connections (start with 4, tuned by benchmark), each `BEGIN CONCURRENT`.
  Commits go through an in-process mutex, not SQLite's busy handler, as the
  SQLite document recommends. On `SQLITE_BUSY_SNAPSHOT`: roll back and rerun
  the closure, at most 5 attempts with jittered backoff, then the existing
  `503 database_busy`. The 5 s admission timeout is unchanged.
- **Exclusive lane**: the single FIFO writer for migrations, bulk
  cleanup/purge, large imports, and any transaction marked
  `db.write_exclusive(...)` (wide multi-table changes where retries would be expensive).
- Lane crates only call `db.write(|tx| ...)` / `db.write_exclusive(|tx| ...)`.
  The closure may run more than once, so it holds database work only: no
  filesystem, Git, model, process or network work and no events published
  inside it. That matches the v3 transaction rule, and the retry-safety test
  enforces it.

**Reducing conflicts without changing the schema**
- **Random rowids.** Most tables have UUID primary keys on normal rowid tables
  (`app/models/*.py`), so SQLite's hidden rowid grows by one per insert and
  every concurrent insert hits the same last page. Rust inserts set an
  explicit random rowid (uniform in 1..2^62). No code reads `rowid`
  (checked: no use under `app/` outside migrations). Rowids are invisible to
  the API, and stock SQLite and v3 handle any rowid value, so this is
  file- and behaviour-compatible.
- **Remaining hot spots:** the `uuid7` primary-key index and time-ordered
  indexes such as `(session_id, created_at, id)` still put new keys at the
  end of the index. Concurrent inserts into the *same* table can conflict
  there and retry. Transactions are short and DB-only, so a retry is cheap.
  The conflict metric shows where this matters. Changing id generation or
  indexes would be a schema/contract change and is out of scope for v4 (v4.1 candidate).
- **Biggest gain:** writes to different tables run fully in parallel
  (message persistence alongside usage/observability telemetry, memory,
  scheduler, delegation state), which the single writer serializes today.

**While Python still writes (Phases 1–3)**
Python keeps its own single writer with stock SQLite. Rust's concurrent
transactions take the standard WAL write lock at commit, so the two
processes coordinate through SQLite's normal locking. Phase 0 proves this with
a two-process stress test (v3.1.1 Python writer + Rust concurrent writers,
then the compatibility gate). If it fails, Rust runs with the switch off until
Python stops writing (Phase 4).

**Metrics and tests**
- `EVOFLUX_db_concurrent_conflicts_total{table}`,
  `EVOFLUX_db_concurrent_retries_total{lane}`, and per-page conflict detail
  from `sqlite3_log` in debug builds.
- Retry-safety test: inject `SQLITE_BUSY_SNAPSHOT` on every first commit and
  check the final state is identical and no side effect ran twice.
- Benchmark in Phase 0 and again in Phase 4: write throughput and p99 write
  latency, FIFO vs concurrent, on the main write paths. v4 target: no write
  path slower than FIFO; the pool size is tuned from these numbers.

**Owner decision (2026-10-31): implemented, default off.** The Phase 0
benchmark (`documents/analysis/sqlite-concurrent-writes-benchmark-2026-10-30.md`,
3-run medians, 2 writers) showed the FIFO writer matching or beating
`BEGIN CONCURRENT` in every workload: messages 2087/s vs 1472/s, cross-table
3354/s vs 2940/s. The concurrent lane stays built and tested behind
`EVOFLUX_DB_CONCURRENT_WRITES`, but **the default is the FIFO writer**. Re-benchmark it
(a) after Python stops writing (Phase 4), and (b) with v4.1 schema changes that
remove the time-ordered hot pages, and enable it per write path only where it wins.

Note: in v3, database contention is already bounded at 5 s → `503`, so this
improves throughput and is probably not the cause of the freezes.

### 3.4 Python calls Rust for moved areas (ADR 0001)

Owner decision, 2026-10-30. Full record:
[ADR 0001](../architecture/decisions/0001-rust-migration-python-calls-rust.md).

- When a unit cuts over, its in-process Python service object is replaced by
  an adapter in `app/core/rust_bridge/<area>.py`. The adapter forwards to the
  gateway's loopback API, sending the gateway secret and the desktop token;
  adapters act as the desktop user, matching v3 parity.
- An adapter is active only while its unit's owner is `rust`, so
  `EVOFLUX_ROUTE_OVERRIDE` rollback also switches the adapter back. Python reads
  `EVOFLUX_GATEWAY_URL` and `EVOFLUX_RUST_UNITS` at startup; routing changes
  restart Python to apply the new ownership.
- The adapter ships in the unit's cutover PR, together with a contract test
  proving the Python agent tool path reaches Rust.
- Pins that are only locks become cross-process file locks (a `core` helper,
  mirrored in Python).
- Adapters are **temporary**. All are deleted when the agent-runtime unit moves
  (Phase 3). The goal is a fully Rust backend (§9).

## 4. Repository layout and branches

```text
server/                      # new Cargo workspace (separate from desktop/src-tauri)
  crates/core/               # config, paths, db lanes, auth, telemetry, errors  [shared]
  crates/api-types/          # request/response types, OpenAPI via utoipa        [shared]
  crates/gateway/            # routing table, proxy, Python supervisor            [shared]
  crates/area-<name>/        # one crate per lane                                 [lane-owned]
  crates/server/             # the evoflux-server binary, wires areas in          [shared]
  routing.toml  CUTOVER_UNITS.md  MIGRATION_BOARD.md  KNOWN_DIFFERENCES.md
contract-tests/              # black-box HTTP suite run against Python and Rust   [shared]
```

**Branches**
- `migrate/rust-v4`: the integration branch, created from `main` at v3.1.1.
  Protected: merges only through PRs with all gates green (§6).
- `migrate/<lane>`: one per lane, branched from `migrate/rust-v4`, rebased at
  least daily, merged back by PR. Short-lived: merge as soon as a slice is green.
  Shared changes use `migrate/shared-<topic>`, cutovers `migrate/cutover-<unit>`
  (workflow §1).
- Bootstrap: the first commit on `migrate/rust-v4` (these planning documents)
  is pushed directly. The owner then turns on branch protection for
  `migrate/rust-v4` on GitHub (required checks + PR-only), and from then on
  only PRs merge.
- `main`: frozen. The only allowed changes are critical security/data-loss fixes
  (approved by the owner), which are then merged forward into `migrate/rust-v4`.
  *(My call; `main` is otherwise untouched.)*

## 5. Multi-agent protocol

The step-by-step lane workflow, branch rules, coding rules, testing rules and
review checklist live in [rust-migration-workflow.md](rust-migration-workflow.md),
which becomes `server/AGENTS.md` in Phase 0. This section is the summary.

The protocol uses only git, files and `make` targets, so any agent, tool or app can follow it.

- **`server/MIGRATION_BOARD.md`** lists every lane with: owned Python source
  paths, owned routes, cutover unit, owned output paths, status
  (`open` → `claimed:<agent>` → `in-review` → `merged` → `cut-over`), and the
  current gate report link. An agent claims a lane by opening a draft PR that
  changes only its row.
- **One lane, one owner, one set of paths.** A lane PR may only touch
  `server/crates/area-<lane>/`, its rows in the board, and new contract tests
  under `contract-tests/<lane>/`. CI rejects anything else (§6.1, check 9).
- **Shared paths** (`crates/core`, `api-types`, `gateway`, `server`,
  `routing.toml`, gates and CI, existing contract tests) change only through a
  `shared:` PR that the owner reviews. A lane that needs a shared change opens
  a request in the board and waits, or works around it inside its crate.
- **Lane brief** for an agent: the board row, plus the Python files to read, the
  existing Python tests for that area (behaviour reference), the contract tests
  that must pass, and the commands:
  `make contract AREA=<lane> TARGET=python|rust`, `make gates AREA=<lane>`.
- Agents never edit `app/`, `web/` or `desktop/` on the migration branch,
  except two Phase 0 shared PRs: the launcher change in `sidecar.rs` and the
  Python startup PR (§3), and cutover PRs adding temporary `app/core/rust_bridge/`
  adapters, their replaced call sites and contract tests (ADR 0001).

## 6. Constraints that protect the app core

### 6.1 Merge gates (all automatic, all required, CI on every PR to `migrate/rust-v4`)

1. `cargo fmt --check`, `cargo clippy -- -D warnings`.
2. No panics in non-test code: clippy `unwrap_used`, `expect_used`, `panic`,
   `indexing_slicing`, `todo`, `unimplemented` denied. Each handler runs behind
   a panic-catching layer that returns 500 and logs, so a bug never kills the process.
3. **No blocking on the async runtime** (§6.3): `clippy::disallowed_methods`
   bans `std::thread::sleep`, `std::fs::*`, `std::process::Command`,
   `std::net` blocking I/O, and blocking DB drivers outside `spawn_blocking` helpers in `crates/core`.
4. Rust unit and integration tests for the crate.
5. The lane's contract tests pass with `TARGET=rust` **and** still pass with `TARGET=python`
   (proves the test describes v3 behaviour, not Rust behaviour).
6. The **full** contract suite passes through the gateway with the PR's routing
   (no regression in any other area).
7. OpenAPI diff: Rust-generated schema for owned routes equals Python's `/openapi.json` for the same routes.
8. Performance check (§8): not slower than Python on the lane's endpoints, and
   the responsiveness test passes.
9. Path-ownership check: the diff only touches paths the board assigns to the PR's lane.
10. DB safety: the suite runs against copies of fixture databases and checks
    that schema and unrelated rows are unchanged afterwards.

### 6.2 What the owner reviews by hand (my call)

Everything else merges automatically when green.

- All Phase 0 foundation PRs and every later `shared:` PR (core, gateway,
  api-types, routing logic, gates, CI, existing contract tests). Weakening a
  test or a gate is the most likely way an unsupervised agent "passes".
- Each **cutover**: the one-line `routing.toml` change that flips a unit to
  `rust`, accepted after reading its gate and shadow reports.
- Security-critical ports: auth middleware, permissions and sandbox, secret/PII
  redaction, credential storage (keyring), WebBridge pairing, Computer App Control approval.
- Entries in `KNOWN_DIFFERENCES.md`.
- The final v4 merge into `main`.

### 6.3 No-freeze rules for the Rust backend

- One multi-threaded tokio runtime. Request handlers never block: blocking work
  goes through `spawn_blocking` or a dedicated bounded worker pool.
- Every outbound call (model provider, Git, MCP, web search, subprocess) has a
  timeout and is cancelled when the client disconnects.
- Health (`/api/health/*`) runs without touching the DB writer or any area lock,
  so it stays fast while everything else is busy.
- A watchdog task measures runtime scheduling delay and logs and exports a
  metric when it goes over 100 ms.

### 6.4 Contract tests (built in Phase 0)

Only 63 of 363 existing test files go through HTTP. The others test Python
internals and can't check Rust. They stay as the behaviour reference that
agents read.

- `contract-tests/`: pytest + httpx, black-box, against `EVOFLUX_TEST_BASE_URL`.
  Each test starts a fresh backend with a temp config dir and a fixture database.
- Coverage target before Phase 2: every route family has tests for its success
  path, auth failure, validation failure and main error codes. Before a unit's
  cutover, every endpoint in the unit is covered.
- Responses are compared after normalising ids, timestamps and ordering where
  ordering isn't part of the contract.
- **Model calls** go to a local mock provider that replays recorded streams
  (text, reasoning, tool calls, usage, errors), so agent-loop tests are
  deterministic. Real-provider smoke tests run nightly, not as gates.
- **Recorded traffic**: a gateway debug mode records real request/response
  pairs while the owner uses the app; scrubbed recordings become replay tests.

## 7. Phases and estimate (agents running nonstop)

| Phase | Work | Gate to leave | Estimate |
|---|---|---|---|
| 0. Foundation | **Freeze diagnosis on v3.1.1 first** (event-loop lag monitor + `py-spy dump` when the UI stalls; identify the real cause so the responsiveness gate measures the right thing), v3.x upgrade fixtures, the Python startup PR (§3), branch, `server/` workspace, `core` (config, paths, db lanes including the pinned `begin-concurrent` SQLite build, compatibility gate and two-process stress test (§3.3), auth, telemetry, errors), gateway + Python supervisor + routing table + override, contract harness + mock provider + first route-family coverage, CI with all gates, `CUTOVER_UNITS.md`, `MIGRATION_BOARD.md`, v3.1.1 performance baseline, `sidecar.rs` launching the gateway with everything routed to Python | App works fully through the gateway with 100 % Python routing; owner approval | 3–5 days |
| 1. Pilot | Small units with no shared in-memory state: health, diagnostics, quote, commands, snippets, wiki, observability (final list from `CUTOVER_UNITS.md`; scheduler and dream wait for Phase 3) | First units cut over and used in real use for a day; the process is adjusted | 1–2 days |
| 2. Services (parallel lanes) | CLI (§11a), settings/providers config, skills/agents registry, plugins/marketplace, MCP management, git/coding workspace/reviews/change sets, terminal/shell/processes/file watcher (ConPTY), memory/search, documents/preview/import/office, WebBridge/browser/computer bridge/remote use | Each unit cut over | 1–2 wks |
| 3. Agent runtime | providers (~17k lines), tools (~19k), MCP client, hooks, plugins/skills, Python plugin host + on-demand Python runtime (§11), `skill-scripts` lane (§11), modes, teams/delegation, scheduler + dream, then agent loop + chat/SSE unit last | Unit cut over; replayed-conversation suite green; owner uses it daily | 2–3 wks |
| 4. Hardening | Remove Python sidecar from the gateway, Rust owns migrations, re-run the concurrent-write benchmark and tune the pool (§3.3), v3.x upgrade tests, packages for Windows/macOS/Linux, performance report, dogfood | §9 done criteria | 1–2 wks |

**Total: about 6–9 weeks** (the original 5–8, plus about a week of lanes for the CLI, the Python plugin host and the skill scripts). What still takes calendar time: Phase 0 can't run
in parallel; the agent runtime is hard to verify; packaging and real-world use
run at real-world speed.

## 8. Performance and responsiveness

- Baseline v3.1.1 in Phase 0: cold start to handshake, idle memory, p50/p99
  latency of the 30 most-used endpoints (taken from recorded traffic), SSE time-to-first-event.
- **Responsiveness test** (gate): during a heavy load (repository index rebuild,
  long tool run, large history page), `/api/health/live` p99 stays under 50 ms
  and a session history page p99 stays within 2× its idle value. This is the
  test that represents "the app froze".
- v4 release target (my call): cold start ≤ 50 % of v3, idle memory ≤ 50 % of
  v3, no endpoint slower than v3 at p99.

## 9. Done criteria for the v4 merge to `main`

- `routing.toml` has no `python` entries; the backend no longer starts the Python sidecar. Python runs only on demand for §11.
- `app/core/rust_bridge/` is gone: no ADR 0001 adapters remain.
- Full contract suite, Rust tests and v3.x upgrade tests green on all three OSes.
- Performance targets in §8 met; report committed under `documents/releases/`.
- `KNOWN_DIFFERENCES.md` reviewed and approved by the owner.
- At least 3 days of daily use by the owner on a v4 build with no stall and no data issue.
- Desktop packages build and install for Windows, macOS and Linux; updater works from v3.1.1 to v4.

## 9a. User-level checkpoints (owner decision, 2026-10-31)

Contract tests prove the API matches; they don't prove the app works for a
person. At every checkpoint below, the app is exercised **as a normal user
would use it**, through the real desktop/web UI and the real gateway.

**Checkpoints:**
- the end of each phase (its exit report);
- every unit cutover, before its 24 h watch starts;
- before the final v4 merge to `main`.

**1. Automated end-to-end smoke suite** (`web/e2e/`, Playwright). It runs against
`run_dev.py --desktop` behind `evoflux-server`, with the mock model provider (T5)
so it's deterministic. The journeys:
- first launch: connect a provider, start a Work session, stream a reply, reload, and see the history;
- Coding: open a project, file tree, git status/diff, workspace search, editor save;
- terminal: run a command and see its output;
- agent tool call: a tool runs, is approved, and its result renders;
- settings: change a provider and toggle a skill, then restart and check both persisted;
- plugins and MCP: install the sample plugin and see its MCP server reach `ready`;
- scheduler: create a task and trigger it, and see its run appear;
- every unit cut over so far: its screens work, plus a rollback drill (`EVOFLUX_ROUTE_OVERRIDE=<unit>=python`, where the same journey still passes);
- a crash drill: kill the Python child mid-session, and the UI recovers after the 502 window.

It runs on Windows at every checkpoint and on all 3 OSes in CI nightly. A
failing journey blocks the checkpoint, the same way a failing gate does.

**2. Exploratory smoke run** (an agent with a browser). After the automated
suite passes, an agent drives the running app through the built-in browser for
about 15–30 minutes as a first-time user. It clicks around the areas changed
since the last checkpoint, captures screenshots and console/network errors,
and files each problem as a failing contract or e2e test before any fix.

**3. Owner daily use.** At phase exits and before the v4 merge, the owner uses
the app normally for at least half a day (3 days before v4, §9).

The checkpoint results go into the phase exit report: the suite results,
the exploratory findings, and the owner's sign-off.

## 9b. Phase 5: Python removal and repo cleanup (owner decision, 2026-10-31)

The final state is a **fully Rust backend with the old Python code removed**.
This runs after Phase 4: everything is cut over, the v3.x upgrade tests pass,
and the owner has signed off. Deleting earlier would remove the per-unit
rollback to Python.

**Removed:**
- `app/`: the Python backend;
- `tests/`: Python unit tests for the backend; their behaviour is covered by the contract, e2e and Rust tests;
- the Python sidecar packaging (the bundled interpreter in `scripts/build_sidecar.py`, and the backend dependencies in `pyproject.toml`/`uv.lock`);
- the gateway's Python supervisor and its Python routing (`owner = "python"`, `EVOFLUX_DISABLE_SERVICES`, `EVOFLUX_GATEWAY_SECRET` handling);
- `app/core/rust_bridge/` (it should already be gone, per ADR 0001);
- docs describing the Python backend, rewritten for Rust (`documents/architecture/*`, `AGENTS.md` files, README).

**Kept:**
- the §11 on-demand Python pieces (the `python` tool runtime, the plugin host for user `.py` plugins, and unported skill scripts), moved into one small folder outside the backend;
- the `contract-tests/` HTTP suite and the `web/e2e/` suite as permanent regression tests. Contract tests stay in pytest unless the owner later chooses to port them to Rust;
- the v3 history: the `v3.1.1` tag and pre-v4 `main`.

**Exit gate:**
- a repo-wide search finds no imports of the removed backend;
- the packaged app contains no Python backend;
- all regression suites pass;
- a user-level checkpoint (§9a) passes;
- the CHANGELOG has upgrade notes.

## 10. Rollback

- Per unit, during the migration: `EVOFLUX_ROUTE_OVERRIDE`, or revert the routing line.
- `BEGIN CONCURRENT`: a config flag per write path (`EVOFLUX_DB_CONCURRENT_WRITES`) turns it back to the FIFO writer without a rebuild.
- Per lane: lane crates are only reached through routing, so reverting a lane PR can't affect other lanes.
- After release: v4 ships **no new schema migrations**, and its files stay
  readable by stock SQLite (§3.3), so a user can reinstall v3.1.1 if needed.
  Schema changes start in v4.1 at the earliest. *(My call.)*

## 11. Python that is part of the product, not the backend

These aren't backend code, so removing the Python sidecar doesn't remove them.

- `app/agent/tools/builtin/python.py`: agents run Python code with the bundled interpreter.
- 47 Python scripts in `app/agent/builtin_skills/` (pdf, pptx, xlsx, docx skills).
- In-process Python plugins: `app/agent/plugins/loader.py` and
  `app/agent/providers/plugin_registry.py` import user plugin files.

Agent Plugins (`plugin.json` packages), plugin installs and MCP servers are
**not** in this list. EvoFlux only reads their files and starts the executables
they declare (`npx`, `uvx`, a binary, or a remote URL). They port to Rust as-is,
and Node/Python for those servers stays the user's own, exactly as in v3.

**Owner decision: Rust wherever possible, Python only where it can't be avoided.**
Python never runs inside the backend process. Where it's still needed, Rust
launches it as a subprocess (JSON-RPC over stdio for long-lived hosts), using a
python-build-standalone runtime managed by uv and **downloaded on first use,
not bundled**.

| Part | v4 | Why |
|---|---|---|
| Built-in hooks, tools, providers | **Rust** | Ported with the agent runtime |
| `python` tool | Python subprocess, sandboxed like the shell tool | The agent writes Python code, so Python is unavoidable |
| 47 built-in skill scripts | **Rust where output matches; Python otherwise.** Lane `skill-scripts` (Phase 3): for each script, port to Rust (e.g. rust_xlsxwriter/calamine for xlsx, pdfium-render/lopdf for pdf, docx-rs for docx) and keep it only if a diff test on sample files matches the Python output; otherwise keep the script. pptx is expected to stay Python. | Rust office-format libraries are uneven |
| User `.py` hook plugins (`app/agent/plugins/loader.py`) and provider plugins (`app/agent/providers/plugin_registry.py`) | **Python plugin host** (one subprocess, JSON-RPC: `tool.before`/`tool.after`, provider calls), started only if such plugins exist, with timeouts so a slow plugin can't stall a turn | User code is Python; keeps existing plugins working |
| Third-party skills from marketplace packages | unchanged | User content, run as v3 runs it |

If no Python plugin is installed and the agent never uses the `python` tool or
a Python skill, v4 never downloads or starts Python.

## 11a. CLI and API-only distribution (owner decision)

The `evoflux` CLI (`app/cli/`; `init`, `auth`, `migrate`, `start`/`stop`/`status`,
`doctor`, `cleanup`, `plugin`, `upgrade`) is **ported to Rust** as one
`evoflux` binary with the same commands, flags and output. `serve --handshake`
becomes the subcommand that `sidecar.rs` launches. The pip/uv/pipx install
channel is replaced by a binary release plus Homebrew. `evoflux upgrade` on a v3
install must detect the old channel and explain the switch. The CLI lanes run
in Phase 2 (they depend on `core` only); about 1 extra week of lane work.

## 11b. Timeline and review budget (owner decision)

The 6–9 weeks is an estimate, not a deadline. The owner reviews about 1–2 h per
day: shared PRs, cutovers, security-critical ports and `KNOWN_DIFFERENCES`.
Strict ordering applies: shared changes queue for owner review, and lanes that
depend on them wait rather than work around them.

## 12. Technology choices (from research; confirm in Phase 0 spikes)

Full evidence: [rust-backend-stack-2026-10-30.md](../research/rust-backend-stack-2026-10-30.md). Versions are as of
2026-10-30; pin exact versions for fast-moving crates (gix, rmcp, opentelemetry).

**HTTPS client and 2026-10-31 re-check:** see [rust-http-client-and-stack-recheck-2026-10-31.md](../research/rust-http-client-and-stack-recheck-2026-10-31.md).
In short: one shared `reqwest` 0.13 client in `evoflux-net`, using rustls with aws-lc-rs and the OS trust store
(`rustls-platform-verifier`). `utoipa` 6.0 is pending a spike; `keyring` stays on 3.6 until the target names are checked. That doc supersedes this table where they differ.

| Need | Pick | Why / production users | Risk and Phase 0 check |
|---|---|---|---|
| HTTP, SSE, WebSocket | **axum 0.8** + tokio + tower-http 0.7 | Largest ecosystem; Block's Goose server (`goosed`) is axum with HTTP+SSE+WS as a separate process from its desktop app, the same shape as EvoFlux | low |
| Gateway proxy | **axum-reverse-proxy 2.x**; fallback: own hyper 1 proxy | Handles HTTP + WebSocket upgrade | **SSE streaming not documented. Spike first.** Disable compression and timeouts on SSE/WS routes. |
| OpenAPI | **utoipa 5** + utoipa-axum, explicit names and operationIds | Supports OpenAPI 3.1, which FastAPI emits | Won't match FastAPI byte-for-byte. Normalize, then `oasdiff` + strict diff in CI. |
| Validation errors | garde or validator + `serde_path_to_error`, custom extractor producing FastAPI's 422 `detail[]` shape | — | Check against recorded FastAPI responses |
| No-freeze tooling | `spawn_blocking`, clippy `disallowed_methods` + `await_holding_lock`, tokio-console (dev), tokio-metrics + lag watchdog (prod) | — | low |
| SQLite | **rusqlite** (on libsqlite3-sys, linked to the pinned `begin-concurrent` amalgamation) + own pools: concurrent writer pool, exclusive FIFO writer, `query_only` readers | Zed uses its own wrapper over libsqlite3-sys. Pool crates have no lane concept, so `core` owns this. | medium: custom amalgamation build on 3 OSes; one libsqlite3-sys version across the whole dependency graph |
| `BEGIN CONCURRENT` | **Implemented** (§3.3): pinned branch build, `wal` only, random rowids, retry + exclusive lane, compatibility gate | The branch has no merge plans, so the build is pinned and tracked monthly; the research found no public conflict-rate data, hence the Phase 0 benchmark | medium |
| Turso / libSQL | **Not used** | Turso's MVCC is "not production ready" and can't open user files in place | revisit after v4 |
| Migrations | refinery or own runner, baselined from `alembic_version` | Avoid `user_version`-based tools | low |
| LLM providers | **In-house thin layer** on reqwest + SSE parsing, about 5 wire protocols (OpenAI chat/responses, Anthropic, Gemini, Bedrock via `aws-sdk-bedrockruntime`, Ollama), per-provider quirks as config data | Codex and Goose both built their own. `genai` 0.7 kept as reference/fallback for rare providers. | medium: cache-usage normalization per provider |
| SSE client | `eventsource-stream` + own parser | Codex does this | Never auto-reconnect a model POST (duplicate output/billing) |
| MCP client | **rmcp 3.x**, pinned exactly, behind an own wrapper crate (as Codex does) | Official SDK; spec 2026-07-28, legacy session mode for MCP 2.x servers, OAuth behind a feature flag | medium: fast releases. Client must handle old and new MCP lifecycles; tool scheduler needs a "waiting on user input" state (`InputRequiredResult`). |
| Agent loop tests | wiremock + typed SSE event builders + insta | Copy Codex's `core/tests/common/responses.rs` pattern | low |
| Terminal | **portable-pty 0.9** | Used by codex-rs | medium: older Windows 10 ConPTY quirks |
| Processes | tokio::process + **process-wrap** (Job Objects / process groups) | watchexec org | low. PTY children need manual job assignment. |
| Git | **Hybrid**: `gix` (pinned) for fast reads; git CLI for writes, network, credentials, worktrees | codex-rs uses gix; Zed uses the CLI | low |
| File watching | **notify 8** + notify-debouncer-full | codex-rs | Events can be missed: periodic rescan + polling fallback |
| Code search | `ignore` crate as a library; keep bundled `rg` for agent tool calls | Zed and codex-rs | low |
| LSP client | In-house JSON-RPC client on `lsp-types` | Zed does the same; client crates are immature | medium |
| Credential vault | **keyring 3.6** | — | **Python keyring writes different Windows credential names**: read with `Entry::new_with_target`, fall back to `user@service`. Contract test against real v3 entries. |
| PDF text | **pdfium-render** + bundled pdfium | Same engine as pypdfium2, so same text | Bundle pdfium per OS |
| HTML → Markdown | **htmd** | turndown port | Fidelity vs markdownify untested: diff test in Phase 0 |
| DuckDB | duckdb `=1.4.x`, bundled | — | slow builds; ICU not included |
| Cron + time | **croner** + chrono + chrono-tz | — | Must match croniter: port its test cases |
| Web search | reqwest + scraper on `html.duckduckgo.com` | No library equivalent | HTTP 202 means soft block: back off |
| Sandbox | Follow codex-rs: Seatbelt (macOS), landlock + seccompiler/bwrap (Linux), restricted token + ACLs (Windows) | — | Windows least mature |
| Redaction | In-house: gitleaks rules via `regex` + entropy check + exact-value matching | No dominant crate | low |
| Logs and metrics | tracing + tracing-subscriber + tracing-appender; opentelemetry pinned as a set; `metrics` + metrics-exporter-prometheus | — | Metric names must stay identical |
| Python runtime (§11) | python-build-standalone via uv, subprocess + JSON-RPC over stdio | Common pattern; Astral maintains python-build-standalone | Every bundled binary must be signed on macOS |
| Packaging | Tauri `bundle.externalBin` for `evoflux-server` | — | NSIS may not replace a sidecar on same-version reinstall (tauri #15134); keep the updater key; v4 must kill a leftover v3 Python sidecar |

**Methodology lessons adopted from the research** (added to the workflow doc):
validate the contract suite with mutation testing before porting ("a judge
that fails on broken code"); turn repeated review findings into rules and
regenerate rather than patch; keep a gap inventory of implicit behaviours;
run the diff on two Python instances to measure noise in shadow mode; diff
SSE as event sequences, not bodies; expect to throw away and redo a lane's
first attempt.

## 13. Left to the builder

Final crate choices after spikes, the exact cutover-unit mapping, contract
normalisation rules, CI provider details, and lane slicing inside Phase 2–3,
all within the constraints above.
