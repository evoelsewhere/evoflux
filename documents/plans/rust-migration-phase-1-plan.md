# EvoFlux v4 Phase 1 (Pilot) Implementation Plan

> **For agentic workers (any AI tool or person):** Pick an unclaimed task whose
> dependencies have landed (see the wave table), claim it and land it as
> [rust-migration-execution.md](rust-migration-execution.md) describes (no PRs;
> local review by the other pool), and work it step by step. Steps use checkbox
> (`- [ ]`) syntax for tracking. Claude Code users: REQUIRED SUB-SKILL:
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** The first units with no shared in-memory state (`edge-stateless`,
`observability`, then `import` if the owner clears it) are served by Rust in
real daily use, each after contract tests, a shadow or replay comparison, an
owner-approved cutover and a 24 h watch. The Phase 0 exit-report items those
cutovers need are closed first.

**Architecture:** Each lane is one crate `server/crates/area-<lane>` exposing
`router(state)`. The `evoflux-server` binary mounts every area router behind
the gateway (T6); `server/routing.toml` decides per unit whether a request goes
to Python, to Rust, or to Python with a Rust shadow. A cutover flips one
unit's `owner` to `rust`. The gateway then derives `EVOFLUX_DISABLE_SERVICES`
for the unit's Python lifespan services and starts the Rust equivalents.
Rollback is `EVOFLUX_ROUTE_OVERRIDE=<unit>=python` and an app restart.

**Tech Stack:** as Phase 0 (tokio, axum 0.8, hyper 1, `core::db`, tracing,
metrics, utoipa); pytest + httpx contract tests; GitHub Actions.

**Spec:** [rust-migration-design.md](rust-migration-design.md) §3, §3.4, §6,
§7, §8; [ADR 0001](../architecture/decisions/0001-rust-migration-python-calls-rust.md);
[`server/AGENTS.md`](../../server/AGENTS.md) (lane loop §2, rules §3–§6);
[rust-migration-execution.md](rust-migration-execution.md) (landing, budget,
model ladder); [Phase 0 exit report](../analysis/phase-0-exit-report-2026-10-31.md).

## Scope decisions

| Unit | Phase 1? | Why |
|---|---|---|
| `edge-stateless` (lanes `health-live`, `quote`, `commands`, `snippets`) | **yes**, first cutover | pin `none`. Python's in-process `parse_slash_invocation` (`app/agent/mode/team/team.py`, `app/api/routes/team/chat.py`) only reads the same command files, so no adapter is needed. |
| `observability` (lane `observability`, service `otel_retention`) | **yes**, second cutover | pin `none`; GET-only, so it can use live shadow; writers stay file based |
| `import` (lane `imports`) | **port and replay yes; cutover only if Q3 allows** | pin `none`, but `CUTOVER_UNITS.md` lists it as phase 2, and `execute`/`undo`/`auto-sync` write files owned by Phase 2 units: agents and skills dirs, `mcp.json`, `wiki/sources/` and runtime settings `import_auto_sync`. The `_import_jobs` preview dict is route-local and moves with the unit. |
| `remote-access` | **no, Phase 2** | pin `adapter:remote-access`: `desktop_auth` calls `remote_use_service.claim`, and the embedded tailnet manager is a Python-owned child process. |
| WebSocket auth port | **no, later phase** | no pilot unit has a WebSocket route |
| Tailnet (remote claim) for Rust HTTP routes | **T8, gated by Q2** | without it, every cut-over route answers `403 remote_route_unavailable` to remote clients (`server/crates/server/src/app.rs` `refuse_tailnet`) |

## Global Constraints

- Landing per the execution doc: claim the row, `wip/<agent>/p1-<task>` cut
  from `migrate/rust-v4`, test first, local review by the other pool until
  `APPROVE`, `--ff-only` land, add a row to `server/LANDED.md`. Never push `wip/*`; never force-push.
- Every commit adds to `CHANGELOG.md` `## [Unreleased]`. Conventional Commits
  with lane scopes (`feat(rust/quote): …`, `test(contract/quote): …`). **No AI trailers.**
- Lane tasks touch only their board row's `owned_paths`
  (`python scripts/migration/check_paths.py <lane>`). Edits to `server/crates/server/**`,
  `contract-tests/{conftest,backends,normalize}.py`, CI, `gates.sh` and
  `routing.toml` are shared tasks.
- **New crate dependency:** the lane stops (workflow §9) and lists it in
  `NOTES.md`. The orchestrator lands it as a `chore(shared)` commit after `cargo deny check`.
- `routing.toml` is changed **only** by a cutover task (`CO*`). Shadow is set at
  runtime with `EVOFLUX_ROUTE_OVERRIDE=<unit>=shadow` and never committed.
- At most **one unit in its 24 h watch** at a time, so a regression points at one unit.
- First cutover (CO1) needs the owner's approval of the Phase 0 exit report,
  including the half-day of daily use on the packaged build (T5).
- Rust gates per change: `cargo fmt --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo nextest run --workspace`, `bash scripts/migration/gates.sh <area>`.
  Python: no new failures against the base (`scripts/migration/python_gate_baseline.sh`).
- Values: `/api/health/live` p99 < 50 ms and max < 1 s under every
  responsiveness scenario. Perf limit per endpoint is
  `max(1.1 × p99, p99 + floor_ms)` from `baseline-v3.1.1.json`. Shadow and
  replay need zero unexplained diffs, judged against a Python-vs-Python noise pass.
- Health (`/api/health/live`) never touches the DB writer, the read pool or any area lock (design §6.3).
- Models per [execution doc](rust-migration-execution.md#usage-budget-owner-decision-2026-10-30):
  at most **2 implementers per pool** at once. The reviewer is the other pool's
  cheapest capable model. Desktop Opus also reviews T4 (db), T6 (gateway) and T8 (auth).

## Review Focus

1. **Rollback is one switch.** With a unit `rust`, restarting with
   `EVOFLUX_ROUTE_OVERRIDE=<unit>=python` sends every route back to Python and
   re-enables its Python services. Each `CO*` task tests this.
2. **Services never run twice.** With `observability=rust`, Python's log shows
   `otel_retention` skipped and Rust's retention task runs once. With the override, it is the reverse (CO2).
3. **Shadow never reaches the client.** A Rust panic, timeout or 5xx in shadow
   still returns Python's response. A shadow override on a unit with a non-GET
   operation stops `serve` at startup (T6).
4. **Remote clients.** On a Rust route, a request carrying tailnet identity
   gets the same claim outcome as on a Python route (T8), or Q2 accepts the
   documented `403` for the pilot.
5. **Cross-unit writes (imports).** Rust writes that Python caches read
   (skills, MCP, wiki, settings) are revalidated, or the cutover waits (Q3).

---

## Owner decisions (2026-10-31)

- **Q1:** yes. POST render routes (commands, snippets) are checked by a dual-backend replay (T7) instead of live shadow; GET routes still get live shadow.
- **Q2:** port first. T8 (remote claim on Rust routes) runs, and CO1 waits for it.
- **Q3:** wait. `import` is ported and replay-checked in Phase 1, but SH3/CO3/WA3 move to Phase 2, together with the units that cache its files.
- **Q4:** yes. `remote-access` stays on Python through Phase 1.

## Waves and dependencies

Waves are dependency layers, not timeboxes: a task starts when its "needs" have
landed and its pool has a free slot (≤ 2 implementers per pool).

| Wave | Claude CLI (≤ 2) | Codex (≤ 2) | Needs landed |
|---|---|---|---|
| 1 | T1 board · T2 CI and gates | T6 units and shadow in `serve` · T4 db metrics | — |
| 2 | L1a health-live · L2a quote | T7 replay diff and `TARGET=rust` · T8 remote claim (Q2) | L\*a ← T1 · T8 ← T6 |
| 3 | L3a commands · L4a snippets | L1b · L2b | L\*b ← own L\*a, T6, T7 |
| 4 | L5a observability · T5 packaged build | L3b · L4b | — |
| 5 | L6a imports · T3 cross-OS evidence | L5b observability | T3 ← T2 landed and one push run |
| 6 | SH1 edge-stateless replay · SH2 observability shadow | L6b imports | SH1 ← L1b–L4b, T7 · SH2 ← L5b, T6 |
| 7 | CO1 → WA1 (edge-stateless), then CO2 → WA2 (observability) | — | CO1 ← SH1, T2, T5, T8 or Q2, owner Phase 0 approval · CO2 ← SH2, WA1 |
| 8 | SH3 imports replay → CO3 → WA3 (only if Q3 allows) · T9 Phase 1 exit | — | SH3 ← L6b, T7 · CO3 ← SH3, WA2, Q3 · T9 ← WA2 (and WA3 if run) |

## Assignments

Model names follow the execution doc's ladder. Reviews are local (`git diff
migrate/rust-v4...HEAD`) with the execution doc's review prompt, pointing at
this plan's task.

| Task | Assignment | Reviewer | Depends on |
|---|---|---|---|
| T1 board and units for Phase 1 | Claude CLI **Haiku** | Codex Luna/low | — |
| T2 CI on pushes, cross-OS contract job, cutover gates | Claude CLI **Sonnet** | Codex Luna/low | — |
| T3 Linux/macOS evidence | Claude CLI **Haiku** | Codex Luna/low | T2 + one push run |
| T4 db metrics on T7 telemetry | Codex **Terra/medium** | Claude CLI Sonnet + desktop Opus | — |
| T5 packaged build with web UI | Claude CLI **Sonnet** | Codex Luna/low | — |
| T6 `serve` hosts area units; shadow wiring | Codex **Terra/high** | Claude CLI Sonnet + desktop Opus | — |
| T7 dual-backend replay; `TARGET=rust` override | Codex **Terra/medium** | Claude CLI Sonnet | — |
| T8 remote claim on Rust routes (Q2) | Codex **Terra/high** | Claude CLI Sonnet + desktop Opus | T6 |
| L1a/L2a/L3a/L4a/L5a/L6a crate, NOTES, contract tests | Claude CLI **Sonnet** | Codex Luna/low | T1 |
| L1b health-live Rust | Codex **Luna/low** | Claude CLI Sonnet | L1a, T6, T7 |
| L2b/L3b/L4b/L5b/L6b Rust | Codex **Terra/medium** | Claude CLI Sonnet | own La, T6, T7 |
| SH1/SH2/SH3 shadow or replay run | Claude CLI **Sonnet** | Codex Luna/low | see waves |
| CO1/CO2/CO3 cutover flip | Claude CLI **Haiku** | Codex Luna/low; **owner approves** | see waves |
| WA1/WA2/WA3 24 h watch | Claude CLI **Haiku** (log) · owner (use) | Codex Luna/low | own CO |
| T9 Phase 1 exit report | Claude CLI **Sonnet** | Codex Luna/low; owner | WA2 (+ WA3) |

**Queue per pool:**
- **Claude CLI:** T1 → T2 → L1a → L2a → L3a → L4a → L5a → T5 → L6a → T3 → SH1 → SH2 → CO1 → WA1 → CO2 → WA2 → SH3 → (CO3 → WA3) → T9
- **Codex:** T6 → T4 → T7 → T8 → L1b → L2b → L3b → L4b → L5b → L6b; then reviews

## File structure

```text
server/Cargo.toml                                  # members = ["crates/*"] (T6)
server/crates/server/src/{units.rs,serve.rs,app.rs}  (T6, T8; one mount line per SH task)
server/crates/api-types/src/{health_live,quote,commands,snippets,observability,imports}.rs   (stubs T6, filled by lanes)
server/crates/area-{health-live,quote,commands,snippets,observability,imports}/
  Cargo.toml  NOTES.md  src/{lib,routes,service,store}.rs  tests/
server/crates/core/src/{db/metrics.rs,telemetry.rs}                    (T4)
server/crates/core/src/remote_claim.rs                                 (T8)
contract-tests/{health-live,quote,commands,snippets,observability,imports}/   (L*a)
contract-tests/backends.py  contract-tests/conftest.py                 (T7)
scripts/migration/{replay_diff.py,gates.sh}  .github/workflows/migration-gates.yml   (T7, T2)
scripts/build_sidecar.py  Makefile                                     (T5, T7)
documents/analysis/phase-1-{cross-os-run,packaged-build,shadow-<unit>,exit-report}-<date>.md
```

---

### Task T1: Board and units for Phase 1

**Files:** Modify `server/MIGRATION_BOARD.md`, `server/CUTOVER_UNITS.md` (phase column only).

- [ ] **Step 1:** Run `uv run python scripts/migration/check_board.py` (baseline PASS).
- [ ] **Step 2:** Set `health-live`, `quote`, `commands`, `snippets` and
  `observability` from `blocked:phase-0` to `open`. The exit report says
  Phase 1 lanes were opened, but these rows were missed. Set `remote-access`
  to `blocked:phase-2` (scope table).
- [ ] **Step 3:** Add rows `p1-t2` … `p1-t9` (unit `none`) with each task's Files as `owned_paths`.
- [ ] **Step 4:** After Q3, set `import`'s phase in `CUTOVER_UNITS.md` to `1` (cutover allowed) or leave it at `2`.
- [ ] **Step 5:** `check_board.py` and `uv run pytest tests/scripts/test_check_board.py -q` PASS.
  Commit `docs(shared): open Phase 1 pilot lanes on the migration board`.

### Task T2: CI on pushes, cross-OS contract job, cutover gates

**Files:** Modify `.github/workflows/migration-gates.yml`, `scripts/migration/gates.sh`. Test: `tests/scripts/test_gates_sh.py`.

**Interfaces:**
- `gates` job runs on `push` to `migrate/rust-v4` as well as PRs. For pushes,
  the area is `shared` and the diff base is `github.event.before`
  (`HEAD^` when it is all zeros).
- New `contract` job on `ubuntu-latest`, `macos-latest`, `windows-latest`
  (push and PR): `uv sync --group contract`, `cargo build -p evoflux-server`,
  `make contract-all TARGET=gateway`. It uploads the `pytest` junit file as an artifact.
- `gates.sh cutover-<unit>`: runs the shared gates plus `check_paths.py cutover-<unit>`
  and `make contract-all TARGET=gateway`. It skips the per-crate
  `evoflux-area-*` nextest, mutants and OpenAPI steps, which `cutover-*` would
  otherwise run against a crate that doesn't exist.
- `GATES_DRY_RUN=1` prints the step names instead of running them (for the test).

- [ ] **Step 1: Failing test** `test_gates_sh.py`: `GATES_DRY_RUN=1 bash gates.sh cutover-edge-stateless`
  lists `check_paths cutover-edge-stateless` and `contract-all gateway` and no `evoflux-area-cutover`.
  `GATES_DRY_RUN=1 bash gates.sh quote` lists `nextest evoflux-area-quote` and `mutants`.
- [ ] **Step 2:** `uv run pytest tests/scripts/test_gates_sh.py -q` → FAIL. Implement. → PASS.
- [ ] **Step 3:** `actionlint` (if installed) on the workflow; `bash scripts/migration/gates.sh shared` PASS.
- [ ] **Step 4:** Commit `ci(shared): run migration gates and contract suite on pushes to migrate/rust-v4`.

### Task T3: Linux/macOS evidence

**Files:** Create `documents/analysis/phase-1-cross-os-run-<YYYY-MM-DD>.md`.

- [ ] **Step 1:** After T2 lands, take the first push run (`gh run list --branch migrate/rust-v4 --workflow "Migration gates"`).
- [ ] **Step 2:** Record per OS: gates, `contract-all TARGET=gateway`, `db-compat`
  (when triggered), and the result of `supervisor::test_kill_gateway_kills_python_tree`
  (the POSIX process-group hard-kill item).
- [ ] **Step 3:** Write each Linux/macOS failure as one line: test id, OS and
  the first error line. The orchestrator turns each one into a fix brief; this
  task does not fix them. Commit `docs(analysis): record Phase 1 cross-OS CI run`.

### Task T4: Database metrics on the T7 telemetry

**Files:** Modify `server/crates/core/src/db/metrics.rs`, `server/crates/core/src/telemetry.rs`. Test: `server/crates/core/tests/db.rs`.

**Interfaces:**
- `EVOFLUX_db_pool_wait_seconds` (histogram, labels `lane`, `route`, the 13
  `WAIT_BUCKETS`), `EVOFLUX_db_pool_timeouts_total`,
  `EVOFLUX_db_concurrent_conflicts_total`, `EVOFLUX_db_concurrent_retries_total`
  and `EVOFLUX_db_wal_checkpoints_total` are emitted through the `metrics`
  facade. `telemetry::install_metrics()` sets the bucket list for the wait
  histogram. `telemetry::render_prometheus()`, and so `/metrics/gateway`,
  includes them. Names, labels and buckets stay those of `app/core/metrics.py`.
- `Db::metric(name, labels) -> f64` stays (existing tests read it). `Db::render_metrics()` is removed or delegates to telemetry; no caller outside tests.

- [ ] **Step 1: Failing tests:** `db_timeout_shows_in_render_prometheus` (force a read-pool admission timeout → the rendered text has `EVOFLUX_db_pool_timeouts_total{lane="read",route="…"} 1`), `pool_wait_histogram_uses_python_buckets`.
- [ ] **Step 2:** `cargo nextest run -p evoflux-core` → FAIL. Implement. → PASS; `bash scripts/migration/gates.sh shared` PASS.
- [ ] **Step 3:** Commit `feat(rust/core): export database metrics through the shared telemetry`.

### Task T5: Packaged build with the web UI

**Files:** Modify `scripts/build_sidecar.py`, `Makefile` (target `package`). Test: `tests/scripts/test_build_sidecar_web.py`. Create `documents/analysis/phase-1-packaged-build-<YYYY-MM-DD>.md`.

**Interfaces:**
- `build_sidecar.py` builds the web UI (`bun install --frozen-lockfile && bun run build` in `web/`)
  when `web/dist/index.html` is missing. `--no-build-web` keeps today's
  `web bundle missing` error.
- `make package` = web build → `build_sidecar.py` → Tauri bundle build (the command in `desktop/AGENTS.md`).

- [ ] **Step 1: Failing test:** with `web/dist` absent and the build command
  stubbed, `main([])` calls the web build once. `main(["--no-build-web"])` exits 1
  with `web bundle missing: web/dist/index.html`.
- [ ] **Step 2:** FAIL → implement → PASS. Run `make package` on Windows.
- [ ] **Step 3:** The report has the installer path and size, the version, and
  whether it installs, starts (handshake through `evoflux-server`) and loads the UI. It hands the
  build to the owner for the exit report's half-day checklist. Commit
  `build(shared): build the web UI as part of the packaged sidecar`.

### Task T6: `serve` hosts area units; shadow wiring

**Files:** Modify `server/Cargo.toml` (`members = ["crates/*"]`), `server/crates/server/{Cargo.toml,src/serve.rs,src/app.rs}`, `server/crates/api-types/src/lib.rs`. Create `server/crates/server/src/units.rs`, `server/crates/api-types/src/{health_live,quote,commands,snippets,observability,imports}.rs` (empty modules). Test: `server/crates/server/tests/units.rs`.

**Interfaces:**
- `units::UnitState { settings: Arc<Settings>, paths: Arc<Paths>, db: Option<Db> }` (`Clone`).
  The DB opens (`DbOptions` from env) only if a mounted area declares it needs it.
- `units::router(state: &UnitState) -> axum::Router`. It merges each area
  crate's `router(state)` and is empty when T6 lands; each `SH*` task adds one line.
- `units::start_rust_services(table: &RoutingTable, state: &UnitState, cancel: CancellationToken) -> Vec<JoinHandle<()>>`.
  It starts a Rust service only when its unit's owner is `rust`, using the names in
  `routing.toml` `services`; empty when T6 lands.
- `serve` startup, after `RoutingTable::from_toml(…, EVOFLUX_ROUTE_OVERRIDE)`:
  `table.check_shadow_get_only(&openapi_operations(PYTHON_OPENAPI)?)` with
  `PYTHON_OPENAPI` embedded from `contract-tests/openapi/python-v3.1.1.json`.
  If it fails, `serve` exits with `EXIT_STARTUP` and stderr `routing table: <error>`.
- `serve` builds the proxy with `proxy::router_with(table, sup, units, GatewayOptions::from_env(state_dir))`.
- The Python child env adds `EVOFLUX_GATEWAY_URL=http://127.0.0.1:<port>` and
  `EVOFLUX_RUST_UNITS=<rust-owned units, comma-separated>` (ADR 0001 rule 3; nothing reads them yet).

- [ ] **Step 1: Failing tests:**
  `shadow_override_on_get_only_unit_starts` (`observability=shadow`),
  `shadow_override_on_mixed_unit_exits_startup` (`edge-stateless=shadow` → `EXIT_STARTUP`; stderr names `POST` and `/api/commands/`),
  `rust_owned_unit_dispatches_to_units_router` (test area router + `test-unit=rust`),
  `shadow_unit_writes_jsonl_through_serve` (fake Python vs a differing test route → one line in `<state_dir>/shadow/<unit>.jsonl`; the client gets Python's body),
  `python_env_lists_rust_units`.
- [ ] **Step 2:** `cargo nextest run -p evoflux-server` → FAIL. Implement. → PASS; `make contract-all TARGET=gateway` PASS.
- [ ] **Step 3:** Commit `feat(rust/server): mount area units and wire shadow mode into serve`.

### Task T7: Dual-backend replay and `TARGET=rust` unit override

**Files:** Modify `contract-tests/backends.py`, `contract-tests/conftest.py`, `Makefile` (`replay-diff`). Create `scripts/migration/replay_diff.py`. Test: `tests/scripts/test_replay_diff.py`, `tests/scripts/test_contract_rust_override.py`.

**Interfaces:**
- `TARGET=rust` sets `EVOFLUX_ROUTE_OVERRIDE=<unit>=rust` for the area's unit
  (lane → unit from `MIGRATION_BOARD.md`, resolved in `conftest.py` from the
  test's folder). `TARGET=gateway` is unchanged (committed routing).
- `replay_diff.py <unit> --recordings <dir> --out <dir> [--noise]` starts
  `python` and `rust` backends on separate copies of the same fixture DB and
  config. It replays the unit's recorded requests, all methods and in recorded
  order, against both, and normalizes with `contract-tests/normalize.py`. It
  writes `<out>/<unit>-replay.jsonl` and prints `compared`, `equal` and
  `diff` counts. It exits 1 on a diff not listed in `KNOWN_DIFFERENCES.md`.
  `--noise` replays Python against Python.
- `make replay-diff UNIT=<unit> RECORDINGS=<dir> OUT=<dir> [NOISE=1]`.

- [ ] **Step 1: Failing tests** with fake backends: equal responses → exit 0;
  one differing body → exit 1 and one JSONL line; a diff listed in
  `KNOWN_DIFFERENCES.md` → exit 0; non-unit paths in the recording are
  skipped. `test_contract_rust_override`: `contract-tests/quote` under
  `TARGET=rust` gets `EVOFLUX_ROUTE_OVERRIDE=edge-stateless=rust`.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `test(contract): add dual-backend replay diff and per-unit rust target`.

### Task T8: Remote claim on Rust routes (only if Q2 = port)

**Files:** Create `server/crates/core/src/remote_claim.rs`, `server/crates/core/tests/remote_claim.rs`, `contract-tests/gateway/test_remote_claim.py`. Modify `server/crates/core/src/lib.rs`, `server/crates/server/src/app.rs`.

**Interfaces:**
- Port of `app/services/remote_use_service.py::claim` and the two call sites in
  `app/core/desktop_auth.py` (about lines 293–310 and 367–375):
  `remote_claim::claim(db: &Db, login: &str, device_label: Option<&str>) -> Result<(), ClaimError>`.
  It does the same row read/write on the same table, in a `db.write` closure
  with ids and timestamps made outside. `ClaimError::Conflict` renders Python's
  status and body for `RemoteUseConflict`.
- `app::rust_routes` replaces `refuse_tailnet` with a claim check for HTTP.
  WebSocket upgrades on Rust routes keep the `403 remote_route_unavailable` refusal.

- [ ] **Step 1: Failing tests:** Rust `claim_first_device_then_conflict`,
  `claim_same_device_idempotent`. Contract (`TARGET=gateway`, with a test unit
  set to `rust`): the same tailnet headers give the same status and body on a
  Python route and a Rust route, for a first claim, a repeat claim and a
  second-device conflict.
- [ ] **Step 2:** FAIL → implement → PASS; `bash scripts/migration/gates.sh shared`.
- [ ] **Step 3:** Commit `feat(rust/core): honour the remote device claim on Rust routes`.

---

## Lane tasks

Every lane runs the same two tasks, following the lane loop (`server/AGENTS.md`
§2 steps 2–6). The table after this section gives each lane's specifics.

### Lane task `La`: area crate, NOTES and contract tests

**Files:** `server/crates/area-<lane>/{Cargo.toml,NOTES.md,src/lib.rs}` (a
`router()` stub returning an empty `Router`), `contract-tests/<lane>/**`.

- [ ] **Step 1: Study.** Write `NOTES.md` as `server/AGENTS.md` §2 step 2 asks:
  endpoints, state, files, side effects, odd behaviour and the **test map**
  (every Python test for the area → contract case, Rust unit test or `n/a: <reason>`).
  Add a **pins check**: every caller of the area's service outside its routes
  (`rg` for the service module), and each one marked "reads the same files /
  DB, no adapter" or "needs adapter" (if it needs one, stop: §9).
- [ ] **Step 2: Contract tests** to the §5.2 minimum per endpoint: success,
  missing or wrong auth, validation failure, each documented error, empty
  state, a pagination boundary where paginated, and concurrent access where it writes.
- [ ] **Step 3:** `make contract AREA=<lane> TARGET=python` PASS. Spot-break
  the Python handler once and see a test fail (§5.3), then revert.
- [ ] **Step 4:** Commit `test(contract/<lane>): cover every <lane> endpoint against v3`.

### Lane task `Lb`: Rust implementation

**Files:** `server/crates/area-<lane>/**`, `server/crates/api-types/src/<lane>.rs`.

**Interfaces:** `pub fn router(state: UnitState) -> axum::Router` in `lib.rs`.
`routes.rs` handles transport, `service.rs` the port, and `store.rs` (only if
the lane touches the DB) uses `core::db` only. A lane with a lifespan service
also exposes `pub fn spawn_<service>(state: UnitState, cancel: CancellationToken) -> JoinHandle<()>`.
utoipa annotations make `openapi_diff.py <lane>` match Python.

- [ ] **Step 1:** Port the test map's Rust unit tests first; `cargo nextest run -p evoflux-area-<lane>` → FAIL.
- [ ] **Step 2:** Implement until the unit tests and
  `make contract AREA=<lane> TARGET=rust` PASS, and `TARGET=python` still passes.
- [ ] **Step 3:** `bash scripts/migration/gates.sh <lane>` (clippy, nextest,
  `cargo mutants --in-diff` with no survivors, OpenAPI diff, check_paths).
  Run `make perf AREA=<lane> TARGET=rust` for endpoints in the baseline; list the others in `NOTES.md` for the SH task.
- [ ] **Step 4:** Self re-review against §6 with the Python source side by side. Commit `feat(rust/<lane>): port <lane> routes`.

### Lane specifics

| ID | Lane (unit) | Endpoints | Python sources | Points that need care |
|---|---|---|---|---|
| L1a/L1b | `health-live` (edge-stateless) | `GET /api/health/live` | `app/api/routes/health.py` (`health_live` only) | No DB, no lock, no `await` on shared state. Must keep `make perf-responsiveness TARGET=rust` green, including the scenarios that are `xfail` for Python. `/ready` and `/diagnostics` stay in `health-diagnostics`. |
| L2a/L2b | `quote` (edge-stateless) | `GET /api/quote` | `app/api/routes/quote.py`, `app/services/quote_service.py` | Date-based choice: assert that Python and Rust give the same quote on the same day, and test the day boundary with a Rust unit test on an injected clock. |
| L3a/L3b | `commands` (edge-stateless) | `GET /api/commands`, `POST /api/commands/{name:path}/render` | `app/api/routes/commands.py`, `app/services/commands.py` | Built-in `init` command, frontmatter regex, `{name:path}` with slashes, discovery order and precedence. Python `parse_slash_invocation` stays in-process (no adapter); NOTES records why. |
| L4a/L4b | `snippets` (edge-stateless) | `GET /api/snippets`, `POST /api/snippets/{name:path}/render` | `app/api/routes/snippets.py`, `app/services/snippets.py` | Same discovery and render rules as commands; an unknown snippet's 404 body. |
| L5a/L5b | `observability` | `GET /api/observability/summary?days=1..90`, `GET /api/observability/traces`, `GET /api/observability/traces/{trace_id}` | `app/api/routes/observability.py`, `app/services/observability_service.py`, `app/core/otel_retention.py` | Contract fixture: a committed, scrubbed OTel JSONL set under `contract-tests/observability/fixtures/`. `days` 0 and 91 → Python's 422 body. Rust `spawn_otel_retention` uses the same interval, age and file selection as `otel_retention.py`, with a Rust unit test on a temp dir. |
| L6a/L6b | `imports` (import) | `GET /scan`, `GET`/`PUT /auto-sync`, `POST /detect`, `GET /preview/{import_id}`, `PATCH /preview/{import_id}/items/{item_index}`, `PATCH /preview/{import_id}/items`, `POST /execute/{import_id}`, `DELETE /{import_id}`, `GET /history`, `GET /history/{job_id}`, `POST /history/{job_id}/undo` (all under `/api/import`) | `app/api/routes/import_route.py`, `app/services/import_service.py`, `app/services/importers/**`, `app/models/import_job*.py` | NOTES must list every cross-unit write (agents and skills dirs, `mcp.json` with masked sensitive keys, `wiki/sources/`, runtime settings `import_auto_sync`, session rows) and say which Python cache reads each one; that answers Q3. Fixtures for each importer (`chatgpt`, `claude_code`, `claude_web`, `codex`, `cursor`, `generic`, zip). Concurrent `execute` of one `import_id`. Undo restores files byte for byte. `_import_jobs` becomes Rust state in the crate. |

---

## Unit tasks: shadow or replay, cutover, watch

### SH1 / SH2 / SH3: shadow or replay run

**Files:** Modify `server/crates/server/{Cargo.toml,src/units.rs}` (mount the
unit's area crates; SH2 also registers `otel_retention` in
`start_rust_services`). Create `documents/analysis/phase-1-shadow-<unit>-<YYYY-MM-DD>.md`.
New diffs that are explained go to `server/KNOWN_DIFFERENCES.md` (owner-approved) or back to the lane as a fix.

- [ ] **Step 1:** Mount the crates. `make contract-all TARGET=gateway` stays
  green with committed routing (still Python).
- [ ] **Step 2: Record.** Use the app (dev or packaged build) for at least
  half a day with `EVOFLUX_GATEWAY_RECORD_DIR` set, then run
  `make scrub FILE=…` on each recording.
- [ ] **Step 3: Compare.**
  - **SH2 (observability, GET-only):** run with `EVOFLUX_ROUTE_OVERRIDE=observability=shadow`
    and `EVOFLUX_SHADOW_PYTHON_TWICE=1`, then `make shadow UNIT=observability …`.
  - **SH1 (edge-stateless) and SH3 (import), which have POST, PATCH, PUT or DELETE** (live shadow is refused at startup, T6):
    `make replay-diff UNIT=<unit> …`, then again with `NOISE=1` (per Q1).
- [ ] **Step 4:** Report the request count, equal and diff counts, the noise
  pass, and perf for endpoints missing from the baseline (Python vs Rust on the
  same machine and run). Zero unexplained diffs is required.
  Commit `test(shared): shadow report for <unit>`.

### CO1 / CO2 / CO3: cutover flip

**Files:** Modify `server/routing.toml` (`owner = "rust"` for the unit),
`server/MIGRATION_BOARD.md` (the unit's lane rows). Branch `wip/<agent>/cutover-<unit>`.

- [ ] **Step 1:** Write the cutover note in the commit body: the gate reports,
  the SH report link, and the lanes' pins check. Adapter: CO1 and CO2 `n/a`
  (the NOTES evidence); CO3 per Q3.
- [ ] **Step 2:** Flip the unit. Run `bash scripts/migration/gates.sh cutover-<unit>`
  (T2), `make perf AREA=<lanes> TARGET=gateway` and
  `make perf-responsiveness TARGET=gateway`.
- [ ] **Step 3: Services and rollback.** Start the packaged or dev app and
  check that `EVOFLUX_DISABLE_SERVICES` in the Python child's env equals
  `RoutingTable::disabled_python_services()`. CO2: `otel_retention` is skipped
  in Python's log and the Rust retention task runs. Restart with
  `EVOFLUX_ROUTE_OVERRIDE=<unit>=python`: the routes are served by Python
  again (`X-EvoFlux-Gateway` path log), and the Python services start.
- [ ] **Step 4:** The owner approves the diff locally. Land it, and set the
  lane rows to `merged` (they become `cut-over` after the watch). Commit
  `feat(shared): cut over <unit> to Rust`.

### WA1 / WA2 / WA3: 24 h watch

**Files:** Modify `server/MIGRATION_BOARD.md` (rows → `cut-over`, `gate_report` link), `server/LANDED.md`.

- [ ] **Step 1:** The owner uses the build that has the cutover for 24 h. The
  agent checks `backend.log` and `/metrics/gateway` at the start, at about
  12 h and at the end: 5xx count on the unit's routes, watchdog stalls over
  100 ms, and `remote_request_refused_on_rust_route` (expected only if Q2 accepts it).
- [ ] **Step 2:** Any regression: roll back with the override, write the
  failing contract test first in the lane (a fix task), then repeat CO and WA.
- [ ] **Step 3:** If clean, move the rows to `cut-over` and add a `LANDED.md` line. Commit `docs(shared): record <unit> cutover watch`.

### Task T9: Phase 1 exit report

**Files:** Create `documents/analysis/phase-1-exit-report-<YYYY-MM-DD>.md`.

- [ ] **Step 1:** Collect: the units cut over, the SH and WA results, CI
  status on three OSes (T3 and later pushes), and perf and responsiveness numbers against the baseline.
- [ ] **Step 2:** "Process adjustments" (design §7 Phase 1 gate): what the lane
  template, the shadow/replay step, reviews and the budget cost, and what
  changes for Phase 2 (for example lane size, reviewer model, or the
  dependency intake).
- [ ] **Step 3:** List what is still open for Phase 2: `remote-access`, WebSocket
  auth, `import` if deferred, the warm-history freeze repeat, and the SQLite pin
  security review. Commit `docs(analysis): add Phase 1 exit report`.

---

## Open questions for the owner

- **Q1 Shadow for units with non-GET routes.** `check_shadow_get_only` refuses
  live shadow for `edge-stateless` (POST render) and `import`. Is the
  dual-backend replay (T7) on fixture copies acceptable as their shadow
  evidence? Default: yes.
- **Q2 Remote clients on Rust routes.** Port the remote claim (T8) before
  CO1, or accept `403 remote_route_unavailable` for tailnet clients on
  cut-over routes during the pilot? Default: port it (T8), because the UI over
  remote access calls `/api/commands`, `/api/snippets` and `/api/health/live`.
- **Q3 Import cutover.** Import writes files read by Phase 2 units (skills,
  MCP, wiki, settings), and `CUTOVER_UNITS.md` marks it phase 2. Default: port
  it and run the replay in Phase 1, and cut over only if L6a's NOTES show that
  no Python cache holds those files; otherwise cut it over together with
  `agents-skills`, `plugins-mcp` and `memory-search` in Phase 2.
- **Q4** Confirm that `remote-access` stays in Phase 2 (`adapter:remote-access` pin and the Python-owned tailnet process).
