# ADR 0001: During the Rust migration, Python calls Rust for moved areas

Status: accepted · 2026-10-30 · Owner decision · Applies to: EvoFlux v4 migration
([design](../../plans/rust-migration-design.md) §3.4)

## Context

The v4 migration moves the Python backend to Rust one cutover unit at a time
behind a gateway. Units are grouped by shared in-memory state (design §3.1).
When Phase 0 Task 13 mapped every route (`server/CUTOVER_UNITS.md`), **334 of 366
routes (91 %) landed in the `agent-runtime` unit**. Python agent tools, hooks and
`team_manager` use the same in-process objects as those routes. Examples:

- the per-repository `asyncio.Lock`s in `git_ops`, shared with the `pr` tool;
- `wiki._thread_write_lock`, shared with the `note` tool, memory hooks and dream;
- `change_set_service._change_sets` and `problems_service._problems`;
- the `process_manager`, `lsp_manager` and `webbridge_manager` registries;
- settings and the loaded provider plugins.

Under the original rule ("Rust never calls Python, and Python is unchanged"),
almost everything could switch to Rust only together with the agent runtime at
the end. That makes it a big-bang cutover, the main risk the plan is meant to avoid.

## Decision

**Option A.** When an area moves to Rust, Python stops using its in-process copy
and calls the Rust API for it, through a small adapter. Where the only shared
thing is a lock, use a cross-process file lock instead.

## Rules

1. **One-way at any moment.** Python may call Rust, and Rust never calls
   Python. Rust-owned state has exactly one owner.
2. **Adapters are temporary.** Each adapter lives in
   `app/core/rust_bridge/<area>.py` and replaces the Python service object's
   public functions with calls to the gateway's loopback API, using the
   gateway secret and desktop token. Each adapter carries a header comment
   `# TEMPORARY (ADR 0001): delete when the agent-runtime unit moves to Rust.`
3. **Adapters follow routing.** An adapter is active only while its unit's
   owner in `routing.toml` is `rust`. Rolling the unit back to `python`
   (`EVOFLUX_ROUTE_OVERRIDE`) switches the adapter back to the in-process
   code, so rollback stays one switch.
4. **Same PR as the cutover.** A unit's cutover PR flips `routing.toml`, adds
   its adapter, and adds a contract test proving the Python agent tool path
   now hits Rust (for example, the `pr` tool's git call shows up in Rust's
   request log). It's owner-reviewed.
5. **Lock-only pins** (for example git per-repo locks) become cross-process file
   locks in a `core` helper, mirrored in Python. Git's own `index.lock`
   remains the last line of defence.
6. **No new Python features in adapters.** They only forward calls. Bugs are
   ported as-is (workflow §3).

## Consequences

- Units can be split again so they cut over independently. `CUTOVER_UNITS.md`
  is regrouped in a follow-up PR, and each split names the adapter that breaks its pin.
- Each cutover costs one small Python change, so `app/` is edited during the
  migration, limited to `app/core/rust_bridge/` and the call sites it replaces.
- A loopback call replaces an in-process call for moved areas while Python
  still runs the agent. The responsiveness and performance gates (design §8)
  cover this.

## End state: fully Rust

This is a bridge, not a destination. The owner's goal is **a fully Rust
backend**. When the agent-runtime unit moves to Rust (Phase 3), every adapter
is deleted along with the Python sidecar. v4's done criteria (design §9)
require `app/core/rust_bridge/` to be empty or gone. The only Python left in v4
is what can't be avoided (design §11): the `python` tool, user `.py` plugins and
any skill scripts without a matching Rust port, all run on demand outside the
backend.

## Alternatives considered

- **C, one big unit:** lanes port in parallel, but ~91 % of routes switch
  together after the agent runtime. Rejected: big-bang risk and late feedback.
- **B alone, cross-process locks:** only solves pins that are locks, not
  shared data such as change sets, so it's kept only as rule 5.
- **Rust calls Python for unported state:** rejected. Ownership becomes
  two-way and rollback gets complicated.
