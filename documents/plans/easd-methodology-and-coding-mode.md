# EASD methodology and Coding-mode implementation specification

Status: implemented and benchmarked on 2026-08-24; see the
[benchmark report](../analysis/easd-benchmark-2026-08-24.md)

Methodology: **EASD — Evo Agent Specification-Driven Development**

## Problem and outcome

Coding mode already coordinates specialized agents, worktrees, typed handoffs,
machine verification, plan/workflow approval, ChangeSets, and observability.
Those capabilities are not joined by a durable specification domain. A lead can
delegate work and tests can pass, but the product cannot yet prove which version
of a requirement authorized each mission, which evidence satisfies each
acceptance criterion, whether the implementation drifted, or why the final run
is converged.

EASD adds that missing execution/governance layer without replacing the team,
workflow, Goal, ChangeSet, or verification engines.

The intended outcome is a Coding-mode Development Run that can prove:

```text
accepted spec → user-approved plan → owned missions → independent review
→ snapshot-bound verification evidence → convergence
```

## Goals

- Make SDD and ADD first-class, durable Coding-mode product concepts.
- Preserve accepted specification revisions immutably with a canonical hash.
- Give every non-trivial mission explicit AC ownership and write scope.
- Reuse `DelegationTask` as the mission execution record.
- Bind evidence to a spec hash and exact code artifact/revision where possible.
- Surface deviations instead of allowing silent scope drift.
- Compute convergence from evidence and open work, not an LLM's “done” claim.
- Provide a live Coding UI for spec, AC, mission, evidence, deviation, and
  convergence state.
- Remain local-first and provider/model neutral.
- Support a reproducible benchmark with GPT-5.6 family role routing.

## Non-goals

- Replacing GitHub Spec Kit, Kiro Specs, or existing Markdown documentation.
- Inventing a second generic workflow engine.
- Automatically merging every worktree or resolving semantic conflicts.
- Claiming mathematical proof of arbitrary product behavior.
- Allowing agents to approve their own normative spec changes.
- Requiring multi-agent fan-out for trivial work.
- Shipping adaptive model selection before the evidence/metrics foundation.

## Vocabulary

- **Development Run:** one EASD execution in one Coding workspace/project.
- **Spec Revision:** immutable normalized specification snapshot.
- **Acceptance Criterion (AC):** stable, observable requirement such as `AC-1`.
- **Mission:** a `DelegationTask` bound to a Development Run and one or more ACs.
- **Evidence:** a structured claim/result with provenance and trust level.
- **Deviation:** behavior or scope not authorized by the accepted spec.
- **Convergence:** all required ACs have satisfactory evidence, required
  missions are terminal, no blocking deviation remains, and final checks pass.

## EASD lifecycle

1. **Author and Accept** — user creates Intent, a bound lead drafts from
   repository evidence, and only the user accepts an immutable spec revision.
2. **Compile and Approve Plan** — the lead maps ACs into a typed mission DAG;
   only the user accepts its immutable hash.
3. **Allocate** — agents/models/tools/path claims/worktrees are selected from
   approved plan missions.
4. **Execute** — implementation and integration missions run through the
   existing team runtime.
5. **Challenge** — an explicit read-only Review phase adds independently
   identified evidence.
6. **Verify** — a separately user-started phase gathers final integration
   evidence against the accepted Proof policy.
7. **Converge** — the service computes an AC matrix and applies gates.
8. **Learn** — telemetry records cost, latency, conflict, rework, and outcome.

## User flows and states

### Create and accept a run

1. User opens EASD in a Coding workspace/project.
2. Repository setup installs the current EASD bootstrap/rules/templates, a chosen
   version-controlled data directory, and the Coding-only Skill bundle before
   runs become available.
3. User creates a run from title, problem, and optional intended outcome. The
   durable run is `intent`; no spec revision or implementation authority exists.
4. **Draft specification in chat** binds an idle authorized Coding session and
   explicitly loads `easd-specify`. The lead grounds the full Scope/Proof in
   repository evidence and submits it through the typed authoring tool.
5. The persisted draft is editable; edits create a newer draft revision.
6. Only the user's **Approve specification** action accepts the immutable
   revision, content hash, and direct/planned flow. Later changes never mutate
   the accepted snapshot.

### Execute missions

1. For planned flow, **Run plan in chat** moves the run to `planning`; the lead
   submits a typed Plan without implementation authority, and only **Approve
   plan** selects its hash and moves to `planned`.
2. **Run implementation in chat** moves planned `planned → active` or eligible
   direct `accepted → active`.
3. Planned delegation contains run/spec/plan/mission/AC identity. Direct
   delegation contains run/spec/AC identity and must omit Plan fields.
4. Runtime validates identity and Scope before dispatch.
5. Existing dependency/path/worktree rules apply.
6. Mission status is projected into the repository store. Explicit
   user actions then advance terminal implementation missions through read-only
   Review and final Verify before Converge is available.

### Add evidence

Evidence may be:

- `machine`: command/test/LSP/build evidence with exit/result and artifact hash;
- `review`: independent agent or human review with concrete sources;
- `manual`: explicit user/lead observation;
- `waiver`: user-authorized criterion waiver with reason.

Final member handoff imports machine `CompletionContract` evidence
automatically when the mission is EASD-bound. Manual/review evidence can be
added through the API/UI.

### Handle deviation

- Agent or lead records a deviation when implementation requires behavior not
  authorized by the active spec.
- Blocking deviations prevent convergence.
- Approving a normative change requires a new spec revision; a deviation may be
  resolved against that revision.
- Rejecting a deviation sends the work back to the mission/rework path.

### Converge

Convergence succeeds only when:

- one accepted spec revision is active;
- all required ACs are satisfied or explicitly waived;
- evidence satisfies each AC's policy;
- all phase-relevant EASD missions are terminal and none failed/blocked/rework;
- required runtime-authenticated review evidence is passing and independent
  where the accepted plan or risk tier requires it;
- no blocking deviation is open or merely proposed;
- final report is bound to the accepted spec hash and current Git revision.

## Risk tiers

| Tier | Intended use | Minimum gate |
|---|---|---|
| `trivial` | Docs/typo/mechanical | Lead evidence, no forced delegation |
| `standard` | Normal isolated feature/fix | Machine or review evidence per required AC |
| `cross_layer` | Backend/frontend/data or multiple owners | Mission graph + machine evidence + independent review |
| `critical` | Auth, permissions, migrations, concurrency, remote/prod | Human spec approval + isolated missions + machine evidence + independent review |

## Requirements and acceptance criteria

### Domain and specification

- **AC-1:** A Coding workspace/project can create and list EASD Development
  Runs without affecting Work-mode sessions.
- **AC-2:** Accepting a spec stores an immutable normalized payload and SHA-256
  hash; later edits cannot change the accepted row.
- **AC-3:** Every criterion has a stable unique ID, statement, required flag,
  and evidence policy validated at write time.
- **AC-4:** Run detail returns the accepted spec, computed AC matrix, missions,
  evidence, deviations, and convergence state in one bounded response.

### Mission execution

- **AC-5:** `TaskSpec` can bind a mission to an EASD run, exact spec hash, and
  non-empty valid AC ID set.
- **AC-6:** Delegation rejects unknown runs, inactive/unaccepted specs, stale
  spec hashes, or unknown AC IDs before dispatch.
- **AC-7:** EASD missions retain existing dependency, deadline, target-path,
  and worktree isolation behavior.
- **AC-8:** Mission records remain queryable after reconnect/restart through the
  durable delegation ledger.

### Evidence and handoff

- **AC-9:** Evidence records contain producer, kind, result, AC IDs, spec hash,
  optional mission, revision/artifact hash, payload, and timestamp.
- **AC-10:** Final EASD handoff imports a passing/failing machine
  `CompletionContract` as evidence without trusting free-form summary text.
- **AC-11:** Evidence with stale spec hash or AC IDs not present in that spec is
  rejected.
- **AC-12:** AC matrix distinguishes `uncovered`, `in_progress`, `passed`,
  `failed`, and `waived` using persisted state.

### Deviation and convergence

- **AC-13:** A blocking open deviation prevents convergence and is visible in
  run detail/UI.
- **AC-14:** Normative deviation approval never mutates the accepted revision;
  it requires/resolves against a new revision.
- **AC-15:** Convergence is rejected with structured reasons when any required
  gate is unsatisfied.
- **AC-16:** Successful convergence persists a report with spec hash, Git
  revision, AC matrix summary, mission summary, evidence IDs, and timestamp.

### Product UI and observability

- **AC-17:** Coding workbench exposes an Evo Agent Specs panel with run
  creation, spec acceptance, AC matrix, mission/evidence/deviation lists, and
  convergence action.
- **AC-18:** Work mode does not expose the Evo Agent Specs workbench tool.
- **AC-19:** EASD API mutations invalidate/refetch the active run without
  duplicating server truth in component state.
- **AC-20:** EASD operations emit structured logs/metrics for run creation,
  spec acceptance, mission binding, evidence, deviation, and convergence.

### Documentation and benchmark

- **AC-21:** Current feature/architecture/API docs and localized Help describe
  the implemented EASD behavior and explicitly label unsupported future work.
- **AC-22:** A separate Git repository is registered as an EvoFlux Coding
  Project and contains a deterministic EASD benchmark specification/tests.
- **AC-23:** The benchmark records role/model mapping, elapsed time, token use,
  AC coverage, mission rework/conflicts, evidence, and final test outcome.
- **AC-24:** Benchmark model policy prioritizes the configured GPT-5.6 family:
  Sol for lead/architect/verifier, Terra for implementation, and Luna/Terra for
  bounded exploration where available.

### Repository setup and runs workspace

- **AC-25:** Workspace scope initializes one repository and project scope
  initializes every live project repository using bounded `.evoflux/easd/`
  artifacts before run creation.
- **AC-26:** Invalid or escaping setup fails closed; repair requires an explicit
  overwrite action and filesystem I/O does not occur inside a DB transaction.
- **AC-27:** Project run listing spans every initialized project repository and
  new runs select an owning repository.
- **AC-28:** The panel offers searchable Board, Table, and List views while run
  detail remains server-backed and view preference remains client-only.
- **AC-29:** Coding UI labels the workbench surface **Agent
  Specification-Driven Development** while retaining EASD as the stable
  methodology/API identifier and Evo Agent Specs as the product name.
- **AC-30:** README demo media records real local EASD Benchmark interactions:
  one complete UI lifecycle through the convergence service and one
  Board/Table/List plus acceptance-matrix inspection, with no mock run data.

### Agent-assisted authoring and chat handoff

- **AC-31:** Generate Outcome, Scope & Proof is enabled after title and problem
  are present and a Coding session supplies the model context. Intended outcome
  is optional input and is returned as a reviewable generated draft.
- **AC-32:** Generation uses bounded authorized multi-repo `AGENTS.md`, current
  docs, configuration, source and tests without following path/symlink/vendor
  escapes or widening project trust.
- **AC-33:** Outcome/Scope proposals contain an observable intended outcome,
  goals, non-goals, source refs, affected repository/file/module targets and
  typed constraints/boundaries.
- **AC-34:** Proof proposals contain observable ACs with per-AC evidence policy,
  risk tier, verification commands and independent-review requirement.
- **AC-35:** Ambiguous or confidence-below-threshold product choices return
  clarifying questions and no Scope/Proof proposal.
- **AC-36:** Proposals expose confidence, rationale, hash-addressed provenance
  and current-versus-proposed review; Scope and Proof regenerate separately.
- **AC-37:** Generation never overwrites edited content on first Apply; a stale
  client snapshot requires explicit replacement confirmation.
- **AC-38:** Generation never creates, accepts, activates or converges a run.
- **AC-39:** Generation supports loading, cancellation, error/retry, project
  multi-repo scope and workbench-container responsive layout.
- **AC-40:** Feature/API/architecture docs, localized Help and focused backend
  and frontend tests describe and enforce the authoring boundary.
- **AC-41:** Each runnable phase exposes a persisted-state CTA: accepted runs
  expose planning, planned runs expose implementation, active runs expose
  Review, and reviewing runs expose Verify. Bound runs reopen their phase chat;
  unbound runs choose an authorized idle Coding chat through atomic
  scope/idleness validation. Handoff survives route navigation and a database
  invariant permits only one non-terminal session-owning run per session.
- **AC-42:** README hero positions EvoFlux as the spec-first, local-first
  workspace for Cowork and Coding without an unsupported market-first claim.

### Run-first specification authoring

- **AC-43:** A user creates a run with title, problem and optional intended
  outcome. The persisted run is `intent`, contains no spec revision, and cannot
  activate implementation.
- **AC-44:** **Draft specification in chat** atomically binds one authorized
  idle Coding session and transitions `intent → authoring`; a busy, foreign or
  already-owned session fails without partial state.
- **AC-45:** The Coding lead receives a specification-only prompt and a
  lead-only typed `easd_submit_specification` tool. The tool validates a complete
  spec and repository-qualified impact scope, persists provenance, and moves
  `authoring → draft`; it has no approval or implementation capability.
- **AC-46:** Agent submission is idempotent for the same hash and refuses a
  different overwrite after the draft reaches user review.
- **AC-47:** Draft detail displays outcome, scope, risk, AC evidence policies
  and planned commands. User edits create a newer draft revision; only explicit
  **Approve specification** establishes the accepted immutable hash.
- **AC-48:** Before specification acceptance, neither planning nor
  implementation is available. After approval, the next action is
  **Run plan in chat** (`accepted → planning`); implementation remains blocked
  until the separately reviewed plan is accepted, as expanded by AC-55–AC-59.
- **AC-49:** The panel polls while authoring and derives every CTA from persisted
  server status, never from agent prose or an optimistic client-only flag.

### Repository-scoped EASD skill bundle

- **AC-50:** Initializing a repository installs the versioned, portable
  `easd-specify`, `easd-plan`, `easd-implement`, `easd-review`, and
  `easd-verify` skills under `.evoflux/skills/`, each with Coding-only scope.
  They are project skills—not global seeds or built-ins—and are therefore
  discoverable only when that authorized repository is in the active Coding
  scope.
- **AC-51:** The five skills cover the executable EASD author-to-converge
  lifecycle without becoming a second policy engine: Specify grounds and
  submits a review draft;
  Plan maps the accepted hash and ACs to bounded work; Implement stays inside
  active accepted scope and reports deviations; Review independently challenges
  the integrated change with cited AC/boundary findings; Verify gathers real
  integration evidence, reconciles docs, and recommends convergence. No skill
  may approve a specification or fabricate lifecycle/evidence state. Every Skill
  re-reads persisted phase/hash state, rejects stale work, and emits the typed or
  evidence-gap output owned by its phase.
- **AC-52:** Setup records the repository store, directories, and exact current
  skill names without schema/bundle versions. A legacy or incomplete valid
  setup reports `upgrade_required` and upgrades idempotently to current without
  replacing an existing valid edited Skill; invalid or escaping bundles fail
  closed and require an explicit overwrite repair.
- **AC-53:** Setup API/UI exposes paths and installed skill
  names, distinguishes Initialize, Upgrade, and Repair, and keeps multi-repo
  readiness blocked until every repository has a valid bundle.
- **AC-54:** Feature/architecture/API/methodology docs and localized Help explain
  project-scoped activation and the runtime-authority boundary; focused tests
  verify installation, discovery precedence/mode, upgrade preservation,
  symlink rejection, API shape, and responsive setup rendering.

### Approved-plan, review, and verification phases

- **AC-55:** Accepting a specification leaves the run `accepted` and exposes
  **Run plan in chat**; implementation cannot start and the pre-implementation
  mutation guard remains active.
- **AC-56:** A provider-neutral plan is bound to the exact accepted spec hash and
  contains an acyclic mission graph with stable mission IDs, kind, owned ACs,
  repository/path scope, dependencies, interfaces/constraints, expected output,
  isolation, verification commands, and independent-review policy. Every
  required AC has implementation/integration ownership, every plan has a Review
  mission, and every accepted Proof command belongs to an explicit verification
  mission. Cross-layer/critical Review must be independent.
- **AC-57:** Starting planning atomically binds an authorized idle Coding chat
  and transitions `accepted → planning`. The lead-only typed
  `easd_submit_plan` tool validates scope/coverage, persists provenance, and
  transitions `planning → plan_review`; it cannot approve or implement.
- **AC-58:** Plan detail is reviewable and hash-addressed. Only explicit user
  **Approve plan** accepts a plan revision and transitions
  `plan_review → planned`; stale hashes and agent overwrite attempts fail.
- **AC-59:** **Run implementation in chat** requires both the current accepted
  spec and current accepted plan. It atomically transitions `planned → active`;
  direct activation from `accepted`, `planning`, or `plan_review` is rejected.
- **AC-60:** **Run review in chat** is available only from `active` after all
  current EASD missions are terminal and transitions `active → reviewing`.
  Review remains read-only for product files and uses the `easd-review` Skill.
- **AC-61:** A typed EASD review submission records real `review` evidence for
  the current spec hash with runtime reviewer identity, per-AC result, cited
  findings/sources, snapshot identity, confidence, and an independently computed
  `independent` flag. A delegated submission must match the exact approved
  review mission; implementation mission IDs, retries with different content,
  and stale snapshots/hashes fail.
- **AC-62:** **Run verify in chat** transitions `reviewing → verifying` only when
  review missions are terminal and cross-layer/critical runs have independent
  passing review evidence. It loads `easd-verify`; read-only verification
  missions still produce a fresh CompletionContract bound to the current
  repository revision and accepted commands. Convergence is unavailable before
  `verifying` and remains a separate user-triggered server gate.
- **AC-63:** Board/detail polling and every CTA are derived from persisted
  `planning`, `plan_review`, `planned`, `active`, `reviewing`, `verifying`, and
  `converged` state. Agent prose or chat navigation never advances a phase.
- **AC-64:** Migration, API/client types, phase Skills, architecture/reference,
  localized Help, and focused backend/frontend tests preserve compatibility for
  existing nullable EASD data while documenting the planned-flow Plan gate.

### Repository-owned store and driven-flow selection

- **AC-65:** Every specification draft contains a reviewable `delivery_flow`
  recommendation of `direct` or `planned`, with rationale, confidence, and the
  detected conditions that require planning. Approving the specification also
  approves this flow choice; the agent never selects it after approval.
- **AC-66:** `direct` is permitted only for trivial/standard, single-boundary
  changes without security, persistence/migration, public compatibility,
  concurrency, multi-repository, or independent-review requirements. The
  service revalidates eligibility and fails closed even when an agent suggests
  skipping Plan. Cross-layer and critical work always uses `planned`.
- **AC-67:** An accepted `direct` specification exposes **Run implementation in
  chat** and may transition `accepted → active` without a plan artifact. An
  accepted `planned` specification exposes **Run plan in chat** and retains the
  separate plan approval gate. Review, Verify, evidence, and Converge remain
  mandatory for both branches.
- **AC-68:** Repository initialization keeps the bootstrap manifest under
  `.evoflux/easd/config.json` and lets the user choose a safe repository-relative
  `data_directory` (default `documents/easd`). Absolute paths, `..`, symlinks, and
  paths outside the repository fail closed.
- **AC-69:** The owning repository stores every normative EASD artifact under
  the configured data directory: run/Intent, immutable spec and plan revisions,
  lifecycle/event history, mission snapshots, evidence, deviations, reviews,
  verification, and convergence. The structure is human-readable, diffable,
  deterministic, and version-controlled.
- **AC-70:** Repository files—not the application SQLite database—are the EASD
  source of truth. Local session bindings, process locks, and rebuildable indexes
  may live in ignored `.evoflux/easd/.local/` state, but no normative EASD
  contract or status depends on one developer's application database.
- **AC-71:** Every mutable repository write is atomic and compare-and-swap
  guarded by the caller's expected document hash/generation. Stale edits return
  a visible conflict; they never silently overwrite a collaborator's Git-pulled
  change. Append-only IDs make evidence/events safe to merge.
- **AC-72:** A multi-repository run has exactly one owning repository and writes
  its canonical store only there. Repository-qualified Scope and source refs may
  target every authorized project repository; collaborators resolve the same run
  by its version-controlled owner path and stable UUID.
- **AC-73:** Initialization installs the current core-rules contract enforcing:
  repository source of truth; intent/spec before code; fix ambiguity in the spec
  before implementation; never weaken an accepted spec to excuse code; immutable
  accepted revisions; human-only approvals and phase transitions; bounded
  mission/AC ownership; explicit deviations; evidence before Done; proportional
  independent review; and stale-write fail-closed behavior.
- **AC-74:** Initialization installs standard Intent, Specification, Plan,
  Mission, Review, Verification, Evidence, Deviation, Event, and Run templates. All five
  EASD Skills must read the manifest and core rules, use only the configured
  repository store, honor direct/planned branching, and stop on a missing or
  stale contract.
- **AC-75:** Setup/API/UI expose and validate the data directory, preview the
  created structure, upgrade legacy repositories without overwriting user
  documents, and include focused multi-user stale-write, multi-repository,
  direct/planned, localization, and responsive tests.

## Repository template

```text
.evoflux/easd/
├── config.json                 # bootstrap: store path, skills, rules
├── RULES.md                    # current invariant contract read by all Skills
└── .local/                     # ignored locks/index/session bindings; rebuildable

<data_directory>/              # default documents/easd; user-selectable at init
├── README.md
├── templates/
│   ├── intent.yaml
│   ├── specification.yaml
│   ├── plan.yaml
│   ├── mission.yaml
│   ├── review.yaml
│   ├── verification.yaml
│   ├── evidence.yaml
│   ├── deviation.yaml
│   ├── event.yaml
│   └── run.yaml
└── runs/
    └── <run-slug>--<run-uuid>/
        ├── run.yaml             # lifecycle projection + CAS generation/hash
        ├── intent.yaml
        ├── specifications/0001.yaml
        ├── plans/0001.yaml      # absent for direct delivery
        ├── missions/<uuid>.yaml
        ├── reviews/<uuid>.yaml
        ├── verifications/<uuid>.yaml
        ├── evidence/<uuid>.yaml
        ├── deviations/<uuid>.yaml
        ├── events/<sequence>-<uuid>.yaml
        └── convergence.yaml     # present only after the server gate succeeds
```

## Native spec payload

The accepted revision stores normalized JSON:

```yaml
title: Add deterministic rate limiting
problem: Requests are currently unbounded.
outcome: Requests respect a documented per-client limit.
goals:
  - Bound requests per client.
non_goals:
  - Distributed global rate limiting.
source_refs:
  - documents/plans/rate-limit.md
impact_targets:
  - repository: backend
    path: app/api/routes/rate_limit.py
    module: API
    reason: Owns request admission behavior.
constraints:
  - kind: compatibility
    statement: Preserve existing success response shapes.
    source_refs: [documents/reference/http-api.md]
verification_commands:
  - uv run pytest --no-cov -q tests/api/routes/test_rate_limit.py
risk_tier: cross_layer
criteria:
  - id: AC-1
    statement: The 11th request inside one minute returns 429.
    required: true
    evidence_policy:
      allowed_kinds: [machine, review]
      machine_required: true
      minimum_passes: 1
```

## Native plan payload

For `planned` flow, an accepted Plan is a separate immutable artifact derived
from one exact Spec. Direct flow has no Plan document:

```yaml
spec_hash: <accepted SHA-256>
review_required: true
integration_owner: M3
missions:
  - id: M1
    kind: implementation
    title: Implement API contract
    goal: Satisfy AC-1 inside the accepted service boundary.
    acceptance_criteria: [AC-1]
    target_repositories: [backend]
    target_paths: [app/api/routes/rate_limit.py]
    depends_on: []
    expected_output: Focused implementation and regression evidence.
    constraints: [Preserve the accepted response shape.]
    verification_commands: [uv run pytest --no-cov -q tests/api/routes/test_rate_limit.py]
    isolation: worktree
  - id: M2
    kind: review
    title: Independent contract review
    goal: Challenge AC-1 on the integrated revision.
    acceptance_criteria: [AC-1]
    target_repositories: [backend]
    target_paths: [app/api/routes/rate_limit.py]
    depends_on: [M1]
    expected_output: Cited per-AC review verdict.
    constraints: []
    verification_commands: []
    isolation: shared
```

## Persistence

The version-controlled repository template defined in AC-68–AC-74 is
normative. `run.yaml` carries lifecycle/CAS state; revision directories preserve
Spec and optional Plan history; append-only mission/review/verification/
evidence/deviation/event documents preserve collaboration and audit history.

The application database may materialize a disposable runtime projection so
local sessions and generic delegation machinery remain efficient. Repository
YAML wins on refresh and is sufficient to rebuild that projection; no shared
EASD status depends on one user's SQLite file.

### `delegation_tasks` extension

- nullable `trace_run_id`
- EASD identity remains duplicated in `spec` for replay/readability but the FK
  is the query/index boundary.

## API contract

All canonical routes are Coding-only under `/api/easd`:

- `GET/POST /runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/revisions`
- `POST /runs/{run_id}/revisions/{revision_id}/accept`
- `POST /runs/{run_id}/start` with an authorized Coding session
- `POST /runs/{run_id}/evidence`
- `POST/PATCH /runs/{run_id}/deviations`
- `POST /runs/{run_id}/converge`

Routes validate Coding workspace/project ownership before service calls.
The unlisted `/api/trace` path is retained as a compatibility alias.

## Agent/tool contracts

`TaskSpec` adds optional fields that become required together:

```text
trace_run_id
trace_spec_hash
acceptance_criteria[]
evidence_policy
```

`HandoffArtifact` adds:

```text
criteria_results[] = {criterion_id, result, summary, evidence_ids[]}
deviations[]
```

Machine evidence remains runtime-generated. The member cannot provide trusted
command IDs, exit codes, revision, or artifact hash directly.

## Security and trust

- EASD never widens Coding repository authorization.
- Spec source references are repository-relative labels, not implicit file
  read/write grants.
- Human/manual evidence is visibly lower-trust than machine evidence.
- Agents cannot self-accept a normative spec revision through hidden tool use.
- Critical/cross-layer convergence requires evidence not produced solely by the
  same mission's free-form handoff.
- Evidence payload/output is bounded and secret-redacted through existing
  policies.

## Concurrency, recovery, and idempotency

- Revision version uniqueness is enforced per run.
- Accept is idempotent for the same draft/hash and rejects conflicting accepted
  revisions without explicit supersession.
- Evidence supports caller idempotency through stable source/command IDs where
  available.
- Converge is idempotent when the spec/artifact state has not changed.
- Existing single-writer DB lane and short transactions remain authoritative.
- No model, Git, filesystem scan, or verification process runs inside a DB
  transaction.

## Observability

Minimum metrics/log fields:

- run ID, risk tier, workspace/project (bounded identity), spec hash prefix;
- mission count/status/rework and path-conflict count;
- AC total/passed/failed/waived/uncovered;
- evidence count by kind/result;
- convergence attempts/rejection reasons;
- token/elapsed time from existing session/agent usage.

## Compatibility and rollout

- Existing Coding sessions and delegations remain valid with nullable EASD
  fields.
- Legacy repository setup remains readable as `upgrade_required`. The normal
  setup action writes the current manifest, adds missing Coding-only Skills,
  and preserves existing valid edited Skills; invalid setup requires repair.
- EASD launches as an opt-in workbench surface; no implicit run is created for
  ordinary chat.
- Workflow and Goal engines remain separate. A future adapter may attach them
  to a Development Run after the domain is stable.
- No public “first” claim ships until the benchmark and release-time audit pass.
- Rollback does not silently delete repository files. A user may remove the five
  exact `.evoflux/skills/easd-*` directories and restore a prior manifest in
  version control; setup then reports the repository as needing upgrade rather
  than widening scope or recreating files behind the user's back.

## Verification matrix

| AC group | Evidence |
|---|---|
| AC-1–4 | model/service/API tests and migration upgrade |
| AC-5–8 | delegation ledger/tool/team tests |
| AC-9–12 | evidence service and handoff tests |
| AC-13–16 | deviation/convergence service/API tests |
| AC-17–20 | frontend component/API tests plus logs/metrics assertions |
| AC-21 | docs and Help catalogue parity/link audit |
| AC-22–24 | created Coding Project, benchmark repository, run report and passing tests |
| AC-25–28 | setup service/API tests plus setup and Board/Table/List UI tests |
| AC-29–30 | workbench label tests and recorded persisted-state README demo evidence |
| AC-31–40 | generation service/API/component tests, provenance review, docs, and localized Help |
| AC-41–42 | chat handoff/store/UI tests and README positioning inspection |
| AC-43–49 | run service/API/tool/hook tests plus persisted-state panel lifecycle tests |
| AC-50–54 | setup/skill-discovery/API tests, setup UI tests, skill validation, and localized docs |
| AC-55–64 | plan model/service/API/tool/hook tests, migration upgrade, persisted-state panel tests, and localized docs |

## Ownership and source map

- Models/migration: `app/models/`, `app/migrations/versions/`
- Services: `app/services/trace_service.py`, `app/services/easd_setup_service.py`,
  `app/services/easd_generation_service.py`, and packaged
  `app/easd_skills/easd-*/SKILL.md` templates
- API: `app/api/routes/easd.py`, `app/api/schemas/easd.py`
- Team integration: `app/agent/mode/team/`, `app/agent/verification.py`
- UI: `web/src/components/EvoAgentSpecsPanel.tsx`, `easd.ts`,
  `useEasdQuery.ts`, and workbench owners
- Tests: `tests/services/test_trace_service.py`, route/team/handoff/frontend tests
- Documentation: prior-art research (including
  `documents/research/easd-skill-prior-art-2026-08-24.md`), this plan, current
  feature/architecture/API/Help
