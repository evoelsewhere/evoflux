# EvoFlux v4 Phase 0 (Foundation) Implementation Plan

> **For agentic workers (any AI tool or person):** Pick an unclaimed task whose
> dependencies are merged (see the wave table), claim it per
> [rust-migration-workflow.md](rust-migration-workflow.md) §2 step 1, and work it
> step by step. Steps use checkbox (`- [ ]`) syntax for tracking. Claude Code
> users: REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans.

**Goal:** EvoFlux runs fully through a new Rust `evoflux-server` gateway that
proxies 100 % of traffic to the unchanged-behaviour Python sidecar, with every
gate, test harness, fixture, database lane and document the later phases need.

**Architecture:** A Cargo workspace under `server/` (crates `core`,
`api-types`, `gateway`, `server`) produces the `evoflux-server` binary. Tauri
starts it in place of Python. It starts Python as a child on a private port and
proxies HTTP/SSE/WebSocket to it according to `server/routing.toml` (all
`python` in Phase 0). A black-box pytest suite in `contract-tests/` runs against
Python, Rust or the gateway via `TARGET`.

**Tech Stack:** Rust (tokio, axum 0.8, tower-http 0.7, hyper 1, rusqlite on a
patched libsqlite3-sys with SQLite's `begin-concurrent` branch, tracing,
metrics, process-wrap, utoipa); Python 3.12 + pytest + httpx for contract tests;
GitHub Actions.

**Spec:** [rust-migration-design.md](rust-migration-design.md) and
[rust-migration-workflow.md](rust-migration-workflow.md). Read both before any task.

## Global Constraints

- Base branch: `migrate/rust-v4`. Each task is one branch
  `migrate/shared-p0-<task-slug>` and one PR into `migrate/rust-v4`. All Phase 0
  PRs are owner-reviewed (design §6.2).
- Every commit updates `CHANGELOG.md` `## [Unreleased]` (root `AGENTS.md`
  rule; no exemptions). Conventional Commits. **No AI co-author trailers.**
- Python changes (Task 6 only) pass: `uv run ruff check app/ tests/`,
  `uv run ruff format --check app/ tests/`, `uv run ty check app/`,
  `uv run pytest --no-cov -q`.
- Rust changes pass: `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo nextest run --workspace` on Windows, macOS and Linux.
- Python behaviour stays the reference. Only Task 6 edits `app/`; only Task 12 edits `desktop/`.
- Handshake line, byte-exact: `EVOFLUX_HANDSHAKE ` + JSON `{"port":u16,"pid":u32,"version":String,"token":String}`
  (`desktop/src-tauri/src/sidecar.rs:29-38`, `app/cli/commands/serve.py:199-210`).
- Shell handshake timeouts: 90 s first attempt, 45 s retry (`desktop/src-tauri/src/main.rs:205-206`).
- Busy error, byte-exact: HTTP 503, header `Retry-After: 1`, body
  `{"detail": "Database is busy. Retry the request in a moment.", "code": "database_busy"}`
  (`app/core/exception_handlers.py:123-139`).
- DB rules: WAL only (never `wal2`), `foreign_keys=ON`, 5-connection `query_only`
  read pool, 5 s admission timeout, no schema change, no DDL from Rust.
- Remote-proxy headers: `Tailscale-User-Login`, `X-EvoFlux-Remote-Proxy` (value
  `tsnet`), `X-EvoFlux-Remote-Token`, `X-EvoFlux-Device-Label` (`app/core/desktop_auth.py:193-198`).
- Metric names keep the `EVOFLUX_` prefix used by Python.
- No-panic and no-blocking lints from design §6.1 gates 2–3 apply from the first commit.

## Review Focus

1. **Python dies mid-session.** Requests to Python-owned routes must get a JSON
   `502` (`{"detail": "Backend is restarting.", "code": "backend_unavailable"}`)
   within 1 s, not hang. The gateway restarts Python (max 3 restarts per 5 min,
   backoff 1 s/4 s/10 s). Test in Task 10.
2. **Client disconnects mid-SSE** through the proxy. Python must see the
   disconnect within 2 s, so the agent stream is released. Test in Task 10.
3. **Large uploads stream, not buffer.** A 200 MB upload through the proxy keeps
   gateway RSS growth under 32 MB, and Python's request-size limit still answers
   with its own status and body. Test in Task 10.
4. **Gateway killed hard** (Task Manager / `kill -9`). The Python child and its
   process tree are gone within 5 s on all three OSes (Job Object /
   process group). Test in Task 10.
5. **Slow first start** (big database migrations). The gateway emits its
   handshake only after Python's handshake. It waits up to 85 s on first start
   so it stays under the shell's 90 s, then exits non-zero with the Python log
   tail on stderr. Test in Task 11.

---

## Waves and dependencies

| Wave | Tasks (can run in parallel) | Needs merged |
|---|---|---|
| 1 | T1 freeze diagnosis · T2 workspace + CI · T3 contract harness · T6 Python startup PR · T13 board and docs | — |
| 2 | T4 upgrade fixtures · T5 mock provider · T7 core basics · T8 db lanes · T14 perf harness | T4, T5, T14 ← T3 · T7, T8 ← T2 |
| 3 | T9 db compatibility + stress · T10 gateway proxy + supervisor | T9 ← T8, T4, T3 · T10 ← T7, T6, T3 |
| 4 | T11 server binary · T15 shadow + recording | T10 |
| 5 | T12 desktop launcher · T16 Phase 0 exit check | T12 ← T11 · T16 ← all |

## Assignments (Codex and Claude in parallel)

Each tool works one task at a time, in the order listed in its column. A
task starts only when its dependencies are merged; if the next one is
blocked, take the next unblocked one in your column. **The reviewer is always
the other tool** (workflow §2 step 8). The owner reviews every Phase 0 PR as well.

| Task | Author | Reviewer | Why this split |
|---|---|---|---|
| T1 freeze diagnosis | **Codex** | Claude | shell/profiling work, independent of the rest |
| T2 workspace + CI gates | **Codex** | Claude | Rust toolchain and lint setup; unblocks T7/T8 |
| T3 contract harness | **Claude** | Codex | Python test design; unblocks T4/T5/T10/T14 |
| T6 Python startup PR | **Claude** | Codex | careful edits to v3 auth and lifespan code |
| T13 board, cutover units, routing table | **Claude** | Codex | reading all routes/services and writing the shared docs |
| T4 upgrade fixtures | **Codex** | Claude | scripting across 13 git tags |
| T8 db lanes + begin-concurrent build | **Codex** | Claude | hardest Rust/C build work |
| T7 core basics (auth port) | **Claude** | Codex | parity with Python auth; security-critical |
| T5 mock provider | **Claude** | Codex | builds on T3 |
| T14 perf baseline | **Claude** | Codex | builds on T3 and T1 |
| T10 gateway proxy + supervisor | **Codex** | Claude | critical path; streaming/process Rust |
| T9 db compat + stress + benchmark | **Claude** | Codex | independent check of Codex's T8 |
| T11 server binary + handshake | **Codex** | Claude | continues T10 |
| T15 shadow + recording | **Claude** | Codex | builds on T10 interfaces |
| T12 desktop launcher | **Claude** | Codex | Tauri edits + dev scripts |
| T16 exit check + report | **Claude** (runs) · **Codex** (runs on 2nd OS) | owner | both verify; owner approves |

**Order per tool**
- **Codex:** T2 → T1 → T8 → T4 → T10 → T11 → T16 (second OS)
- **Claude:** T3 → T6 → T13 → T7 → T5 → T14 → T9 → T15 → T12 → T16

Expected flow: Wave 1 runs both columns at once (Codex T2/T1; Claude
T3/T6/T13). Codex starts T8 as soon as T2 merges, while Claude finishes the
Wave 1 docs and T7. T10 (Codex) starts when T7 + T6 + T3 are merged and is
the critical path. Claude fills that time with T5, T14 and T9.

**Kickoff prompt (paste into Codex or Claude Code, replacing `<Tn>` and `<tool>`):**

```text
You are <tool>, working on EvoFlux v4 Phase 0 in this repository.
Read documents/plans/rust-migration-design.md, documents/plans/rust-migration-workflow.md
and documents/plans/rust-migration-phase-0-plan.md (Global Constraints, Review Focus,
and Task <Tn>). Implement Task <Tn> exactly as written, step by step, test first.
Branch: migrate/shared-p0-<slug> from origin/migrate/rust-v4. One PR into
migrate/rust-v4 using the PR template in the workflow doc §7, with the self
re-review checklist filled in. Update CHANGELOG.md in every commit. No AI
co-author trailers. Do not touch files outside the task's Files list. If anything
in the task is ambiguous or blocked, stop and write the question in the PR
(workflow §9) instead of guessing.
```

**Review prompt (for the other tool):**

```text
You are <tool>, the independent reviewer for PR <url> (EvoFlux v4 Phase 0, Task <Tn>).
Read the three plan documents above and the task. Check out the branch, run the
task's verification commands yourself, and review the diff against workflow §6
checklist and the task's Interfaces block. Leave concrete file/line findings with
the expected behaviour. Approve only when every checklist item holds.
```

## File structure

```text
server/
  Cargo.toml                 # workspace, [workspace.lints], [patch.crates-io] libsqlite3-sys
  rust-toolchain.toml  clippy.toml  deny.toml
  vendor/libsqlite3-sys/     # patched copy; sqlite3/ holds the begin-concurrent amalgamation (T8)
  vendor/SQLITE_BRANCH.toml  # pinned tag, upstream check-in hash, sha256 of sqlite3.c (T8)
  lint-fixtures/bad-blocking/  # crate outside the workspace that must FAIL clippy (T2)
  crates/core/src/{lib,config,paths,error,telemetry,auth,watchdog}.rs   (T7)
  crates/core/src/db/{mod,lanes,retry,rowid}.rs                         (T8)
  crates/api-types/src/lib.rs                                           (T2 stub)
  crates/gateway/src/{lib,routing,supervisor,proxy,shadow,record}.rs    (T10, T15)
  crates/server/src/{main,cli,handshake}.rs                             (T11)
  routing.toml  CUTOVER_UNITS.md  MIGRATION_BOARD.md  KNOWN_DIFFERENCES.md  AGENTS.md   (T13)
contract-tests/
  conftest.py  backends.py  normalize.py  sse.py  README.md            (T3)
  health/test_health.py                                                 (T3)
  mock_provider/{server.py,recordings/}                                 (T5)
  fixtures/upgrade/<tag>/{evoflux.db,config/}  fixtures/build_upgrade_fixtures.py   (T4)
  db/test_compat.py  db/two_process_stress.py                          (T9)
  perf/{scenarios.py,test_responsiveness.py,baseline-v3.1.1.json}      (T14)
  gateway/test_proxy.py                                                 (T10)
scripts/migration/{diagnose_freeze.py,gates.sh,check_paths.py,scrub.py}
Makefile                     # new targets: contract, contract-all, gates, perf, shadow, scrub, board
.github/workflows/migration-gates.yml
app/core/gateway_mode.py  app/core/desktop_auth.py  app/api/app.py  app/services/remote_use_service.py   (T6)
desktop/src-tauri/src/sidecar.rs  scripts/build_sidecar.py               (T12)
documents/analysis/v3-freeze-diagnosis-<date>.md                         (T1)
```

---

### Task 1: Freeze diagnosis on v3.1.1

**Files:**
- Create: `scripts/migration/diagnose_freeze.py`
- Create: `documents/analysis/v3-freeze-diagnosis-<YYYY-MM-DD>.md`

**Interfaces:**
- Produces: the named load scenario(s) that reproduce the stall, used by T14
  as `perf/scenarios.py::FREEZE_SCENARIOS`.

- [ ] **Step 1:** Write `diagnose_freeze.py`. It starts v3.1.1 with
  `uv run python -m app.cli serve --host 127.0.0.1 --port 0 --handshake --generate-token`
  and temp `EVOFLUX_*_DIR`s, polls `GET /api/health/live` every 50 ms, and
  runs each candidate load in turn: repository index rebuild on a large repo,
  a long shell tool run, 20 concurrent history-page reads, an MCP server that
  never answers, and a large PDF intake. When a `live` probe takes over 1 s it
  runs `py-spy dump --pid <pid>` and saves the output.
- [ ] **Step 2:** Run it on Windows (the owner's platform) and on one other OS.
  Expected: a JSON summary per scenario with max/p99 `live` latency and the
  stack dumps for any stall.
- [ ] **Step 3:** Write the analysis doc. It names the blocking call sites seen in
  the stacks (or states that no stall reproduced), the scenarios that trigger
  them, and whether the event-loop hypothesis in design §1 holds.
- [ ] **Step 4:** Commit: `docs(analysis): diagnose v3.1.1 UI stalls`.

### Task 2: Rust workspace skeleton and CI gates

**Files:**
- Create: `server/Cargo.toml`, `server/rust-toolchain.toml`, `server/clippy.toml`, `server/deny.toml`
- Create: `server/crates/{core,api-types,gateway,server}/{Cargo.toml,src/lib.rs or main.rs}` (empty stubs)
- Create: `server/lint-fixtures/bad-blocking/{Cargo.toml,src/lib.rs}`
- Create: `scripts/migration/gates.sh`, `scripts/migration/check_paths.py`
- Create: `.github/workflows/migration-gates.yml`
- Modify: `Makefile` (add `gates` target), `.gitignore` (`server/target/`)

**Interfaces:**
- Produces: `make gates AREA=<name>` → runs `scripts/migration/gates.sh <name>`;
  exit 0 only when every gate passes. Workspace lint table that all crates
  inherit with `[lints] workspace = true`.

- [ ] **Step 1: Write the failing lint fixture.** `bad-blocking/src/lib.rs`
  contains one `async fn` that calls `std::thread::sleep`, one that calls
  `std::fs::read`, one `.unwrap()`, and one `std::process::Command::new`.
- [ ] **Step 2: Run** `cargo clippy --manifest-path server/lint-fixtures/bad-blocking/Cargo.toml -- -D warnings`.
  Expected before config: PASS (no lints yet). That is the failure to fix.
- [ ] **Step 3: Configure lints.** In `[workspace.lints.clippy]` deny `unwrap_used`, `expect_used`, `panic`,
  `indexing_slicing`, `todo`, `unimplemented`, `await_holding_lock`,
  `disallowed_methods`. `clippy.toml` `disallowed-methods` lists
  `std::thread::sleep`, `std::fs::read`, `std::fs::read_to_string`,
  `std::fs::write`, `std::fs::File::open`, `std::fs::File::create`,
  `std::process::Command::new`, `std::net::TcpStream::connect`, each with the
  reason `"blocks the async runtime; use tokio or core::blocking"`.
  `[workspace.lints.rust]` sets `unsafe_code = "forbid"`. The fixture reuses
  the same `clippy.toml` through a relative copy step in `gates.sh`.
- [ ] **Step 4: Run** the fixture clippy again. Expected: FAIL, naming all four
  call sites. `gates.sh` asserts this failure (the "gates can fail" check).
- [ ] **Step 5: `check_paths.py <area>`** reads `server/MIGRATION_BOARD.md` (T13 format) and
  the PR diff (`git diff --name-only origin/migrate/rust-v4...HEAD`). It
  exits 1 listing any path outside the area's owned paths. `<area>=shared`
  allows everything but prints the list for the reviewer.
- [ ] **Step 6: CI** `migration-gates.yml` runs on pull requests to `migrate/rust-v4`, on
  `ubuntu-latest`, `macos-latest` and `windows-latest`: fmt, clippy, the lint
  fixture check, `cargo nextest run --workspace`, `cargo deny check`, and
  `check_paths.py` with the area taken from the branch name
  (`migrate/<area>` or `migrate/shared-*` → `shared`).
- [ ] **Step 7: Lane-only gates in `gates.sh`** (skipped for `AREA=shared`):
  `cargo mutants --in-diff <diff> --package evoflux-area-<area>` (must report no
  surviving mutants in changed code, workflow §5.3), and the OpenAPI diff
  `scripts/migration/openapi_diff.py <area>` from Task 3.
- [ ] **Step 8: Run** `make gates AREA=shared` locally. Expected: PASS on the stub workspace.
- [ ] **Step 9:** Commit: `chore(shared): add Rust server workspace and migration gates`.

### Task 3: Contract test harness

**Files:**
- Create: `contract-tests/{conftest.py,backends.py,normalize.py,sse.py,README.md}`
- Create: `contract-tests/health/test_health.py`
- Modify: `Makefile` (targets `contract`, `contract-all`), `pyproject.toml` (dev dependency group `contract`: `pytest`, `httpx`, `httpx-sse`; already-present ones reused)

**Interfaces:**
- Produces:
  - `backends.start_backend(target: Literal["python","rust","gateway"], data_dir: Path, db_fixture: Path | None) -> Backend`
  - `Backend.base_url: str`, `Backend.token: str`, `Backend.pid: int`, `Backend.stop() -> None`, `Backend.log_tail() -> str`.
    It reads the `EVOFLUX_HANDSHAKE` line. `python` runs the v3 CLI `serve`;
    `rust`/`gateway` run `server/target/debug/evoflux-server serve` (T11).
  - Fixture `backend` (function-scoped, fresh temp `EVOFLUX_DATA_DIR`,
    `EVOFLUX_CONFIG_DIR`, `EVOFLUX_STATE_DIR`, optional fixture DB copy) and
    `client` (`httpx.Client` with the bearer token).
  - `normalize.normalize(obj: Any, rules: NormalizeRules = DEFAULT) -> Any`.
    It replaces UUIDs with `<uuid:N>` (stable numbering per response),
    ISO-8601 timestamps with `<ts>`, and sorts lists only where a rule names the JSON path.
  - `sse.collect_events(client, url, *, until: Callable[[Event], bool], timeout_s: float) -> list[Event]`,
    with `Event = (event: str, data: Any)`, and `sse.assert_same_sequence(a, b)`.
  - Env: `TARGET` (default `python`), `AREA` (selects the `contract-tests/<area>/` directory).

- [ ] **Step 1: Write failing tests** in `health/test_health.py`:
  - `test_live_ok`: `GET /api/health/live` → 200.
  - `test_ready_shape`: `GET /api/health/ready` → 200; `normalize(body)` equals
    the snapshot `health/snapshots/ready.json`. Record it from Python with
    `--snapshot-update`, using a small in-repo helper that writes
    normalized JSON.
  - `test_auth_required`: `GET /api/agents` without a token → 401 with Python's exact body.
  - `test_token_query_param`: `GET /api/agents?_token=<token>` → 200.
- [ ] **Step 2: Run** `make contract AREA=health TARGET=python`. Expected: FAIL (`backends` not implemented).
- [ ] **Step 3: Implement** `backends.py`, `normalize.py`, `sse.py` and `conftest.py`
  with the interfaces above. `make contract` = `uv run pytest contract-tests/$(AREA) -q`
  with `TARGET` passed through; `contract-all` runs the whole directory.
- [ ] **Step 4: Run** `make contract AREA=health TARGET=python`. Expected: 4 passed.
- [ ] **Step 5: Mutation check:** temporarily change the expected 401 body in
  the test to a wrong string. Expected: FAIL. Revert.
- [ ] **Step 6: OpenAPI pin and diff.** Save Python's `GET /openapi.json`
  to `contract-tests/openapi/python-v3.1.1.json`. Write
  `scripts/migration/openapi_diff.py <area>`: it extracts the paths the area
  owns (from `routing.toml`) from both the pinned spec and the Rust server's
  `GET /openapi.json`, normalizes component names, and runs `oasdiff breaking`
  plus a strict JSON diff. It exits 1 on any difference. Test it with a
  hand-edited copy that changes one field type. Expected: exit 1.
- [ ] **Step 7:** Commit: `test(contract): add dual-target contract harness with health coverage`.

### Task 4: v3.x upgrade fixtures

**Files:**
- Create: `contract-tests/fixtures/build_upgrade_fixtures.py`
- Create: `contract-tests/fixtures/upgrade/<tag>/{evoflux.db,config/,MANIFEST.json}` for tags
  `v3.0.0 … v3.0.10, v3.1.0, v3.1.1` (13 tags)
- Create: `contract-tests/upgrade/test_upgrade_fixtures.py`

**Interfaces:**
- Consumes: `backends.start_backend` (T3).
- Produces: `fixtures.upgrade_fixture(tag: str) -> Path` (copies into a temp dir);
  `MANIFEST.json` = `{"tag", "alembic_revision", "row_counts": {table: int}, "created_ids": {...}}`.

- [ ] **Step 1: Write failing test** `test_each_fixture_opens_under_v3_1_1`
  (parametrized over 13 tags). Start `TARGET=python` on the fixture, then
  `GET /api/team/sessions` lists every session id in `MANIFEST.created_ids.sessions`.
- [ ] **Step 2: Run** it. Expected: FAIL (no fixtures).
- [ ] **Step 3: Implement** `build_upgrade_fixtures.py`. For each tag it creates
  `git worktree add` at the tag, runs `uv sync` and the tag's `serve`, then
  seeds through that version's public API: 2 Work sessions with messages, 1
  Coding project + session, a scheduler task, a wiki page, a memory entry and
  a skill toggle. It stops cleanly (WAL checkpoint), copies the DB and config
  dir, and writes `MANIFEST.json`. Secrets are dummy values. The fixtures are
  committed. Keep each DB under 2 MB; fail the build if one is larger.
- [ ] **Step 4: Run** the build, then the test. Expected: 13 passed.
- [ ] **Step 5:** Commit: `test(contract): add v3.x upgrade fixtures`.

### Task 5: Mock model provider

**Files:**
- Create: `contract-tests/mock_provider/server.py`, `contract-tests/mock_provider/recordings/*.jsonl`
- Create: `contract-tests/mock_provider/test_mock_provider.py`
- Modify: `contract-tests/conftest.py` (fixture `mock_provider`), `contract-tests/README.md`

**Interfaces:**
- Produces: `mock_provider` fixture → `MockProvider(base_url: str, load(recording: str) -> None, requests: list[dict])`.
  It speaks the OpenAI Chat Completions streaming wire format and the Anthropic
  Messages streaming format, replaying a JSONL recording (one SSE event per
  line plus `{"delay_ms": n}` entries).
  `configure_backend_provider(client, mock: MockProvider) -> None` registers it
  through the same settings API the UI uses. Find the endpoint in
  `app/api/routes/settings.py` and document it in the README.

- [ ] **Step 1: Write failing test** `test_text_turn_replays`. Load
  `recordings/openai_text_hello.jsonl`, configure the backend, `POST` a chat
  message through the team chat ingress (`/api/team/...`; find it in
  `app/api/routes/team/`). Collect SSE with `sse.collect_events` until the turn
  ends, and assert the assistant text equals `"Hello from mock."`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `server.py` (stdlib `http.server` or `starlette`, port 0, started per test).
- [ ] **Step 4:** Add recordings `openai_text_hello`, `openai_tool_call_then_text`,
  `anthropic_text_hello`, `anthropic_reasoning_and_cache_usage`,
  `provider_error_429`. Add tests `test_tool_call_round_trip` (the second
  request contains the tool result) and `test_429_surfaces_error_event`
  (asserts Python's error event shape).
- [ ] **Step 5: Run** `make contract AREA=mock_provider TARGET=python`. Expected: all pass.
- [ ] **Step 6:** Commit: `test(contract): add replaying mock model provider`.

### Task 6: Python startup PR (gateway mode)

**Files:**
- Create: `app/core/gateway_mode.py`
- Modify: `app/api/app.py` (middleware registration; skip disabled services in the lifespan and in `_start_optional_services`)
- Modify: `app/core/desktop_auth.py:198` (`_EMBEDDED_REMOTE_PROXY_SECRET` source)
- Modify: `app/services/remote_use_service.py:~196` (`--target` port)
- Test: `tests/api/test_gateway_mode.py`, `tests/services/test_remote_use_gateway_target.py`

**Interfaces:**
- Produces (env contract the gateway sets, T10):
  - `EVOFLUX_GATEWAY_SECRET=<hex>`: when set, every HTTP and WebSocket request
    without header `X-EvoFlux-Gateway: <secret>` (constant-time compare) gets
    `403 {"detail": "Direct backend access is not allowed."}`. Exempt: none.
  - `EVOFLUX_REMOTE_PROXY_SECRET=<hex>`: when set, it replaces the random
    `_EMBEDDED_REMOTE_PROXY_SECRET`.
  - `EVOFLUX_TSNET_TARGET_PORT=<port>`: when set, the tailnet helper's
    `--target` uses this port (the gateway's) instead of Python's own.
  - `EVOFLUX_DISABLE_SERVICES=<comma list>` with names exactly from:
    `otel_retention, model_registry_refresh, mcp, plugin_mcp, conductor,
    agents_validation, scheduler, dream_scheduler, memory_backfill,
    standalone_coding_purge, webbridge_cleanup, webbridge_artifact_cleanup`.
    Each disabled service logs `optional_service_disabled service=<name>` and
    doesn't start. Unknown names fail startup with a clear error.
- `gateway_mode.disabled_services() -> frozenset[str]`, `gateway_mode.GatewaySecretMiddleware`.

- [ ] **Step 1: Write failing tests:**
  - `test_gateway_secret_rejects_missing_header`, `…_accepts_correct_header`, `…_rejects_wrong_header`, `…_websocket_rejected_without_header`.
  - `test_no_gateway_secret_env_means_no_check` (v3 behaviour unchanged).
  - `test_disable_services_skips_scheduler_and_mcp` (assert the start functions were not called, via monkeypatch).
  - `test_disable_services_unknown_name_fails_startup`.
  - `test_remote_proxy_secret_from_env`.
  - `test_tsnet_target_port_override` (assert the `--target` argument is `http://127.0.0.1:<override>`).
- [ ] **Step 2: Run** `uv run pytest tests/api/test_gateway_mode.py tests/services/test_remote_use_gateway_target.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The middleware is outermost, so the check runs
  before metrics, auth and CORS. Read the env once at import, like `DesktopTokenMiddleware` does.
- [ ] **Step 4: Run** the focused tests (PASS), then the full backend quality gate from Global Constraints (PASS).
- [ ] **Step 5:** Commit: `feat(core): add gateway mode startup options for the Rust gateway`.
  CHANGELOG: `Changed`, no user-visible effect unless the variables are set.

### Task 7: `core` basics: config, paths, errors, telemetry, auth, watchdog

**Files:**
- Create: `server/crates/core/src/{config.rs,paths.rs,error.rs,telemetry.rs,auth.rs,watchdog.rs,blocking.rs}`
- Test: `server/crates/core/tests/{paths.rs,error.rs,auth.rs,watchdog.rs}`

**Interfaces:**
- Produces:
  - `config::Settings::from_env() -> Result<Settings, ConfigError>` with fields
    mirroring `app/core/config.py` for `APP_ENV`, `EVOFLUX_DATA_DIR`,
    `EVOFLUX_CONFIG_DIR`, `EVOFLUX_STATE_DIR`, `LOG_LEVEL`, `API_HOST`,
    `API_PORT`, using the same defaults and the same XDG/AppData resolution.
  - `paths::Paths { data_dir, config_dir, state_dir, db_file, log_dir }` with `Paths::resolve(&Settings) -> Paths`.
  - `error::ApiError { status: StatusCode, detail: serde_json::Value, code: Option<&'static str>, headers: HeaderMap }`
    implementing `IntoResponse` as `{"detail": …}` plus `"code"` when set.
    Constructors: `ApiError::database_busy()` (byte-exact body from Global
    Constraints), `ApiError::backend_unavailable()` (Review Focus 1), `ApiError::unauthorized()` (Python's exact body).
  - `telemetry::init(&Settings) -> TelemetryGuard` (tracing to stderr + file;
    `metrics` registry with a Prometheus exporter handle: `telemetry::render_prometheus() -> String`).
  - `auth::DesktopAuth::new(token: Option<String>, remote_proxy_secret: String) -> DesktopAuth`
    and `auth::DesktopAuth::layer() -> tower::Layer`. It ports
    `DesktopTokenMiddleware`: bearer header or `?_token=` (stripped from the
    downstream query), the same exempt paths, and remote-proxy header trust
    with the same constant-time compare.
  - `blocking::run<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> impl Future<Output = Result<T, ApiError>>` (wraps `spawn_blocking`).
  - `watchdog::spawn(threshold: Duration /* 100 ms */) -> WatchdogHandle`.
    It ticks every 50 ms, measures drift, increments
    `EVOFLUX_runtime_stall_total` and records `EVOFLUX_runtime_stall_seconds`
    above the threshold. A plain OS thread checks a heartbeat atomic and logs
    `runtime_stalled` if the async tick is more than 1 s late.

- [ ] **Step 1: Write failing tests:**
  - `paths_match_python`: for 4 env combinations, compare with the output of
    `uv run python -c "from app.core.config import settings; print(...)"`
    (the test shells out; skip if `uv` is missing in CI, but not in the gate job).
  - `database_busy_body_exact`: serialize and compare bytes with the Global Constraints body.
  - `auth_*`: the same cases as T3's `test_auth_required` / `test_token_query_param`, plus a remote-proxy marker without the right token → 401 with body `{"detail": "Untrusted tailnet identity."}`.
  - `watchdog_detects_block`: run `std::thread::sleep(300ms)` inside a
    `current_thread` runtime task (allowed in tests with an explicit
    `#[allow(clippy::disallowed_methods)]`), then assert the stall counter ≥ 1.
- [ ] **Step 2: Run** `cargo nextest run -p evoflux-core`. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** the tests (PASS) and `make gates AREA=shared` (PASS).
- [ ] **Step 5:** Commit: `feat(rust/core): add config, paths, errors, telemetry, auth and stall watchdog`.

### Task 8: `core::db`, the begin-concurrent SQLite build and write lanes

**Files:**
- Create: `server/vendor/libsqlite3-sys/` (copy of the libsqlite3-sys version
  rusqlite resolves to, with `sqlite3/sqlite3.c` and `sqlite3.h` replaced by
  the amalgamation built from the pinned `begin-concurrent` tag)
- Create: `server/vendor/SQLITE_BRANCH.toml` (`tag`, `checkin`, `sqlite3_c_sha256`, `based_on_release`)
- Create: `scripts/migration/build_sqlite_amalgamation.sh`
- Modify: `server/Cargo.toml` (`[patch.crates-io] libsqlite3-sys = { path = "vendor/libsqlite3-sys" }`, `rusqlite` with `bundled`)
- Create: `server/crates/core/src/db/{mod.rs,lanes.rs,retry.rs,rowid.rs}`
- Test: `server/crates/core/tests/db.rs`

**Interfaces:**
- Produces:
  - `db::Db::open(path: &Path, opts: DbOptions) -> Result<Db, DbError>`, where
    `DbOptions { readers: usize /*5*/, concurrent_writers: usize /*4*/, admission_timeout: Duration /*5 s*/, max_retries: u32 /*5*/, concurrent_enabled: bool /* EVOFLUX_DB_CONCURRENT_WRITES != "off" */ }`.
    Every connection sets `journal_mode=WAL` (refuses to open if the file is
    `wal2`), `foreign_keys=ON`, `busy_timeout=5000` and
    `synchronous=NORMAL`; readers also set `query_only=ON`.
  - `Db::read<T: Send + 'static>(&self, f: impl FnOnce(&rusqlite::Connection) -> Result<T, DbError> + Send + 'static) -> Result<T, DbError>` (async).
  - `Db::write<T: Send + 'static>(&self, f: impl FnMut(&rusqlite::Transaction) -> Result<T, DbError> + Send + 'static) -> Result<T, DbError>` (async; concurrent lane, `BEGIN CONCURRENT`, commit under an in-process mutex, retry on `SQLITE_BUSY_SNAPSHOT` with jittered backoff 2/8/32/64/128 ms).
  - `Db::write_exclusive<T>(…same…)` (async; single FIFO connection, `BEGIN IMMEDIATE`).
  - `rowid::random_rowid() -> i64` (uniform in `1..=2^62`), and
    `rowid::insert(tx: &Transaction, table: &str, columns: &[&str], values: &[&dyn ToSql]) -> Result<(), DbError>`,
    which prepends `rowid` with a random value. It retries a new value on
    `SQLITE_CONSTRAINT_PRIMARYKEY` for the rowid only.
  - `DbError::Busy` maps to `ApiError::database_busy()`.
  - Metrics: `EVOFLUX_db_pool_wait_seconds{lane,route}`, `EVOFLUX_db_pool_timeouts_total{lane,route}`,
    `EVOFLUX_db_concurrent_conflicts_total{table}`, `EVOFLUX_db_concurrent_retries_total{lane}`.
  - Connections live on dedicated OS threads; async callers talk to them over
    bounded channels, so no rusqlite call ever runs on a tokio worker.

- [ ] **Step 1:** Write `build_sqlite_amalgamation.sh <tag>`. It fetches the
  tagged check-in from sqlite.org (fossil tarball), runs
  `./configure && make sqlite3.c`, and prints the sha256. Run it for the
  latest `begin-concurrent-*` tag and record the result in `SQLITE_BRANCH.toml`.
- [ ] **Step 2: Write failing tests** in `tests/db.rs`:
  - `begin_concurrent_available`: `BEGIN CONCURRENT` succeeds.
  - `refuses_wal2`.
  - `admission_timeout_returns_busy`: hold the exclusive lane for 6 s, then a second `write_exclusive` returns `DbError::Busy` after about 5 s.
  - `different_tables_commit_in_parallel`: 4 writers × 500 inserts into 4 tables, with 0 conflicts.
  - `same_table_conflict_retries_to_success`: force overlapping pages; all rows present and the retries metric > 0.
  - `retry_safety_closure_rerun_is_idempotent`: a test hook makes every first commit fail with `SQLITE_BUSY_SNAPSHOT`; the final state is identical to a no-conflict run and an external side-effect counter (outside the closure) is 1.
  - `random_rowid_insert_never_sequential`: 1,000 inserts, rowids not monotonic, all within range.
  - `off_switch_uses_fifo`: with `concurrent_enabled=false`, `write` goes through the exclusive lane.
- [ ] **Step 3: Run** `cargo nextest run -p evoflux-core db`. Expected: FAIL.
- [ ] **Step 4: Implement** the interfaces above.
- [ ] **Step 5: Run** the tests (PASS on all 3 OSes in CI) and `make gates AREA=shared` (PASS).
- [ ] **Step 6:** Commit: `feat(rust/core): add SQLite read, concurrent and exclusive write lanes`.

### Task 9: Database compatibility gate, two-process stress and benchmark

**Files:**
- Create: `contract-tests/db/test_compat.py`, `contract-tests/db/two_process_stress.py`
- Create: `server/crates/core/examples/db_stress.rs` (Rust writer process for the stress test), `server/crates/core/benches/write_lanes.rs`
- Create: `documents/analysis/sqlite-concurrent-writes-benchmark-<YYYY-MM-DD>.md`
- Modify: `.github/workflows/migration-gates.yml` (run `test_compat.py` when `server/crates/core/src/db/**` or `server/vendor/**` changes; monthly scheduled job comparing `SQLITE_BRANCH.toml.based_on_release` with the latest sqlite.org release, which opens an issue if behind)

**Interfaces:**
- Consumes: `Db` (T8), `upgrade_fixture` (T4), `start_backend("python")` (T3).
- Produces: `make db-compat` (part of `gates.sh` when db paths change).

- [ ] **Step 1: Write failing tests** in `test_compat.py`, parametrized over
  the 13 upgrade fixtures plus a fresh database:
  - `test_after_rust_stress_stock_sqlite_integrity`: run `db_stress` (4
    concurrent writers, 60 s, mixed tables, random-rowid inserts into the
    real tables), then Python's stock `sqlite3` gives `PRAGMA integrity_check`
    = `ok` and an empty `PRAGMA foreign_key_check`.
  - `test_after_rust_stress_v3_opens_and_serves`: start v3.1.1 on the file and
    run `make contract AREA=health` plus `upgrade/` against it. Expected: pass.
  - `test_two_process_stress`: v3.1.1 Python backend writing through its API
    (sessions and messages loop) **and** `db_stress` concurrently for 120 s. Then
    run integrity_check, the foreign key check, and row counts equal to the
    sum of both writers' acknowledged writes.
- [ ] **Step 2: Run** `uv run pytest contract-tests/db -q`. Expected: FAIL (no stress binary).
- [ ] **Step 3: Implement** `db_stress.rs` (CLI args: `--db`, `--seconds`,
  `--writers`, `--report json`) and `two_process_stress.py`.
- [ ] **Step 4: Run** the suite. Expected: PASS. **If `test_two_process_stress`
  fails:** set the Phase 1–3 default to `EVOFLUX_DB_CONCURRENT_WRITES=off` in
  `core::config`, record the failure in the benchmark doc, and tell the owner
  (design §3.3 fallback).
- [ ] **Step 5: Benchmark** `cargo bench -p evoflux-core write_lanes`: FIFO vs
  concurrent, 1/2/4/8 writers, same-table and cross-table. Write the
  throughput and p99 latency table into the benchmark doc, and set
  `DbOptions.concurrent_writers` to the best value.
- [ ] **Step 6:** Commit: `test(rust/core): add SQLite compatibility gate, two-process stress and benchmark`.

### Task 10: Gateway: routing, Python supervisor, HTTP/SSE/WebSocket proxy

**Files:**
- Create: `server/crates/gateway/src/{lib.rs,routing.rs,supervisor.rs,proxy.rs}`
- Test: `server/crates/gateway/tests/{routing.rs,proxy.rs,supervisor.rs}`, `contract-tests/gateway/test_proxy.py`

**Interfaces:**
- Consumes: `core::{Settings, Paths, ApiError, DesktopAuth, telemetry}` (T7); T6's env contract.
- Produces:
  - `routing::RoutingTable::load(path: &Path, override_env: Option<&str>) -> Result<RoutingTable, RoutingError>`.
    `routing.toml` format: `[[unit]] name = "health", owner = "python" | "rust" | "shadow", routes = ["/api/health/**"], services = ["otel_retention"]`.
    `RoutingTable::owner_for(path: &str) -> Owner` (longest prefix wins;
    unmatched → `python`). `RoutingTable::disabled_python_services() -> Vec<String>`
    (services of units whose owner is `rust`). `EVOFLUX_ROUTE_OVERRIDE=unit=python,unit2=rust` overrides per unit.
  - `supervisor::PythonSupervisor::start(cfg: PythonConfig) -> Result<PythonSupervisor, SupervisorError>`, where
    `PythonConfig { python_bin, cli_entry, site_packages, desktop_token, gateway_secret, remote_proxy_secret, gateway_port, disabled_services, env_passthrough }`.
    It launches the same bootstrap as `sidecar.rs:105-131`, with
    `serve --host 127.0.0.1 --port 0 --handshake` and the env from T6. It
    reads Python's handshake, puts the child in a Job Object
    (Windows) or process group (POSIX) via `process-wrap`, and applies the
    restart policy from Review Focus 1.
    `PythonSupervisor::upstream() -> Option<SocketAddr>` (`None` while restarting) and `shutdown()`.
  - `proxy::router(table: Arc<RoutingTable>, sup: Arc<PythonSupervisor>, rust_routes: axum::Router) -> axum::Router`.
    Python-owned requests are forwarded with the body streamed both ways,
    the `X-EvoFlux-Gateway` header added (any client-supplied copy is removed first) and hop-by-hop headers stripped.
    `Authorization` and the `Tailscale-*` / `X-EvoFlux-Remote-*` headers pass
    through unchanged, and Python stays the auth authority for its routes.
    There is no compression, timeout or body limit on proxied responses.
    WebSocket upgrades are spliced. While no upstream exists, return
    `ApiError::backend_unavailable()`.
  - Proxy choice: try `axum-reverse-proxy` first. If `sse_events_not_buffered`
    fails with it, implement the forwarder on `hyper_util::client::legacy`.
    Record which one in `gateway/README.md`.

- [ ] **Step 1: Write failing tests:**
  - `routing.rs`: longest prefix wins, unmatched → python, override env flips a unit, an unknown unit in override → error, `disabled_python_services` lists only rust-owned units' services.
  - `contract-tests/gateway/test_proxy.py` (TARGET=gateway, fake upstream where noted):
    - `test_all_health_contracts_pass_through_gateway` (rerun T3's health tests).
    - `test_sse_events_not_buffered`: the upstream sends event 1, waits 1 s, then sends event 2; the client receives event 1 in under 300 ms.
    - `test_client_disconnect_reaches_upstream`: close the client mid-stream; the upstream sees the disconnect within 2 s (Review Focus 2).
    - `test_websocket_terminal_round_trip`: open the terminal WebSocket (find the path in `app/api/routes/team/`), send `echo hi`, receive `hi`.
    - `test_large_upload_streams`: 200 MB upload; gateway RSS growth under 32 MB (Review Focus 3).
    - `test_python_crash_returns_502_then_recovers`: kill the Python pid; the next request → 502 with the `backend_unavailable` body in under 1 s; within 15 s, `/api/health/live` → 200 (Review Focus 1).
    - `test_direct_python_access_rejected`: call Python's private port without the gateway → 403.
  - `supervisor.rs`: `test_kill_gateway_kills_python_tree` (spawn a gateway test binary, kill it hard, assert the Python pid and its child are gone in under 5 s; Review Focus 4).
- [ ] **Step 2: Run** `cargo nextest run -p evoflux-gateway` and `make contract AREA=gateway TARGET=gateway`. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** both. Expected: PASS on all 3 OSes.
- [ ] **Step 5:** Commit: `feat(rust/gateway): add routing table, Python supervisor and streaming proxy`.

### Task 11: `evoflux-server` binary and handshake

**Files:**
- Create: `server/crates/server/src/{main.rs,cli.rs,handshake.rs}`
- Test: `server/crates/server/tests/cli.rs`

**Interfaces:**
- Consumes: T7, T10.
- Produces: binary `evoflux-server` with
  `serve --host <ip> --port <u16|0> --handshake [--generate-token] [--parent-pid <pid>]`.
  The flags have the same meaning as Python's `serve`
  (`app/cli/commands/serve.py`); the token comes from `EVOFLUX_DESKTOP_TOKEN`
  or is generated. Python location is taken from env `EVOFLUX_SIDECAR_ROOT`
  (dir containing the Python runtime and `site-packages`), set by T12, or
  from `--python-root` in dev. The parent-pid watch exits when the parent dies.
  `/metrics` stays proxied to Python in Phase 0 (`routing.toml` owner `python`);
  the gateway's own metrics are exposed at `/metrics/gateway`. The stall
  watchdog (T7) is on. The whole router is wrapped in
  `tower_http::catch_panic::CatchPanicLayer`, returning a 500
  `{"detail": "Internal Server Error"}` (Python's body) and logging the panic
  (design §6.1 gate 2). Add test `handler_panic_returns_500_and_server_survives`.

- [ ] **Step 1: Write failing tests:**
  - `handshake_line_exact`: start with `--port 0 --handshake --generate-token`; the first stdout line matches `^EVOFLUX_HANDSHAKE \{"port":\d+,"pid":\d+,"version":"[^"]+","token":"[^"]+"\}$` and `version` equals `app/version.txt`.
  - `handshake_waits_for_python`: with a fake Python that delays its handshake 3 s, the gateway handshake arrives after 3 s.
  - `python_never_ready_exits_with_log_tail`: a fake Python with no handshake and `EVOFLUX_GATEWAY_PYTHON_WAIT_S=2` → exit code 3, stderr contains the fake's last log line (Review Focus 5; default wait 85 s).
  - `parent_death_exits`.
- [ ] **Step 2: Run** `cargo nextest run -p evoflux-server`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, then `make contract-all TARGET=gateway` (all T3–T5 and T10 suites). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(rust/server): add evoflux-server serve command with desktop handshake`.

### Task 12: Desktop launches the gateway

**Files:**
- Modify: `desktop/src-tauri/src/sidecar.rs` (`spawn_with_desktop_token`: start `evoflux-server` from the sidecar root instead of Python; pass `EVOFLUX_SIDECAR_ROOT`, keep `EVOFLUX_TSNET_BIN`, `EVOFLUX_RG_BIN`, `EVOFLUX_APP_ENV`, desktop token, log file and Job Object attachment as today)
- Modify: `scripts/build_sidecar.py` (build `server/` in release mode, copy `evoflux-server[.exe]` into the sidecar root next to the Python runtime)
- Modify: `scripts/run_dev.py` (dev mode: run `cargo run -p evoflux-server -- serve …` with `--python-root` pointing at the dev venv)
- Test: `desktop/src-tauri/tests/` (new `sidecar_gateway.rs`)

**Interfaces:**
- Consumes: T11 binary and flags. The handshake struct is unchanged (`sidecar.rs:32-38`).

- [ ] **Step 1: Write failing test** `resolves_gateway_binary` (sidecar root with the
  binary → path found; without → error message naming the missing file).
- [ ] **Step 2: Run** `cd desktop/src-tauri && cargo test sidecar_gateway`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep the Python resolution functions for T11's env.
- [ ] **Step 4: Run** the test (PASS) and `cargo check` (PASS). Then
  `make dev-desktop`: the app boots, a Work session streams a reply via the
  mock provider or a real one, the terminal works, and remote access status loads.
- [ ] **Step 5:** Commit: `feat(desktop): launch the Rust gateway as the backend sidecar`.

### Task 13: Board, cutover units, routing table and agent docs

**Files:**
- Create: `server/AGENTS.md` (copy of `documents/plans/rust-migration-workflow.md`, with a header saying it is now authoritative; the plan file then links to it)
- Create: `server/CUTOVER_UNITS.md`, `server/MIGRATION_BOARD.md`, `server/KNOWN_DIFFERENCES.md`, `server/routing.toml`
- Test: `scripts/migration/check_board.py` + `tests/scripts/test_check_board.py`

**Interfaces:**
- Produces:
  - `MIGRATION_BOARD.md`: one Markdown table, columns exactly
    `lane | unit | python_sources | routes | owned_paths | status | claimed_by | updated | gate_report`.
    `status ∈ {open, claimed, in-review, merged, cut-over, blocked:<reason>}`. T2's `check_paths.py` parses `owned_paths` (comma-separated globs).
  - `CUTOVER_UNITS.md`: every route prefix from every router under
    `app/api/routes/` and every service name from T6's list, each in exactly
    one unit, with a "pinned by" column naming the in-memory state.
    Scheduler and dream are in the agent-runtime unit (design §3.1).
  - `routing.toml`: one `[[unit]]` per unit, all `owner = "python"`.
  - `make board` prints status counts.

- [ ] **Step 1: Write failing test** `test_check_board.py`: every route prefix that
  FastAPI registers (import `app.api.app.create_app()` and walk
  `app.routes`) maps to exactly one unit in `routing.toml`; every service in
  T6's list appears in exactly one unit; board rows parse; owned paths of
  lanes don't overlap.
- [ ] **Step 2: Run** `uv run pytest tests/scripts/test_check_board.py -q`. Expected: FAIL.
- [ ] **Step 3: Write** the four files and `check_board.py`. Lanes come from design §7 Phases 1–3 and §11/§11a (CLI, `skill-scripts`, plugin host).
- [ ] **Step 4: Run** the test. Expected: PASS. Add `check_board.py` to `gates.sh`.
- [ ] **Step 5:** Commit: `docs(shared): add migration board, cutover units and routing table`.

### Task 14: Performance baseline and responsiveness gate

**Files:**
- Create: `contract-tests/perf/{scenarios.py,test_responsiveness.py,bench_endpoints.py,baseline-v3.1.1.json}`
- Modify: `Makefile` (`perf` target)

**Interfaces:**
- Consumes: T3 backends; T1's stall scenarios.
- Produces:
  - `scenarios.FREEZE_SCENARIOS: dict[str, Callable[[Backend], ContextManager]]` (from T1, plus `repo_index_rebuild`, `long_tool_run`, `large_history_page`).
  - `baseline-v3.1.1.json`: `{"cold_start_ms", "idle_rss_mb", "endpoints": {path: {"p50_ms","p99_ms"}}, "sse_first_event_ms"}`
    for the 30 most-used endpoints. Until T15 recordings exist, take the list from the
    UI's boot and session-open request sequence.
  - `make perf AREA=<area> TARGET=<t>` compares against the baseline and fails if any endpoint p99 is more than 10 % worse.

- [ ] **Step 1: Write the test** `test_health_live_p99_under_load[scenario]`:
  under each scenario, `/api/health/live` p99 < 50 ms and the session history page p99 < 2× its idle p99 (design §8).
- [ ] **Step 2: Run** with `TARGET=python`. Expected: this documents v3.
  Scenarios that fail on v3 are marked `xfail(strict=True, reason="v3 stall, see T1 analysis")`
  for `python` only. They must pass for `rust` targets later.
- [ ] **Step 3: Implement** `bench_endpoints.py` and generate `baseline-v3.1.1.json` on the reference machine named in the file.
- [ ] **Step 4: Run** `make perf AREA=health TARGET=gateway`. Expected: PASS (the gateway adds under 10 % p99).
- [ ] **Step 5:** Commit: `test(contract): add v3.1.1 performance baseline and responsiveness gate`.

### Task 15: Shadow mode and traffic recording

**Files:**
- Create: `server/crates/gateway/src/{shadow.rs,record.rs}`, `scripts/migration/scrub.py`
- Test: `server/crates/gateway/tests/shadow.rs`, `tests/scripts/test_scrub.py`
- Modify: `Makefile` (`shadow`, `scrub`)

**Interfaces:**
- Consumes: T10 `RoutingTable`, `proxy::router`.
- Produces:
  - Owner `shadow` (GET only; config load rejects non-GET routes in a shadow
    unit). Python answers the client. The same request runs against the Rust
    router in the background; both responses are normalized (the same rules
    as T3's `normalize`, ported to Rust) and diffs are appended as JSONL to
    `<state_dir>/shadow/<unit>.jsonl`. `EVOFLUX_SHADOW_PYTHON_TWICE=1` also
    replays against Python a second time to measure noise (workflow §5.3).
  - `EVOFLUX_GATEWAY_RECORD_DIR=<dir>`: writes request/response pairs
    (SSE as event lists) as JSONL with the `Authorization`, cookie and
    `_token` values removed.
  - `scrub.py <file>` removes secrets and PII (API-key patterns, emails, home
    paths) in place and exits 1 if any known secret pattern survives.
  - `make shadow UNIT=<unit>` replays a recording directory through the gateway and prints a diff summary.

- [ ] **Step 1: Write failing tests:** `shadow_diff_written_for_mismatch`,
  `shadow_no_diff_for_equal_after_normalize`, `shadow_rejects_non_get_routes`,
  `client_gets_python_response_even_if_rust_panics`, and
  `test_scrub_removes_api_keys_and_home_paths`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(rust/gateway): add shadow comparison and traffic recording`.

### Task 16: Phase 0 exit check

**Files:**
- Create: `documents/analysis/phase-0-exit-report-<YYYY-MM-DD>.md`
- Modify: `server/MIGRATION_BOARD.md` (Phase 1 lanes → `open`)

- [ ] **Step 1: Run** on all 3 OSes: `make contract-all TARGET=gateway`, `uv run pytest --no-cov -q`
  (the unchanged Python suite), `make gates AREA=shared`, `uv run pytest contract-tests/db -q`, and `make perf AREA=health TARGET=gateway`. Expected: all PASS.
- [ ] **Step 2:** Run the packaged desktop build (`scripts/build_sidecar.py` + Tauri build) on Windows and use it for half a day: Work chat, Coding project, terminal, browser, WebBridge pairing, remote access, a scheduler task, MCP server start.
  Record any issue as a failing contract test first.
- [ ] **Step 3:** Write the exit report: gate results, T1 diagnosis summary,
  T9 compatibility and benchmark result (concurrent writes on/off for Phases 1–3),
  proxy choice from T10, and open risks.
- [ ] **Step 4:** Owner reviews and approves the report in its PR. Phase 1 opens.
- [ ] **Step 5:** Commit: `docs(analysis): add Phase 0 exit report`.
