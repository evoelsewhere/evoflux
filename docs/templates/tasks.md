# <Feature name> — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | YYYY-MM-DD |

<!--
The tasks turn the accepted plan into small, ordered steps an agent can
pick up one at a time. Each task:
- has a stable ID (T1, T2, …; never renumbered — a dropped task is struck out);
- names the requirements it serves ([FR-1]) and the files it touches;
- says how it is checked (a test name or a manual check);
- is marked [P] when it can run in parallel with the other [P] tasks of the
  same phase (no shared files, no dependency on them);
- is ticked [x] in the same commit as the code that completes it.
Tests come before the code they prove. Copy to docs/features/<slug>/tasks.md.
Rules: docs/README.md. Delete this comment.
-->

## 1. Phases

### Phase 1 — <name>

Done when: <observable result>.

- [ ] T1 [FR-1] Write the failing test for … — `crates/evo-…/tests/…` — check: `cargo test -p evo-… <name>` fails for the right reason
- [ ] T2 [FR-1] Implement … — `crates/evo-…/src/…` — check: T1 passes
- [ ] T3 [P] [FR-2] … — `apps/desktop/src/…` — check: …

### Phase 2 — <name>

Done when: ….

- [ ] T4 …

## 2. Verification

Every requirement in the spec maps to the check that proves it. A
requirement without a passing check is not done.

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-… <name>` / manual check in the running app | not run · passed (YYYY-MM-DD) |
| NFR-1 | … | … |
