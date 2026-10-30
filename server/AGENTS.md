> **Authoritative.** This is the operating manual for the Rust migration. It is now maintained as `server/AGENTS.md`; read and edit that file, not the copy in `documents/plans/`. In case of conflict, `server/AGENTS.md` wins. Changes to it go through a `shared:` PR that the owner reviews.

# EvoFlux v4 — Rust migration workflow and rules

Status: draft for approval · 2026-10-30 · Companion to
[rust-migration-design.md](../documents/plans/rust-migration-design.md)

This is the operating manual for every agent, tool or person working on the
migration (EvoFlux, Claude Code, Codex, Cursor, a human). It only assumes git,
a shell and `make`. In Phase 0 it is copied to `server/AGENTS.md`, and from
then on that file is the authoritative copy.

**Precedence:** root `AGENTS.md` → `server/AGENTS.md` (this) → the lane's row
in `server/MIGRATION_BOARD.md`. When they conflict, the stricter rule wins.
If something is unclear, stop and escalate (§9). Don't guess.

---

## 1. Branch rules

> **Superseded for landing work (owner decision, 2026-10-30):** tasks now land
> directly on `migrate/rust-v4` through local `wip/<agent>/<task>` branches,
> local review by a second agent, and `--ff-only` merges. No PR per task. See
> [`documents/plans/rust-migration-execution.md`](../documents/plans/rust-migration-execution.md).
> The rest of this section still applies where it doesn't conflict with that document.

| Branch | Who writes | How |
|---|---|---|
| `main` | nobody during the migration | frozen; only owner-approved critical fixes, then merged forward |
| `migrate/rust-v4` | CI merge only | squash-merge of a green PR; no direct pushes (after the bootstrap commit), no force pushes |
| `migrate/<lane>` | the lane's claimant | your own branch; rebase on `migrate/rust-v4` at least daily and before opening a PR |
| `migrate/shared-<topic>` | anyone, owner-reviewed | for changes to shared paths |
| `migrate/cutover-<unit>` | anyone, owner-approved | the `routing.toml` change, plus the unit's temporary Python adapter when needed (design §3.4) |

- One lane per branch, one branch per agent session. Never commit to someone
  else's lane branch.
- Rebase, don't merge `migrate/rust-v4` into your branch. Force-push is allowed
  only on your own lane branch.
- **PR size:** at most ~1,500 changed lines of non-test Rust. Larger work is
  sliced, usually one route family per PR. Each slice must be green by itself.
- Lane branches live at most 3 days without a merge. Past that, slice smaller.
- **Commits:** Conventional Commits, in the repo's existing style, scoped to the
  lane: `feat(rust/scheduler): port task CRUD routes`,
  `test(contract/scheduler): cover pause/resume errors`,
  `chore(shared): add db.write retry API`. No AI co-author trailers.
- `app/`, `web/`, `desktop/` aren't edited on migration branches, except:
  two Phase 0 shared PRs (the one that points `sidecar.rs` at the gateway, and
  the Python startup PR: private port, forwarded identity,
  `EVOFLUX_DISABLE_SERVICES`; design §3), and **cutover PRs**, which may add
  `app/core/rust_bridge/<area>.py` and switch the call sites it replaces (design
  §3.4, ADR 0001). Python's behaviour stays the reference.

## 2. Lane lifecycle (the loop every lane follows)

```text
claim → study → contract tests → implement → self-test → re-review
  → PR + gates → independent review → fix + re-review → merge
  → shadow → cutover → watch → done
```

1. **Claim.** Open a draft PR from `migrate/<lane>` that changes only your row
   in `MIGRATION_BOARD.md` to `claimed:<agent-id>` with a date. If the row is
   already claimed and was updated less than 24 h ago, pick another lane.
   A claim older than 24 h with no commits can be taken over.
2. **Study.** Read the Python routes, services and models listed in the board
   row, plus their Python tests. Write `server/crates/area-<lane>/NOTES.md`:
   - every endpoint: method, path, request, response, status codes, error bodies;
   - in-memory state, background tasks, files, processes and DB tables it touches;
   - side effects (events published, SSE frames, files written);
   - edge cases and odd behaviour found in the Python code (ported as-is);
   - **test map:** every Python test case for the area → the Rust unit test or
     contract test that covers it, or `n/a: <reason>` (e.g. tests a Python-only helper).
3. **Contract tests first.** Write or extend `contract-tests/<lane>/` until
   every endpoint in your slice is covered (§5.2). Run them with
   `make contract AREA=<lane> TARGET=python`. They must pass against Python
   **before** any Rust is written. Then they describe v3, not your implementation.
4. **Implement** the slice in `server/crates/area-<lane>/` following §3–§4.
   Port Python unit-test logic into Rust unit tests as you go (test map).
5. **Self-test.** `make gates AREA=<lane>` must be fully green locally: all
   §6.1 gates of the design. Fix everything. Don't open a PR to "see what CI says".
6. **Re-review after coding (self).** In a fresh pass, ideally a new agent
   session without the implementation context, go through the §6 checklist
   against the diff and against the Python source side by side. Write the
   result into the PR description: each checklist item ✔ or the reason why not.
   Fix anything found and run step 5 again.
7. **PR.** Mark it ready using the §7 template. CI runs every gate. A red gate
   means fix it. Never edit a gate, an existing contract test or the CI config in a lane PR.
8. **Independent review.** A *different* agent or tool from the author (another
   model, product or session) reviews it with the §6 checklist. PRs in the owner-review
   categories (design §6.2) also need the owner.
9. **Fix and re-review.** Every finding is fixed or answered with evidence. After
   fixes, the reviewer re-checks the changed parts, gates run again, and the
   loop repeats until there are no open findings.
10. **Merge.** CI squash-merges when gates are green and reviews are approved.
    Update the board row to `merged`.
11. **Shadow** (cutover units with GET routes). Set the unit to `shadow` in a
    shared PR, replay the recorded traffic, and use the app for at least half a
    day. The diff report must show zero unexplained differences. Explained ones
    go to `KNOWN_DIFFERENCES.md` (owner-approved) or get fixed.
12. **Cutover.** When every lane of a unit is `merged`, open `migrate/cutover-<unit>`
    flipping it to `rust`, with the gate and shadow reports attached. If the
    unit's state is used by Python agent code, the same PR adds its temporary
    adapter in `app/core/rust_bridge/<area>.py` (design §3.4) and a contract
    test proving the Python tool path now reaches Rust. The owner approves.
13. **Watch.** 24 h of real use. Any regression: flip back with
    `EVOFLUX_ROUTE_OVERRIDE`, open a bug PR with a failing contract test first,
    fix it, then cut over again.
14. **Done.** Board row → `cut-over`, with links to the cutover PR and gate report.

## 3. Coding rules (Rust)

Rust never calls Python. Temporary Python adapters may call Rust as specified in ADR 0001.

**Structure, per lane crate**
```text
area-<lane>/src/
  lib.rs       # pub fn router(state) -> axum::Router; nothing else public
  routes.rs    # transport only: extract, validate, call service, map errors
  service.rs   # business rules (port of app/services/... )
  store.rs     # SQL through crates/core db API only
  NOTES.md
```
Request/response types live in `crates/api-types` (shared). If you need a new
type, add it in your PR inside a clearly separated module
`api_types::<lane>`. That one module counts as lane-owned.

**Faithful port**
- Each Rust module starts with a doc comment naming its Python source:
  `//! Port of app/services/scheduler_service.py`.
- Keep Python's names for concepts, fields and JSON keys. Serde renames must
  reproduce the exact JSON, including `null` vs missing fields and number vs string.
- Same order of validation and the same error precedence as Python. The API's
  first error is part of the contract.
- No improvements, new features or "cleanups" of behaviour. Record suspected
  Python bugs in `NOTES.md` and raise them (§9).

**Safety**
- `#![forbid(unsafe_code)]` in every lane crate.
- No `unwrap`/`expect`/`panic!`/`todo!`/`unimplemented!`/unchecked indexing
  outside tests. Errors use `thiserror` enums converted into the shared
  `core::ApiError`, which renders Python's error JSON shape.
- No new dependency in a lane PR. Dependencies are added only through a shared PR
  (`cargo-deny` checks licences and advisories).

**Async and no-freeze**
- Never block the runtime: no `std::fs`, `std::thread::sleep`,
  `std::process::Command` or blocking I/O in async code. Use the tokio
  equivalents, or `core::blocking(|| ...)` for unavoidable sync code.
- Every outbound call has a timeout from `core::timeouts`. Every long task
  takes a cancellation token tied to the request or session.
- No locks held across `.await` except `tokio::sync` locks scoped to the smallest region.
- CPU-heavy work (parsing, diffing, indexing) goes to the bounded worker pool, never a request task.

**Data and state**
- DB only through `core::db`: `db.read(...)`, `db.write(|tx| ...)` (concurrent
  lane) or `db.write_exclusive(|tx| ...)` (migrations, bulk purge/import, wide
  multi-table changes). The write closure may run more than once (design
  §3.3): database work only, no I/O, no event publishing, no non-deterministic
  side effects inside it. Generate ids and timestamps *before* the closure.
- Inserts into rowid tables go through `core::db` insert helpers, which set the
  random rowid (design §3.3). Hand-written `INSERT` SQL without them is rejected
  by a lint test.
- No DDL. The schema is frozen.
- Config, paths, auth, telemetry, the event bus and the process registry come
  from `core`. No globals of your own, no reading env vars directly.
- Metrics and log field names stay identical to the Python ones (`EVOFLUX_*`).
  Never log secrets, tokens, prompts or file contents. Use `core::redact`.

**Cross-platform:** Windows, macOS and Linux. Use `core::paths` for all paths,
no hard-coded separators, and consider long and Unicode paths on Windows.

**Style:** `rustfmt` defaults, comments where the Python had them or where the
port is non-obvious, no commented-out code.

## 4. Generated and shared code

- OpenAPI comes from `utoipa` annotations on lane routes. Don't hand-edit generated schemas.
- Fixture databases, recorded traffic and provider recordings under
  `contract-tests/fixtures/` are shared. New recordings are added through a
  shared PR, with secrets and PII scrubbed (`make scrub`).

## 5. Testing rules

### 5.1 Layers

| Layer | Where | What it proves | Runs |
|---|---|---|---|
| Rust unit | inside the crate | ported logic; Python unit-test cases from the test map | every PR |
| Contract | `contract-tests/` | HTTP behaviour equals v3, against Python and Rust | every PR, full suite |
| Replay | `contract-tests/replay/` | recorded real traffic and recorded model conversations | every PR for the touched units, full nightly |
| Responsiveness/perf | `contract-tests/perf/` | design §8 | every PR for touched endpoints, full nightly |
| Cross-OS | CI matrix | Windows, macOS, Linux | every PR (unit + contract), nightly (all) |
| Real-provider smoke | nightly | live model APIs still work | nightly, not a merge gate |
| Upgrade | `contract-tests/upgrade/` | v3.x databases and config dirs open and work | Phase 4 gate, then every PR |

### 5.2 Contract test minimum per endpoint

Success path · auth missing or wrong · validation failure · each documented
error code · pagination/cursor boundary (if paginated) · empty state ·
concurrent access (if it writes) · SSE/WS: connect, normal stream, client
disconnect mid-stream, reconnect/resume.

### 5.3 Rules

- During the migration, Python quality gates (Ruff, Ruff format, ty and pytest)
  require **no new failures compared with the base branch**. Compare the same
  commands and failure identities on the merge-base and the PR head; report
  pre-existing failures and treat unexplained or incomplete runs as failures.

- **Never weaken an existing test** to make Rust pass: don't loosen asserts,
  add skips, widen normalisation or raise timeouts. Changes to existing
  contract tests are shared PRs that the owner reviews.
- A new contract test must pass against Python before it's merged. If it can't
  (the Python behaviour is wrong), that's a `KNOWN_DIFFERENCES.md` entry the owner decides on.
- Tests are deterministic: mock provider, fixed clock where needed, temp dirs,
  no real network in gates.
- **Flaky = failing.** Quarantining a test needs a shared PR with an issue link
  and an owner deadline. A lane can't cut over with its tests quarantined.
- Tests leave no state behind: temp config dir and fixture DB copy per test.
- **Prove the tests can fail.** Before a lane's contract tests count as its
  gate, run `cargo mutants` / deliberate mutations against the Rust code (and
  spot-break the Python). A suite that stays green on broken code isn't a gate.
- **Mine the Python tests.** Most existing tests (83 %) call Python internals.
  For each one in the test map, turn the behaviour it checks into an HTTP
  contract case where the API can observe it.
- **SSE and WebSocket are compared as event sequences** (type, order, payload
  after normalization), never as raw bytes.
- **Shadow noise baseline:** shadow diffs run Python vs Python as well as
  Python vs Rust. Differences that show up in both are noise to normalize, not bugs.
- **Repeated findings become rules.** When reviewers flag the same issue twice,
  add it to §3 or a lint and regenerate the affected code rather than
  patching each file. Rerunning a lane from scratch is acceptable and expected.

## 6. Review checklist (self re-review, independent review, and re-review after fixes)

**Behaviour parity**
- [ ] Every endpoint in `NOTES.md` is implemented and covered; the test map has no unexplained gaps.
- [ ] JSON matches exactly (field names, null vs missing, types, ordering where it's part of the contract).
- [ ] Status codes, error bodies and error precedence match Python.
- [ ] Side effects match: events, SSE frames, files, DB rows. Nothing extra, nothing missing.
- [ ] Checked by reading the Python source next to the Rust, not only by the tests passing.

**Core safety**
- [ ] No blocking in async; timeouts and cancellation on every outbound call.
- [ ] DB writes are database-only and safe to re-run (ids/timestamps made outside the closure); right lane (`write` vs `write_exclusive`); inserts use the random-rowid helpers; no DDL.
- [ ] No panics possible on user input; errors map through `core::ApiError`.
- [ ] No secrets in logs; auth and permission checks are identical to Python's.
- [ ] Touches only lane-owned paths; no new dependencies.

**Tests**
- [ ] Contract tests were written first and pass against both Python and Rust.
- [ ] No existing test or gate was weakened.
- [ ] Windows path and process behaviour considered.

**Reviewer duties:** run the lane's contract tests yourself, read the diff
fully, and leave findings as concrete file/line comments with the expected
behaviour and the Python reference. "Looks good" without the checklist isn't a review.

## 7. PR template

```markdown
## Lane / slice
<lane> — <route family>  ·  Board row: <link>  ·  Cutover unit: <unit>

## What is ported
- Python source: app/...  →  Rust: server/crates/area-<lane>/...
- Endpoints: METHOD /api/... (list)

## Tests
- Contract tests added: N (all pass vs Python ✔, vs Rust ✔)
- Test map: X Python cases → Y Rust unit / Z contract / W n/a (see NOTES.md)
- Gate report: <CI link>  ·  Perf vs v3: <summary>

## Self re-review (§6)
<checklist with ✔ or reason>

## Known differences / open questions
None | <link to KNOWN_DIFFERENCES entry or §9 escalation>
```

## 8. Definition of done

- **Slice PR:** all gates green, independent review approved with no open findings, test map complete for the slice.
- **Lane:** all slices merged; `NOTES.md` complete; every Python test case in the area mapped.
- **Unit:** all lanes merged, shadow report clean, cutover approved, 24 h watch with no regression.
- **v4:** design §9.

## 9. Escalation (stop, don't guess)

Stop work on the slice, write the question in the PR under "open questions",
and set the board row to `blocked:<reason>` when:

- Python behaviour looks like a bug, or two Python code paths disagree;
- you need a change to a shared path, a new dependency or a schema change;
- a gate or test seems wrong;
- the work needs in-memory state owned by another cutover unit;
- the lane turns out bigger than its board row (split it in the board via a shared PR).

Meanwhile, take another open lane.

## 10. Commands (created in Phase 0)

```bash
make contract AREA=<lane> TARGET=python|rust   # lane contract tests against one backend
make contract-all TARGET=gateway               # full suite through the gateway with current routing
make gates AREA=<lane>                         # every merge gate, locally
make shadow UNIT=<unit>                        # replay recorded traffic in shadow mode, print diff report
make perf AREA=<lane>                          # perf + responsiveness vs the v3.1.1 baseline
make scrub PATH=<recording>                    # scrub secrets and PII from recorded traffic
make board                                     # print lane status from MIGRATION_BOARD.md
```
