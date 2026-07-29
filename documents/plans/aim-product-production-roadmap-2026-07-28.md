# AIM Product Audit & Production Roadmap

| | |
|---|---|
| Date | 2026-07-28 |
| Baseline | `main` at `64c40d4` |
| Scope | AIM product, domain model, workflows, evidence, UI, and testability |
| Request constraint | Plan only — no product code changes |
| Verdict | Strong engineering POC; not yet ready for a real single-operator customer engagement |

## 1. Executive conclusion

AIM is no longer a mock or a four-screen demo. The current product already has
a credible vertical slice:

- AIM project setup with source, target, and KB roles.
- Source indexing, unit inventory, phases, waves, dependencies, and complexity.
- Ten builtin AIM workflows covering assess, understand, rule review, design,
  golden capture, unit/wave conversion, compare, cutover check, and suggested
  next work.
- Backend-owned readiness rules, legal phase transitions, optimistic unit
  revisions, file-backed transition events, expiring claims, and retry lineage.
- Golden provenance/integrity validation, target verification evidence, typed
  compare behavior, run reports, and traceability diagnostics.
- Mission-control-style Overview, project health, approval queue, suggestions,
  editable/searchable Knowledge Base, Traceability, run monitor, logs, retry,
  reports, and responsive navigation.

This proves that the product direction is viable. It does not yet prove that
AIM can safely run a real modernization engagement. The remaining work is not
mainly “add more cards to the UI”; it is to turn the execution and evidence
model into a durable, reproducible single-operator delivery tool and validate
it against one real stack pair.

The recommended product strategy is:

1. Stop expanding stack breadth.
2. Choose one pilot stack and one representative estate.
3. Make attempts, approvals, claims, worktrees, artifacts, and metrics
   authoritative and recoverable.
4. Refocus the UI from feature navigation to daily operational decisions.
5. Earn the production claim through a measured pilot, not more demo flows.

Scope decision:

- AIM targets one trusted operator running one local project instance.
- Collaboration, RBAC, SSO, organization tenancy, approval roles, and
  enterprise governance are explicitly out of scope.
- Approval decisions remain as lightweight workflow checkpoints because they
  are required for safe execution, not for user administration.

## 2. Audit evidence

The audit reviewed the current AIM frontend, backend services, domain models,
API routes, builtin workflows, rulebook template, and AIM-specific tests. It
also compared the current implementation with the production-readiness audit
from 2026-07-24 and its remediation notes.

Validation on the current baseline:

- AIM-focused backend, API, tool, and roster test slice: pass.
- Web TypeScript typecheck: pass.
- Web lint: fails on six existing errors and one warning outside AIM.
- Frontend AIM component/e2e tests found: zero.
- Largest AIM frontend modules:
  - `AimPipelinesPanel.tsx`: 3,518 lines.
  - `AimOverviewPanel.tsx`: 2,042 lines.
  - `AimTraceabilityPanel.tsx`: 594 lines.
  - `AimKbPanel.tsx`: 573 lines.
- Largest AIM backend policy/diagnostic modules:
  - `readiness.py`: 892 lines.
  - `traceability.py`: 765 lines.

## 3. Current product capability map

### 3.1 Overview

What works:

- Project health and operational prerequisite checks.
- Phase/wave telemetry, live operations, recent runs, approvals, and attention
  queues.
- Dependency-aware suggested next work.
- Unit queue/flow modes and contextual unit details.
- Cutover checklist and legacy state reconciliation.

Production gap:

- “Overview” now contains several products at once: mission control, planning,
  approvals, wave management, unit details, and reconciliation.
- No durable work queue or ownership SLA; most views are reconstructed from
  current files, execution rows, and process-local runtime state.
- No delivery forecast, cost, throughput, aging, WIP, quality trend, or
  plan-versus-actual.
- Suggested actions are useful recommendations, but not a persisted,
  schedulable migration plan with capacity and release targets.

Assessment: strong POC / early pilot surface.

### 3.2 Knowledge Base

What works:

- Full tree, preview, edit/split modes, search, cross-document links, document
  templates, optimistic revision conflicts, schema validation, and reindex.
- Protected generated evidence/state paths are read-only from the editor.
- Watcher-driven projection rebuild for relevant KB changes.

Production gap:

- It remains a filesystem editor rather than a structured migration knowledge
  workspace.
- Rules, mappings, ADRs, waivers, and unresolved questions do not have dedicated
  structured views or validation flows.
- No explicit local branch/commit state or conflict recovery assistance.
- Removed or moved unit documents are not reconciled; reindex intentionally
  leaves stale unit rows to preserve history.
- Search is local text scanning, without semantic/entity search, saved filters,
  or backlinks.

Assessment: useful single-user knowledge workspace; incomplete structure and
recovery.

### 3.3 Traceability

What works:

- Per-unit rule, mapping, target artifact, run, dependency, and link coverage.
- Diagnostics for missing documents, invalid rules, missing citations, missing
  mappings, target collisions, missing target artifacts, failed/stale compare
  evidence, dependency lag/cycles, and dangling links.
- Next-action readiness and attention queue.

Production gap:

- Trace links are still optional in several lifecycle phases; diagnostics can
  warn without blocking certification.
- No explicit requirement-to-rule-to-code-to-test matrix with coverage policy
  per engagement.
- Evidence freshness uses a mixture of hashes and filesystem timestamps.
- No signed/exportable certification pack for a unit, wave, or release.
- No waiver lifecycle for accepted gaps or acceptable differences.
- No impact-analysis query such as “what must be re-certified if this rule,
  mapping, source revision, or target file changes?”

Assessment: strong diagnostic foundation; not yet a certification system.

### 3.4 Pipelines and Runs

What works:

- Real workflow execution, readiness preflight, unit/wave filtering, claims,
  run history, node graph, logs, gates, stop, retry, report, and discussion.
- Interrupted executions can be retried with lineage.
- Conversion and compare produce structured evidence.

Production gap:

- Workflow execution state is explicitly best-effort and process-local. Database
  rows are not used to resume an execution; restart means retry from the
  beginning, not resume from a durable checkpoint.
- Pending approvals are read from an in-memory question service. They are not
  durable approval records bound to artifact hashes and an approver identity.
- `AimRun` and `WorkflowExecution` remain separate ledgers joined through
  session/execution references.
- Conversion uses the shared target checkout. There is no deterministic
  per-attempt worktree/branch/merge contract or target-path lock.
- A prompt now instructs the converter to commit, but target verification does
  not fail solely because the worktree is dirty or the expected commit/revision
  contract is absent.
- Compare supports a useful generic baseline, but not engagement-grade
  comparators for databases, message streams, APIs, UIs, PDFs/reports, batch
  side effects, or non-functional behavior.
- Wave `foreach` execution is sequential and lacks configurable concurrency,
  per-unit failure policy, bounded repair loops, and queue scheduling.
- The primary screen exposes workflow internals; it is better suited to expert
  debugging than daily delivery management.

Assessment: real execution POC; not durable or isolated enough for production.

### 3.5 Project setup and rulebook

What works:

- Create/join, folder convention detection, role mappings, KB-local rulebook,
  capability maturity, health checks, runner validation, canonicalizer
  validation, and project-specific assets.

Production gap:

- The shipped rulebook is intentionally a template; all lifecycle capabilities
  are `template`.
- There is no production-ready stack pack with representative fixtures and
  measured parser/runner/compare quality.
- Health checks mostly report after setup; setup does not operate as a formal
  acceptance gate with signed-off source snapshot, target baseline, CI,
  credentials, environments, and data access.
- No rulebook version upgrade/migration contract or engagement compatibility
  matrix.

Assessment: extensibility framework, not a deployable migration product pack.

## 4. Remaining production blockers

### P0-1. No real pilot pack

The generic framework cannot establish real-world value by itself. A production
claim requires at least one stack pack with:

- Reliable inventory/extraction on a representative estate.
- Reviewed mappings and target patterns.
- Executable legacy and target runners.
- Real build/test commands.
- Golden case capture.
- Supported comparator types.
- Failure and recovery fixtures.
- Measured accuracy, effort, cost, and throughput.

Recommendation: use Java 8 to Java 21 as the first pilot unless an actual
customer engagement dictates otherwise. Do not pursue COBOL, VB6, Java, and
other stacks in parallel.

### P0-2. Runtime and approvals are not durable

Workflow execution state and pending gates still depend on process memory.
Retry lineage is valuable, but it is not equivalent to checkpoint/resume.

Required contract:

- Persist every stage attempt, node checkpoint, inputs, outputs, side effects,
  pending approval, definition hash, artifact hash, and external revision.
- On restart, classify an attempt as resumable, retryable, compensatable, or
  terminal.
- Make approval prompts durable records, not projections of live questions.
- Bind decisions to artifact hashes, policy version, timestamp, decision,
  reason, and supersession state. No user/RBAC model is required.

### P0-3. Target mutation is not isolated

Claims prevent some duplicate unit work, but all conversion agents can still
operate in the same target checkout. Unit boundaries do not guarantee distinct
files, generated assets, build outputs, or shared configuration.

Required contract:

- Create one worktree and branch per stage attempt.
- Record base revision, branch, worktree, expected target paths, resulting
  commit, and merge/PR status.
- Run verification against the resulting commit in a clean checkout.
- Reject overlapping path claims or route them to a serialized integration
  lane.
- Never transition to `converted` from an uncommitted or unverifiable target
  state.

### P0-4. Source safety is a guardrail, not isolation

The current sandbox blocks direct filesystem writes and simple shell redirects,
but explicitly cannot detect all mutations such as `sed -i`, scripts with
internal writes, environment indirection, or arbitrary Git commands.

Required contract:

- Mount legacy sources read-only at the OS/container boundary for production
  runs.
- Execute runners in an isolated worker/container with allowlisted mounts,
  network policy, resource limits, and scrubbed secrets.
- Copy inputs into disposable execution sandboxes when a legacy tool requires
  local mutation.

### P0-5. Certification coverage is incomplete

A text/JSON/fixed-width/binary directory compare is necessary but not sufficient
for real modernization work.

Required contract:

- A case manifest states input coverage, expected artifacts, comparator for
  each artifact, source revision, environment, and provenance.
- Unsupported output types fail closed.
- Add comparator plugins for CSV/tabular data, database snapshots, API
  contracts, message/event sequences, PDFs/reports, UI screenshots/DOM
  semantics, and performance envelopes as demanded by the pilot.
- Model triage dispositions: target defect, golden defect, expected difference,
  environment defect, unsupported, and flaky.
- An acceptable difference requires a recorded waiver linked to rule/ADR,
  scope and canonicalizer change.
- Certification is invalidated automatically when source, mapping, target,
  test, runner, comparator, or policy hashes change.

## 5. Product direction

### 5.1 Product promise

AIM should promise:

> Given a pinned source snapshot and a ready target baseline, AIM plans and
> executes migration units through a controlled factory, preserves human
> decisions and machine evidence, and produces a reproducible certification
> pack for each release.

It should not promise fully autonomous migration. The product's differentiator
should be controlled automation with verifiable evidence and efficient human
review.

### 5.2 Primary personas

| Persona | Primary question |
|---|---|
| Delivery lead | Are we on plan, what is blocked, and what decision is needed? |
| Migration engineer | What unit is safe to start and what must I fix? |
| Architect | Does the design follow the target baseline and shared patterns? |
| SME | Which extracted rule or golden output needs business confirmation? |
| QA/certifier | What evidence proves equivalence and what invalidates it? |
| Release manager | Is the wave operationally ready and reversible? |

### 5.3 Recommended information architecture

Do not simply add more peers beside the current four menu items. Organize the
product around operational jobs:

1. **Mission Control** — health, exceptions, approvals, WIP, wave progress,
   throughput, cost, and forecast.
2. **Estate & Plan** — source snapshots, inventory reconciliation, dependency
   graph, wave builder, scope, estimates, and capacity plan.
3. **Work Units** — compact unit table/board and a unit workspace containing
   understanding, rules, design, implementation, evidence, attempts, and
   actions.
4. **Runs** — active/queued/recoverable attempts, logs, checkpoints, artifacts,
   retry/resume/supersede, and worker state.
5. **Evidence** — traceability, golden cases, comparisons, waivers, coverage,
   certification packs, and export.
6. **Project Configuration** — workspace mappings, rulebook, target baseline,
   runners, environments, policy, and local Git settings.

Transition from current routes:

| Current | Target |
|---|---|
| Overview | Rename/refocus as Mission Control |
| Knowledge Base | Keep as a view inside Evidence/Knowledge; retain direct route for compatibility |
| Traceability | Expand into Evidence |
| Pipelines | Move generic picker to Runs > Advanced |
| Unit detail side panel | Promote to a routeable Work Unit workspace |
| Approval queue in Overview | Promote to global/project inbox with durable decisions |
| Discussion | Keep as forensic context; never use chat as the approval or state system |

## 6. Feature roadmap

The sequence below assumes a small product team of two backend engineers, one
frontend engineer, and shared QA/domain-SME capacity. Estimates are planning
ranges, not commitments.

### Phase 0 — Pilot definition and architecture decisions

Estimated: 1 week.

Deliverables:

- Select one stack pair, fixture estate, target baseline, and customer-like use
  cases.
- Define supported unit kinds and exact phase evidence contracts.
- Confirm the supported operating model: one operator, one local AIM instance,
  SQLite, and KB-first state.
- Define success metrics and failure taxonomy.
- Freeze new stack packs and non-pilot comparator features.
- Threat model source, target, runner, secrets, and customer data.

Exit gate:

- A pilot charter states scope, unsupported scenarios, quality targets,
  deployment profile, and production Definition of Done.

### Phase 1 — Durable execution control plane

Estimated: 2–3 weeks.

Deliverables:

- Add `AimStageAttempt` as the canonical execution identity; stop heuristically
  joining workflow runs and domain runs.
- Persist node checkpoints, pending gates, artifacts, failure kind, retry
  lineage, and supersession.
- Add durable `AimApprovalDecision`; no user identity or RBAC layer.
- Implement restart classification and resume/retry/compensate policies.
- Keep claims safe for parallel sessions inside the single local instance.
- Add an execution outbox/event stream so UI state is SSE-driven rather than
  assembled from polling multiple ledgers.
- Define idempotency keys for every side-effecting workflow node.

Exit gate:

- Kill the server before and after every side-effecting node and gate. Every
  attempt resumes or reaches an explicit recoverable/terminal state without
  duplicate transitions, lost approvals, or leaked claims.

### Phase 2 — Isolated conversion and evidence authority

Estimated: 2–3 weeks.

Deliverables:

- Per-attempt target worktree and branch lifecycle.
- Clean-base and clean-result verification.
- Resulting commit and integration evidence linked to an attempt.
- Immutable artifact manifest with SHA-256, media type, producer, source
  revision, target revision, and policy version.
- Certification invalidation graph.
- Structured triage dispositions and waiver workflow.
- Comparator plugin interface and the pilot-required comparator set.
- Unit/wave certification pack generator in JSON, Markdown, and PDF.
- OS/container-enforced read-only source execution profile.

Exit gate:

- A fresh machine can reproduce a passing unit's verification from recorded
  revisions and manifests; changing any load-bearing artifact invalidates the
  certification.

### Phase 3 — Product UX refactor

Estimated: 2–3 weeks, can overlap late Phase 2 after contracts stabilize.

Deliverables:

- Mission Control with queues: Needs approval, Blocked, Failed/interrupted,
  Ready next, Running, and Stale evidence.
- Estate inventory reconciliation and dependency/wave planner.
- Routeable Unit Workspace with Summary, Understanding, Rules, Design, Code,
  Tests, Evidence, Dependencies, Attempts, and Activity.
- Runs workspace with queue, checkpoint timeline, recovery actions, artifact
  explorer, and advanced pipeline picker.
- Evidence workspace with matrix/graph toggle, coverage policies, waivers, and
  certification export.
- Project setup as a hard readiness wizard, not only folder detection.
- Desktop-first operational tables; mobile supports monitoring and approvals,
  not full conversion editing.
- Accessibility, empty/error/recovery states, and consistent deep links.

Exit gate:

- A delivery lead can operate a wave and explain status without opening raw
  files or chat. An engineer can move from a blocker to the exact corrective
  action in two navigation steps or fewer.

### Phase 4 — Pilot pack and measured engagement

Estimated: 4–6 weeks depending on stack and estate.

Deliverables:

- Production-ready rulebook and runners for the selected stack.
- Representative estate with at least 20–50 units and intentional edge cases.
- Parser reconciliation report against a human inventory sample.
- Golden case library with provenance and coverage.
- CI execution of workflow contracts and certification fixtures.
- Failure drills: runner crash, backend restart, stale source, dirty target,
  local branch conflict, parallel-session claim, invalid golden, flaky test,
  rejected approval, and rollback rehearsal.
- Pilot dashboard and final evidence pack.

Exit gate:

- Pilot metrics meet agreed targets and an independent reviewer can reproduce
  selected certifications. Only then label the selected stack pack
  production-ready.

## 7. Refactor plan

### 7.1 Backend boundaries

Target package shape:

```text
app/aim/
  domain/
    project.py
    unit.py
    wave.py
    attempt.py
    evidence.py
    approval.py
    policy.py
    events.py
  application/
    commands/
    queries/
    orchestration/
  infrastructure/
    database/
    kb_git/
    artifact_store/
    runners/
    worktrees/
  api/
    projects.py
    units.py
    attempts.py
    approvals.py
    evidence.py
    health.py
```

Refactor rules:

- Domain policy is pure and has no FastAPI, filesystem, LLM, or UI dependency.
- Application commands own transactions and idempotency.
- Infrastructure adapters implement Git, KB, database, runner, and artifact
  concerns.
- API routes remain thin and never rebuild readiness rules.
- Workflows call application commands; agents produce proposals/artifacts but
  do not own lifecycle transitions.
- Every projection is rebuildable from one declared authority.

Specific current hotspots:

- Move AIM endpoints out of the large team `projects.py` router.
- Split `readiness.py` into transition policy, pipeline selection,
  dependencies, and cutover policy.
- Split `traceability.py` into graph construction, coverage policy,
  diagnostics, impact analysis, and query DTOs.
- Replace file mtime freshness checks with artifact/revision hashes.
- Add a real unit archive/rename event instead of indefinite stale projections.
- Replace cross-module imports from agent tool implementation details with
  stable AIM application interfaces.

### 7.2 Authority model

The supported product profile is deliberately local and single-operator:

- KB files are authoritative for portable project state and evidence.
- SQLite holds rebuildable projections and local execution checkpoints.
- One AIM instance owns a project while workflows are active.
- Multiple sessions may run in parallel, but only through the same local
  scheduler and claim service.
- Git is used for version history and delivery, not realtime collaboration.

Do not add a Postgres control plane, user directory, organization model, or
distributed-worker protocol unless the product scope changes later. Within the
local profile, still remove ambiguity between KB state, workflow rows, and
process memory.

### 7.3 Frontend boundaries

Target feature shape:

```text
web/src/features/aim/
  mission-control/
  estate/
  units/
  runs/
  evidence/
  project-settings/
  shared/
  api/
```

Refactor priorities:

1. Extract server-state hooks and query keys from panels.
2. Split `AimPipelinesPanel` into trigger, run table, run detail, graph,
   activity, gate, report, and recovery modules.
3. Split `AimOverviewPanel` into health, queues, approvals, suggestions, waves,
   live operations, telemetry, and unit summary modules.
4. Promote the unit workspace and run workspace to routes; side panels become
   optional quick views.
5. Generate or centralize API DTO types; remove duplicated labels/status
   mappings across components.
6. Use backend-provided actions and reason codes; never duplicate readiness
   policy in TypeScript.
7. Replace broad polling with one project event stream and targeted query
   invalidation.

Refactor guardrail:

- Refactor by vertical slice while preserving routes and behavior. Do not
  attempt a one-shot rewrite of the AIM frontend.

## 8. Required test strategy

### Domain and contracts

- Property tests for every legal/illegal phase sequence.
- Revision, local claim, idempotency, and target-path collision tests.
- Schema compatibility and migration tests for every versioned artifact.
- Certification invalidation tests.

### Workflow resilience

- Execute every real AIM workflow with deterministic fake agents and real
  application commands.
- Crash/restart matrix before and after every node, gate, filesystem write,
  commit, and transition.
- Retry, resume, compensate, supersede, and claim-expiry tests.
- Parallel-session tests inside one AIM instance.

### Evidence conformance

- Empty, missing, binary, encoding, large file, JSON, CSV, fixed-width,
  tolerance, masked value, unsupported media, corrupt metadata, stale hash, and
  flaky runner fixtures.
- Golden provenance and approval tests.
- Reproducibility tests on a clean checkout.

### UI

- Component tests for queues, action blocking, approvals, conflicts, retry, and
  evidence invalidation.
- Playwright journeys for setup, assess, unit lifecycle, approval, interrupted
  recovery, certification, and cutover.
- Visual coverage at 1440, 1024/768, and 390 px.
- Accessibility keyboard and screen-reader checks.

### Security and operations

- Read-only mount escape tests.
- Runner network/filesystem/resource policy tests.
- Secret redaction tests for logs, artifacts, KB export, and URLs.
- Load tests for estate size, run history, SSE fan-out, and parallel local runs.

## 9. Product metrics

The product should capture these automatically from the first pilot:

| Dimension | Metric |
|---|---|
| Inventory | Human-sampled recall/precision, unmatched source artifacts |
| Flow | Lead time per phase/unit, queue time, WIP, blocked aging |
| Automation | Automated steps / total steps, manual touch time |
| Quality | First-pass build, first-pass compare, reopen/regression rate |
| Evidence | Coverage completeness, stale evidence, waiver count/age |
| Reliability | Restart recovery rate, duplicate side effects, claim collisions |
| Economics | Token/tool/runtime cost per unit and per certified behavior |
| Forecast | Estimate versus actual by unit kind/complexity |
| Decisions | Approval turnaround, overrides, rejected/superseded decisions |

Initial pilot targets should include:

- Zero false-pass cases in the conformance suite.
- Zero illegal phase transitions.
- Zero duplicate side effects in restart tests.
- Zero concurrent claim/path collisions.
- 100% certification artifacts reproducible from recorded revisions.
- 100% cutover decisions stored with timestamp, evidence hash, and reason.

Business targets such as automation rate and cost per unit must be set after
baseline measurement; inventing them before the pilot would be misleading.

## 10. Defer list

Do not prioritize these before the first production-ready pilot pack:

- More stack pairs.
- A general visual workflow editor for AIM.
- Autonomous cutover execution.
- Portfolio dashboards across many customers.
- Fully mobile conversion authoring.
- Marketplace/distribution for rulebooks.
- Sophisticated ML estimation trained on insufficient engagement data.
- Multi-user collaboration, RBAC, SSO, organization tenancy, and distributed
  workers.

## 11. Recommended first implementation slice

The first implementation slice after this plan should be narrowly focused on
durability and isolated local execution:

1. Introduce canonical `AimStageAttempt` and durable approval decisions.
2. Persist workflow checkpoints and pending gates.
3. Make local claims and target-path ownership authoritative across parallel
   sessions.
4. Add per-attempt worktree/branch and clean-commit verification.
5. Add crash/restart and parallel-session contract tests.
6. Expose one attempt/event API consumed by the current UI without redesigning
   the screens yet.

Why this slice first:

- It removes the highest-risk production failure modes.
- It gives the UX a stable contract.
- It lets the pilot generate trustworthy evidence.
- It avoids spending time polishing screens over a non-durable runtime.

## 12. Production Definition of Done

AIM is ready for a real customer delivery only when:

- A selected stack pack has passed the representative pilot.
- Every state transition is policy-owned and tied to same-attempt evidence.
- Every attempt survives restart with an explicit, tested recovery outcome.
- Approval decisions are durable, hash-bound, and supersedable.
- Parallel local runs cannot write overlapping target scope.
- Conversion occurs in isolated, clean, revisioned worktrees.
- Source read-only enforcement is provided by the execution environment.
- Unsupported or stale evidence fails closed.
- Certification is reproducible and automatically invalidated by relevant
  changes.
- The unit/wave/release evidence chain is exportable for the customer/auditor.
- Operators can run the factory from queues and unit workspaces without relying
  on chat or raw file inspection.
- Critical backend, workflow, UI, security, and resilience journeys are
  automated.
- Pilot quality, delivery, reliability, and cost metrics meet the signed
  targets.
