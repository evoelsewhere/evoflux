# Evo Agent Specs

**Evo Agent Specs** is the Coding-mode product surface for **EASD — Evo Agent
Specification-Driven Development**. EASD is EvoFlux's spec-governed
Agent-Driven Development methodology.

EASD separates two responsibilities:

- SDD defines the normative problem, outcome, goals, non-goals, risk tier, and
  acceptance criteria.
- ADD executes that accepted specification through bounded agent missions,
  evidence, deviations, and convergence gates.

## Product flow

The Run header includes a server-derived guided action rail for Intent → Spec →
Plan → Implement → Review → Verify → Done. It makes direct flow's skipped Plan
explicit, emphasizes the next action, and shows mission/evidence/deviation or
command blockers before a mutation is attempted. Approve specification,
Approve plan, and Converge each require a confirmation summarizing the exact
contract or evidence state.

Each Run also has **Overview** and **Trace** workspaces. Trace is a read-only
server projection of the repository-owned Run, Spec/Plan revisions, ACs,
mission contracts and attempts, evidence, deviations, convergence, and ordered
events. Users can filter by AC, inspect exact entity hashes/status/ownership,
and see the current action blockers as trace gaps. Narrow panels present the
activity ledger first; maximized panels add the relationship map and inspector.

The **Recovery** workspace derives one safe retry from current persisted state.
It previews phase transition, exact Spec/Plan/session identities, and preserved
history before confirmation. Redraft/Replan reuse the existing revision-safe
paths; active implementation, Review, and Verify retries remain in the same
phase, append a recovery event, then reopen the matching EASD chat prompt.
Stale repository generations fail closed. Converged Runs are never reopened.

An open Run maintains a scoped SSE connection. The stream registers presence,
replays repository events after the client's last sequence, and then delivers
post-commit lifecycle/artifact/recovery events. The client deduplicates sequence
overlap and invalidates existing detail, Trace, Recovery, and list queries;
TanStack Query remains the durable UI authority. Header presence is ephemeral
and shows only viewer count, while all activity remains repository-owned.

1. Open a Coding workspace/session and choose **Agent Specification-Driven
   Development** in the workbench.
2. Initialize EASD for every repository in the workspace or Coding Project.
   The repository-relative data directory defaults to `documents/easd` and can
   be changed during setup. EvoFlux
   adds `.evoflux/easd/config.json`, the shared core rules, standard YAML
   templates, and five Coding-only project skills under `.evoflux/skills/`.
3. Create a run from **Run title**, **Problem**, and an optional intended
   outcome. This persists only Intent: no specification revision exists and no
   implementation is authorized.
4. Choose **Draft specification in chat**. EvoFlux atomically binds the Intent
   to an idle authorized Coding session and explicitly selects the repository's
   `easd-specify` Skill. The lead reads project `AGENTS.md`, docs,
   source/configuration and tests, asks clarifying questions, then calls the
   lead-only `easd_submit_specification` tool with a complete typed draft.
5. The tool validates repository scope and persists one immutable-hash draft;
   it cannot approve, start implementation or converge. The detail panel changes
   from Drafting to **Review before approval** only after this durable write.
   The successful chat tool row exposes **Review specification**, which opens
   this exact Run in the EASD workbench even though the agent turn stops without
   final prose. **Retry drafting** repeats an interrupted authoring attempt;
   **Redraft in chat** moves `draft → authoring` and preserves the current draft
   until a newer revision is persisted.
6. Review outcome, goals/non-goals, impact targets, constraints, risk, AC
   evidence policies, commands, and the agent's driven-flow recommendation.
   `direct` skips Plan only for a low-risk single-boundary change; `planned` is
   mandatory for multi-repo, cross-layer, security, persistence/migration,
   compatibility, concurrency, and critical boundaries. Edit by saving a newer
   draft, then explicitly choose **Approve specification**. This user action
   accepts both the immutable Spec hash and its flow. Acceptance also publishes
   a hash-identical immutable copy into the repository's common `specs/`
   catalogue; the Run-local revision remains its audit snapshot.
7. For `planned`, choose **Run plan in chat**. EvoFlux moves `accepted → planning`
   and selects `easd-plan`. The lead compiles a typed acyclic mission graph from
   the exact accepted spec hash, then calls the lead-only `easd_submit_plan`
   tool. Product files, implementation delegation, and automatic approval stay
   blocked.
8. Review the persisted plan hash, AC ownership, mission kinds, repositories/
   paths, dependencies, expected outputs, isolation, verification commands, and
   independent-review policy. Every plan must have a Review mission and every
   accepted Proof command must have an explicit verification mission. Only
   explicit **Approve plan** moves
   `plan_review → planned`; agent prose cannot unlock implementation. The
   successful tool row exposes **Review plan**. **Retry planning** repeats an
   interrupted attempt, while **Replan in chat** moves
   `plan_review → planning` and keeps the prior draft until its replacement is
   persisted.
9. Choose **Run implementation in chat**. Planned flow requires accepted Spec
   and Plan and moves `planned → active`; direct flow requires only its accepted
   Spec and moves `accepted → active`. Planned delegations include exact
   spec/plan/mission identity; direct delegations omit Plan identity and remain
   bounded by accepted ACs and Scope.
10. Final implementation handoffs report every assigned criterion. Runtime-generated
   CompletionContract results are persisted as machine evidence when the
   mission completes; isolated worktree evidence waits for lead merge acceptance.
11. Choose **Run review in chat** only after implementation missions are
    terminal. `active → reviewing` selects `easd-review`; product-file mutation
    is blocked. `easd_submit_review` persists cited per-AC review evidence only
    for the approved review mission and with runtime reviewer identity. Plans
    requiring independence accept only a member who did not implement the
    reviewed ACs.
12. Choose **Run verify in chat** only after review missions are terminal and
    required passing review evidence exists. `reviewing → verifying` selects
    `easd-verify`; approved verification missions produce fresh revision-bound
    CompletionContracts even though the phase is read-only, then evaluate the
    current AC matrix, integration, deviations, docs, and manual-required gaps
    without changing implementation or declaring Done.
13. Choose **Converge**. The server accepts only `verifying` runs and returns a
    durable report bound to the accepted Spec and, for planned flow, its Plan
    hash when every gate is satisfied.

The product name remains **Evo Agent Specs**. The workbench uses the explicit
**Agent Specification-Driven Development** label so users understand the
surface before opening it; **EASD** remains the stable methodology and API
identifier.

## Repository initialization

Initialization is repository-local and idempotent. Project scope is ready only
when every live repository workspace is initialized. The setup screen shows
per-repository state (`not_initialized`, `upgrade_required`, `ready`, or
`invalid`) and supports initializing one repository, upgrading an older valid
setup, initializing all remaining repositories, or explicitly repairing invalid
setup.

| Repository artifact | Purpose |
|---|---|
| `.evoflux/easd/config.json` | bootstrap manifest for the configured data directory, rules, templates, and skill bundle |
| `.evoflux/easd/RULES.md` | normative core rules shared by every phase Skill |
| `<data_directory>/index.yaml` and section READMEs | EASD knowledge-base navigation, authority and retention contract |
| `<data_directory>/specs/` | discoverable accepted Specs with immutable revisions and a small current-revision index |
| `<data_directory>/{features,architecture,reference}/` | adopted living product behavior, boundaries and exact contracts |
| `<data_directory>/{guides,development,records,images}/` | task guidance, contributor procedures, historical records and media |
| `<data_directory>/templates/` | standard YAML and Markdown artifact shapes |
| `<data_directory>/runs/<slug>--<uuid>/` | version-controlled lifecycle, revisions, status history, missions, evidence, deviations, and convergence |
| `.evoflux/easd/.local/` | ignored rebuildable locks/index/session bindings; never normative |
| `.evoflux/skills/easd-{specify,plan,implement,review,verify}/SKILL.md` | portable EASD phase guidance discovered only in this repository |
| `.evoflux/skills/easd-*/.evoflux.json` | limits the EASD skills to Coding mode |

Run creation returns `409 easd_setup_required` until the entire selected scope
is ready. Legacy Run-only setups report `upgrade_required` and add only missing
knowledge skeleton/templates without replacing existing valid edited Skills or
moving/copying repository documentation. Invalid configuration, symlinks or
Skills are never silently overwritten; repair requires an explicit action.

The installed skills are not global seeds or EvoFlux built-ins. Standard skill
precedence makes them available only when their authorized repository is part
of the active Coding workspace/project. They provide phase-specific operating
guidance. EASD chat handoffs use an exact `$easd-*` directive so the matching
Skill is loaded through the normal explicit-selection path rather than eagerly
injecting all five bodies. EASD services and runtime hooks remain authoritative
for repository scope, lifecycle transitions, approval, evidence trust, and
convergence.

Every Skill first reads the manifest, `RULES.md`, configured repository store,
and current phase/hash state. A stale
plan, mission, review snapshot, or verification result is invalidated rather
than patched forward from chat memory. Plan output carries mission AC/path/
dependency/evidence ownership; Implement and Review use typed per-AC handoffs;
Verify emits an evidence-gap report and recommendation but never a convergence
claim.

## Runs workspace

Project-scoped run queries include runs owned by every project repository. The
panel provides:

- **Board:** status lanes for Planning, In progress, Completed, and Needs
  attention;
- **Table:** dense comparison across repository, risk, status, and update time;
- **List:** compact navigation for smaller workbench widths;
- search by run title, status, risk tier, or repository;
- remembered view preference through the shared storage-key registry;
- a separate run-detail workspace for ACs, missions, evidence, deviations, and
  convergence actions;
- shared list/detail cache invalidation after lifecycle and evidence mutations,
  so Board, Table, and List cannot retain a stale run status.

## Agent-assisted specification authoring

The primary UI path is run-first chat authoring: minimal Intent is persisted,
the bound Coding lead drafts from repository evidence, and the typed submission
tool creates the review revision. The manual draft editor can still call the
read-only generation API to regenerate Outcome/Scope or Proof without granting
that model lifecycle authority.

`POST /api/easd/generate` is an explicit, read-only model action. It requires a
Coding session and resolves the same workspace/Coding Project repository set as
run creation. Database reads close before repository inspection or the model
call. The context builder ignores symlink escapes and generated/vendor trees,
bounds repository maps and excerpts, and includes repository `AGENTS.md`,
current docs, relevant source/configuration, and tests across authorized repos.

The response is never persisted automatically. It contains:

- an observable intended-outcome draft when target is `scope` or `both`;
- generated goals, non-goals, source references, affected repository/file/module
  targets and discovered architecture/compatibility/security/operational/product
  constraints;
- observable ACs with individual evidence policies, proposed risk tier,
  verification commands and independent-review policy;
- confidence, rationale, clarification questions and hash-addressed provenance;
- a base fingerprint used by the UI to detect edits made after generation.

Outcome/Scope and Proof are applied independently. If the user changed either
section after generation, the first Apply action stops and asks for a second
explicit replacement confirmation. Scope regeneration also regenerates its
outcome draft; Proof regeneration leaves the current Outcome/Scope proposal
intact.
Loading can be cancelled, errors can be retried, and no generation path calls
Create draft, Accept spec/plan, Start implementation, Review, Verify, or Converge.

The review surface shows exact current/proposed values for every changed field,
not only aggregate counts. Clarification answers are bound to stable question
IDs, and authoring metadata persists provider/model, token usage, confidence,
source hashes, applied sections, and post-apply edits with the draft revision.

Two recordings from the real local EASD Benchmark are available in the project
README: the [20-minute complete agent lifecycle](../../README.md#real-easd-ui-runs)
from run creation through linked chat, implementation, tests, independent
review, machine evidence and Convergence; and the Board/Table/List plus
acceptance-matrix inspection. They use persisted API state and the real
convergence service rather than staged mock data.

## Acceptance matrix

Each criterion is computed from persisted mission/evidence state:

| State | Meaning |
|---|---|
| `uncovered` | No mission/evidence owns the criterion |
| `in_progress` | A mission or evidence exists but the policy is not satisfied |
| `passed` | Passing evidence satisfies minimum/allowed-kind/machine rules |
| `failed` | Failing evidence exists without a satisfactory passing set |
| `waived` | Explicit waiver evidence exists |

Manual evidence never becomes machine evidence. A machine result is trusted
only when it came from the runtime's `CompletionContract`, which records command
IDs, exit codes, Git revision, artifact hash, normalized changed paths, and
whether each check came from the accepted Proof. Changed paths retain repository
identity in multi-repo projects, so an identical relative path in another repo
cannot satisfy Scope. Accepted planned commands run automatically without a
shell; changed paths outside Scope block final handoff.

## Mission contract

EASD extends the existing `team_delegate` contract with:

- `trace_run_id`;
- `trace_spec_hash`;
- `acceptance_criteria`;
- `target_paths` and `target_repos`, validated against accepted impact targets;
- optional mission-specific `evidence_policy`.

Planned flow additionally requires `trace_plan_hash` and `plan_mission_id`.
Direct flow must omit both; the accepted Spec is its executable contract.

The runtime rejects a stale hash, unknown AC, inactive run, or run from another
session/scope before dispatch. Normal delegations remain backward compatible.
All existing dependency, deadline, exclusive-path, worktree, handoff/rework,
and durable replay behavior remains active.

## Deviation contract

A deviation makes scope/spec drift visible. Blocking `open` or `approved`
deviations prevent convergence. A normative deviation cannot resolve against
the same accepted spec hash: the user/lead must accept a new immutable revision.
A rejected deviation is terminal and does not authorize the proposed behavior.
Deviations reported by an EASD-bound final handoff are imported as blocking
mission deviations instead of remaining only in agent prose.

## Convergence

The convergence service, not the agent, owns Done. It rejects when:

- a required AC is not passed or waived;
- an EASD mission is pending, blocked, in review, or failed;
- a cancelled mission leaves required ACs uncovered;
- a blocking deviation remains open/approved;
- any accepted planned verification command lacks passing machine evidence;
- cross-layer/critical work lacks independent passing review evidence.

The report stores spec revision/hash, current Git revision when available, AC
counts, mission counts, evidence/deviation IDs, and convergence timestamp.

## Risk tiers

- `trivial`: no mandatory agent fan-out; manual evidence may be sufficient.
- `standard`: normal feature/fix; machine evidence is the recommended default.
- `cross_layer`: mission graph plus machine evidence and independent review.
- `critical`: human-approved spec, isolated missions, machine evidence, and
  independent review.

## Current limitations

- Native draft creation is implemented; automatic import/normalization of Spec
  Kit and Kiro artifacts is future work.
- For planned flow, mission compilation remains lead-driven, but its typed plan graph is persisted,
  hash-addressed, validated, and user-approved before delegation; deterministic
  automatic plan generation remains future work.
- EASD realtime is local-host Run collaboration; remote cross-host transport is
  not yet provided.
- Deviation resolution and spec/plan revision authoring remain API-backed; the
  detail view exposes the guided phase flow, readiness blockers, and complete
  approved plan mission contract. Trace provides a read-only relationship map,
  not a visual DAG editor.
- One GPT-5.6 benchmark run is recorded; adaptive role/model selection and
  learning recommendations wait for multiple comparable runs and a control.

## Source and tests

Primary code:

- repository store/projection: `easd_repository_store.py`,
  `easd_repository_sync.py`, and the current unversioned config contract; the application DB contains
  only a rebuildable runtime projection for local sessions and generic tasks;
- setup: `easd_setup_service.py`, packaged `app/easd_skills/` templates,
  `/api/easd/setup`, and repository-local `.evoflux/easd/` plus
  `.evoflux/skills/easd-*` artifacts;
- authoring: `easd_generation_service.py`, `/api/easd/generate`, provider/model
  context, client-side proposal review state, and persisted applied-generation
  provenance on each draft revision;
- contracts/service/API: `trace_contracts.py`, `trace_service.py`, `/api/easd`;
- runtime: EASD phase guards/context hook, lead-only
  `easd_submit_specification`/`easd_submit_plan`, runtime-identified
  `easd_submit_review`, and plan-bound team delegation/handoff integration;
- UI: `EvoAgentSpecsPanel`, `easd.ts`, `useEasdQuery.ts`, and Coding workbench
  registration;
- observability: `EVOFLUX_trace_operations_total` plus structured logs.

`trace_*` model/service names and the hidden `/api/trace` alias remain local
compatibility identifiers during migration. They are not the collaborative
source of truth: repository YAML wins and can rebuild the local projection.

Focused tests cover repository-store structure/CAS/immutable revisions/mission
status projection, direct/planned branching, authorized multi-repo generation,
clarification/provenance and overwrite safety, chat binding/handoff, activation
uniqueness, mission binding, evidence idempotency/trust, deviations,
convergence, migration, API, context injection, team schemas, workbench
availability, and panel rendering.

See [EASD architecture](../architecture/evo-agent-specs.md), the
[normative EASD methodology](../reference/easd-methodology.md), the
[accepted implementation specification](../plans/easd-methodology-and-coding-mode.md),
the [prior-art audit](../research/easd-prior-art-2026-08-23.md), and the
[completed benchmark report](../analysis/easd-benchmark-2026-08-24.md).
