# AIM mode production audit — 2026-08-01

## Scope and verdict

Baseline: `54bd7ec` (`origin/main` after PR #90).

This audit revalidated the current implementation rather than treating the
2026-07-28 roadmap as current state. The reviewed surface includes the ten
built-in AIM workflows, workflow runner and persistence models, AIM services
and tools, project APIs, setup/health/readiness/claims, and the AIM web shell.

Verdict by operating level:

| Operating level | Result | Reason |
| --- | --- | --- |
| Local engineering workflow | **Ready with configured runners/rulebook** | The complete assess → understand → design → convert → compare → certify/cutover path exists, with claims, readiness checks, deterministic evidence, run monitoring, and operator gates. |
| Controlled real-stack pilot | **Blocked** | No reviewed pilot stack pack, representative fixture estate, or measured acceptance targets are in the repository. |
| Production modernization engagement | **Blocked** | Process-restart resume, per-attempt target isolation, OS-enforced source isolation, and pilot-specific certification coverage remain open. |

“AIM complete” therefore cannot honestly mean production-certified yet. This
branch completes the highest-impact repository-local defects found by the
audit and records the remaining gates that require architectural or domain
inputs.

## Changes completed in this audit

| Commit | Control added | Acceptance evidence |
| --- | --- | --- |
| `c2d9d56` | Durable workflow gate requests and decisions | A gate is stored before it is presented. Answer, timeout, stop, and restart become `answered`, `timed_out`, `cancelled`, or `interrupted`; execution detail exposes the record. A workflow fails closed if it cannot persist the request or decision. |
| `6b88a6b` | Target revision authority for conversion evidence | Verification requires a committed, clean Git target before execution, rejects commands that dirty or change the target revision, and invalidates evidence whenever target HEAD changes. |
| `8fd6d7a` | Complete AIM question-batch handling | Run Monitor renders and submits every item in a pending batch in order, blocks partial submission, and preserves the one-click path for a single-choice gate. |
| `3ec5aa1` | Event-driven Run Monitor refresh | `workflow_progress` SSE events invalidate execution, gate, and run caches immediately; polling remains a recovery fallback. |
| `ef49007` | Database compatibility marker for the new gate ledger | Desktop schema preflight and migration smoke tests now recognize revision `00000041`; the migration chain remains single-head. |

## Current control coverage

| Area | Current state | Audit assessment |
| --- | --- | --- |
| Workflow library | 10 built-in AIM workflows with 54 tool nodes, 11 human gates, 9 agent nodes, and 6 foreach nodes | Broad local lifecycle coverage. |
| Unit concurrency | Exclusive, lease-backed claims with heartbeat and stale-owner cleanup | Suitable for one local instance; not a distributed lock. |
| Phase transitions | Readiness service, optimistic unit revision, same-attempt transition evidence, deterministic compare before equivalence | Strong guardrails; still depends on the configured stack pack and comparator coverage. |
| Execution history | Execution rows, node runs, inputs/outputs, retry lineage, live/orphan classification, durable gate decisions | Auditable and retryable; not resumable across process loss. |
| Target evidence | Verification command hash, exact clean target commit, target artifact hashes, execution identity | Strong commit-bound evidence for supported artifact types. |
| Source protection | Read-only path policy and sandbox guardrails | Helpful defense in depth, not an OS/container read-only boundary. |
| Operator UX | Mission overview, readiness, approvals, KB/rulebook, traceability, pipeline trigger, run monitor, reports/discussion | Functionally complete for local operation; large panels remain refactor debt. |
| Observability | Persisted execution/node/gate records plus workflow progress SSE and polling fallback | Sufficient for local diagnosis; no durable outbox or replayable attempt event log. |

## Open production blockers

### 1. Durable resume and idempotency

The runner still documents `ExecutionState` as process-local and marks active
runs failed after restart. Node rows are evidence, not resumable checkpoints.
Production completion requires side-effect idempotency keys, checkpoint
contracts, and restart tests before and after every mutation boundary.

### 2. Per-attempt target worktree isolation

Claims protect units, not shared files, generators, build outputs, or target
configuration. Each conversion attempt needs a dedicated branch/worktree with
base commit, resulting commit, path-claim overlap policy, and integration
status recorded as attempt evidence.

### 3. OS-enforced legacy-source isolation

Prompt, tool, and shell guardrails cannot prove a source tree was never
mutated. A production worker profile must mount source repositories read-only,
use disposable writable inputs where necessary, restrict network/resources,
and scrub unrelated secrets.

### 4. Real pilot stack and certification policy

The repository has a generic template and example runner configuration, not a
reviewed stack pack. A pilot owner must select the source/target pair and supply
a representative estate, real runners, target baseline, comparator needs,
quality thresholds, and supported/unsupported scenarios. Without that input,
adding every theoretical comparator would create breadth without evidence.

### 5. Waiver and supersession lifecycle

Human gate decisions are now durable, but certification exceptions still need
structured dispositions and waivers bound to rule/ADR, artifact and policy
hashes, scope, reason, expiry/supersession, and automatic invalidation.

## Required next decision

Choose the first controlled pilot. The existing roadmap recommends Java 8 →
Java 21 unless a real engagement dictates another pair. That decision unlocks
the fixture estate, comparator set, isolation profile, and measurable
Definition of Done; those cannot be inferred safely from the generic framework.

## Verification record

- AIM service/tool regression suite: passed (191 tests).
- Workflow/project integration regression suite: passed (64 tests).
- Web unit suite: passed (84 tests).
- Web production build: passed.
- Full backend suite: passed (5,295 collected tests; configured platform skips
  remain skips).
- Backend `ruff check .`: passed.
- Alembic graph: single head at `00000041`.
- Repository-wide `ruff format --check .`: 21 pre-existing files outside this
  branch are not formatter-clean; all files changed by this branch pass their
  scoped format checks.
- Repository-wide `ty check`: 90 existing diagnostics remain (primarily
  optional skill dependencies, SQLModel typing, and Python 3.12 `uuid7`
  resolution); no diagnostic points to a line introduced by this branch.
