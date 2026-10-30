# Phase 0 exit report - 2026-10-31

Status: for owner review. Phase 1 lanes are set to `open` in
[`server/MIGRATION_BOARD.md`](../../server/MIGRATION_BOARD.md); the owner's
approval of this report and the half-day of daily use below confirm that
opening.

All checks ran on Windows 11 (AMD Ryzen 9 5900HS), run by the orchestrator;
results come from its `exit-check-results.txt`, which is not committed. macOS
and Linux were not run.

## Gate results

| Check | Result |
|---|---|
| `TARGET=gateway` contract `health` | pass (rc 0) |
| `TARGET=gateway` contract `mock_provider` | pass (rc 0) |
| `TARGET=gateway` contract `gateway` | pass (rc 0) |
| `TARGET=gateway` contract `upgrade` | pass (rc 0) |
| `--collect-only` over all of `contract-tests/` | pass (rc 0) |
| `bash scripts/migration/gates.sh shared` | pass (rc 0) |
| `cargo check` in `desktop/src-tauri` | fail (rc 101) before the sidecar bundle exists (`resource path ..sidecar-bundle does not exist`); pass after it was built |
| `uv run python scripts/build_sidecar.py` | fail (rc 1), see "Packaged build" |
| `uv run pytest --no-cov -q` (Python suite) | not completed, see "Python suite" |
| Contract `db` (`-k fresh` / `-k v3`) | **not in the results; not run for this report** |
| Contract `perf` / `make perf AREA=health TARGET=gateway` | **not in the results; not run for this report** |

The `db` and `perf` rows are gaps in the exit check, not passes. The T9 and
T14 numbers below come from their own landed reports, not from this run.

### Python suite

The subset run (`api`, `core`, `scheduler`, `models`, `cli`) stopped on a
timeout. It hit `tests/api/test_webbridge.py::test_command_roundtrip_agent_ws`,
which hangs on both v3 and the migration branch. The only `app/` change on
`migrate/rust-v4` is T6 (`23d8166c`, PR #50). Its full base-versus-head
comparison showed no new failures: ruff 11 = 11, format 71 = 71, ty 159 = 159,
and identical failing pytest ids. So the owner's rule (no new failures
compared with v3.1.1) is supported by that T6 comparison, not by a complete
run here. A full run that gets past the hanging test is still open.

### Packaged build

`build_sidecar.py` packed 52 Python packages, then stopped with
`web bundle missing: web/dist/index.html`. The web UI must be built first
(`cd web && bun install && bun run build`). The Tauri bundle build was not
attempted, so the full packaged installer has not been built or used.

## T1: v3.1.1 freeze diagnosis

Full report: [v3-freeze-diagnosis-2026-10-30.md](v3-freeze-diagnosis-2026-10-30.md).
A cold-start repeat reproduced a 1,407 ms `live` probe before optional services
were ready. The `py-spy` capture put the main thread in the MCP SDK import,
reached from `_start_optional_services`, so synchronous startup work blocks the
event loop for roughly 1-3.5 s. It is not every start (the full rerun's
cold-start maximum was 640 ms). After optional services were ready, no
steady-state workload exceeded one second (worst: 516 ms for a long shell tool).
The experiment does not establish the cause of the owner's intermittent UI
freeze; a warm repeat with populated history is open.

## T9: SQLite result and owner decision

Full report: [sqlite-concurrent-writes-benchmark-2026-10-30.md](sqlite-concurrent-writes-benchmark-2026-10-30.md).
`BEGIN CONCURRENT` is built (pinned 3.51.3 branch build, two concurrent
writers, lane-managed WAL checkpoints that keep the WAL under 16 MiB). On this
host, FIFO with two or more writers matches or beats the concurrent lane in
every workload; the multi-statement chat-turn workload conflicts on every
multi-writer size. Example, message workload, 8 writers: FIFO 1944 writes/s, p99
54 ms; concurrent 1601 writes/s, p99 120 ms.

**Owner decision (design §3.3): concurrent writes are built and default off.**
FIFO is the default for every write path; `EVOFLUX_DB_CONCURRENT_WRITES=on`
enables the concurrent lane. It stays off until re-benchmarked in Phase 4 and
v4.1. One mixed Python-plus-Rust stress case failed once with a post-shutdown
`disk I/O error` from stock Python SQLite; later repeats passed and the cause is
not proven.

## T10: proxy choice

Full notes: [`server/crates/gateway/README.md`](../../server/crates/gateway/README.md).
`axum-reverse-proxy` for plain HTTP and SSE (`test_sse_events_not_buffered`
passes; no compression, timeout or body limit added). WebSocket upgrades bypass
it: the gateway sends the upgrade over its own `hyper::client::conn::http1`
connection (500 ms connect timeout) and splices the upgraded connections after
Python answers `101`. The `hyper_util` fallback was not needed.

## T14: performance baseline headline

Baseline: [`contract-tests/perf/baseline-v3.1.1.json`](../../contract-tests/perf/baseline-v3.1.1.json),
median of 5 Python v3.1.1 runs on this machine. Cold start 7,008 ms (spread
3,380 ms), idle RSS 225.6 MB, chat POST to first SSE event 332 ms. Typical
endpoint p99 is 2.6-16 ms (`/api/health/live` 2.6 ms); the slow ones are
`/api/settings/providers` (p99 2,061 ms), `/api/skills` (104 ms), history
(81 ms) and session detail (91 ms). The compare limit per endpoint is
`max(1.1 x p99, p99 + floor_ms)`, so a candidate is judged against the measured
Python-vs-Python noise.

## Open items

- macOS and Linux runs not done (contract suites, gates, freeze diagnosis, T9
  benchmark; Windows only).
- POSIX hard-kill cleanup (process group) is untested.
- DB metrics are not on the T7 telemetry.
- Shadow mode is not wired into `serve`.
- Tailnet and WebSocket auth are not ported to Rust.
- CI only runs on PRs, so nothing checks `migrate/rust-v4` itself.
- The packaged build needs the web UI built first; the full Tauri bundle has
  not been built.
- The contract `db` and `perf` suites were not part of this exit run, and the
  full Python suite did not complete (see above).
- The T1 second-OS run and a warm-history repeat; the T9 other platforms and
  fixture versions; pinned SQLite base is behind 3.54.1 and needs a
  security-fix review.

## Owner checklist: half a day of daily use

Use the packaged desktop build (build the web UI, then `build_sidecar.py`, then
the Tauri build). Record any issue as a failing contract test first.

- [ ] Work chat: new session, send messages, stream completes, history reloads.
- [ ] Coding project: open a project, list files, Git status and diff, edit a file.
- [ ] Terminal: open one, run a command, a long-running command, close it.
- [ ] Browser: open the in-app browser and load a page.
- [ ] WebBridge pairing: pair, confirm status, send a command.
- [ ] Remote access: enable it and connect from another device (WebSocket too).
- [ ] Scheduler task: create one, run it, pause and resume it.
- [ ] MCP server start: start a configured server and call one of its tools.
- [ ] Throughout: no UI freeze; note any pause of a second or more and the time.

## User-level checkpoint (design §9a), 2026-10-31

The orchestrator ran an exploratory smoke run as a first-time user. Setup: the web UI (Vite) talked to `evoflux-server` on :8000, with Python behind it, throwaway data/state dirs, and a copy of the owner's real provider config.

| Check | Result |
|---|---|
| App boots through the gateway; first-launch import dialog shows | pass |
| Owner's model picked up from config (`mimo-v2.6-flash`) | pass |
| Work chat: send a message, the reply streams over SSE through the proxy ("smoke test ok", 5.4 s, 33.7k tokens, $0.005) | pass |
| Reload: the session and its history persist | pass |
| Crash drill: kill the Python child; requests get `502` at once, `/api/health/ready` returns `200` again after ~9 s, and the UI shows the session after a reload | pass |

Environment finding: drive D: ran out of space (0 GB free), mostly per-worktree Rust `target/` caches, and Vite crashed with "not enough space on the disk". Clearing the caches of landed worktrees freed 37.7 GB. Agents must delete build caches when a worktree's task lands (added to the execution doc).

The automated e2e suite (Phase 1 T10) and the owner's half-day of use are still to come.
