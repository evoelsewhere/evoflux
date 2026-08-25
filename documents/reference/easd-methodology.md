# EASD methodology

Status: normative method
Name: **EASD — Evo Agent Specification-Driven Development**

EASD is EvoFlux's product-executable form of Agent-Driven Development (ADD),
governed by Specification-Driven Development (SDD). **Evo Agent Specs** is its
product and UI name. EASD is designed for work in which agents may plan,
implement, test, review, and integrate code, while humans retain authority over
normative intent and exceptional risk.

EASD does not mean “let agents code autonomously.” It means:

> Accept intent before execution, assign bounded ownership, preserve provenance,
> challenge claims with evidence, and compute Done from explicit gates.

## SDD and ADD responsibilities

SDD and ADD are complementary layers:

| Layer | Owns | Must not do |
|---|---|---|
| SDD | problem, intended outcome, goals, non-goals, risk, source references, acceptance criteria | silently change after execution starts |
| ADD | mission decomposition, role/model/tool allocation, isolation, execution, handoff, review, rework | redefine accepted product intent |
| EASD convergence | evidence policy, mission state, deviations, final artifact identity | accept an agent's prose claim as Done |

The accepted specification is normative. Plans, mission prompts, implementation
notes, and agent messages are derived artifacts. When they disagree, agents
must stop the affected work, record a deviation, or request a new spec revision.

## Core invariants

1. **Immutable intent:** an accepted spec revision has a stable content hash.
2. **Stable criteria:** each observable requirement has a unique AC ID.
3. **Bounded missions:** substantial agent work names its ACs, owned paths,
   dependencies, expected output, constraints, and evidence policy.
4. **Explicit ownership:** concurrent writers use disjoint paths or one named
   integration owner; mutable parallel work uses isolation.
5. **Typed handoff:** a final handoff reports every assigned AC, verification,
   exact revision/artifact identity, and deviations.
6. **Evidence provenance:** machine, review, manual, and waiver evidence never
   collapse into one undifferentiated “passed” flag.
7. **No silent scope expansion:** unauthorized behavior becomes a deviation,
   not an implementation detail.
8. **Computed completion:** convergence is a deterministic service decision,
   separate from agent completion or a lead's summary.
9. **Proportional ceremony:** trivial changes need fewer agents and gates;
   higher-risk changes require stronger separation of duties.
10. **Durable learning:** compare runs using AC outcomes, defects, rework,
    conflicts, latency, and cost—not stylistic preference alone.

## Repository skill bundle

Initializing EASD installs five portable, Coding-only project skills:

| Skill | EASD responsibility |
|---|---|
| `easd-specify` | ground Intent in repository evidence and submit a draft for human review |
| `easd-plan` | compile the accepted hash and ACs into bounded ownership and evidence work |
| `easd-implement` | execute only an active accepted contract and report scope/spec deviations |
| `easd-review` | independently challenge the integrated change with cited AC and boundary findings |
| `easd-verify` | validate integration/evidence, reconcile docs, and prepare convergence |

They live under the initialized repository's `.evoflux/skills/`, not in the
global or built-in catalog. Skill selection provides phase guidance but cannot
change EASD state or trust. The user accepts the specification; runtime services
validate access and lifecycle, admit evidence, and compute convergence. The
[dated prior-art review](../research/easd-skill-prior-art-2026-08-24.md)
explains why the bundle uses these five boundaries.

All five Skills are resumable from durable EASD state rather than conversation
memory. They stop on a stale accepted hash or wrong lifecycle phase. Plan output
maps ACs into bounded missions; Implement and Review return typed per-AC results;
Verify reports evidence gaps and can only recommend that the server convergence
gate be attempted.

## Repository source of truth

`.evoflux/easd/config.json` selects a safe repository-relative data directory.
The owning repository stores Intent, Spec/Plan revisions, lifecycle events,
mission snapshots, reviews, verifications, evidence, deviations, and
convergence as version-controlled YAML. Accepted revision content is immutable;
mutable projections use generation/hash compare-and-swap and atomic rename.

Application SQLite and `.evoflux/easd/.local/` may hold only rebuildable runtime
projection, locks, or session bindings. They do not define shared status. Git
repository documents win so another collaborator can continue without the
original machine or chat.

The lifecycle's Learn phase is intentionally not a sixth Skill yet. It remains
backed by run telemetry and benchmark analysis until EvoFlux exposes a bounded
read-only run-report context with convergence, rework, deviation, cost, and
final-artifact provenance; this prevents retrospective prose from outrunning
authoritative evidence.

## Lifecycle

### 1. Author and Accept

Persist minimal Intent—title, problem and optional outcome—before choosing an
implementation. A bound Coding lead may then inspect authorized repository
evidence, ask clarifying questions and submit a typed specification draft. That
submission changes the run to human review; it does not authorize execution.

The specification contains goals, non-goals, sources, affected targets, typed
constraints, planned verification commands, risk tier, and ACs with evidence
policies. Acceptance freezes a normalized revision and hash.

Before acceptance, the user may ask the EASD authoring agent to propose Scope
and Proof from authorized repository context. This is analysis, not authority:
low-confidence product choices become clarifying questions; proposals retain
confidence/provenance and require explicit review/apply. The authoring tool can
create a draft revision but can never accept, start implementation, or converge
the run on the user's behalf.

Exit gate: one accepted revision exists and every required behavior has a stable
AC ID. Unresolved product choices remain explicit rather than hidden in a task.

### 2. Select driven flow and compile when required

The specification recommends `direct` or `planned`, and the user accepts that
choice with the Spec. `direct` skips Plan only for low-risk, single-boundary
work. Multi-repository, cross-layer, security, persistence/migration,
compatibility, concurrency, and critical changes require `planned`.

For planned flow, the user explicitly starts Plan. The lead maps ACs to a
typed mission DAG and submits it as a hash-addressed plan revision. A mission
has one coherent ownership boundary and is independently checkable. Shared
contracts are designed before dependent implementation missions begin.

Compilation checks:

- every required AC has an implementation/integration owner;
- every run has an explicit review mission;
- every accepted Proof command belongs to an explicit verification mission;
- target paths do not overlap accidentally;
- dependencies represent real contract/data order rather than team hierarchy;
- integration and final review have named owners;
- no mission can broaden the accepted spec through its prompt.

The server validates the exact spec hash, graph, AC coverage, repository/path
scope, verification ownership, and review policy. Only the user's
**Approve plan** action selects the
executable plan hash. EASD lets the lead perform compilation; deterministic
automatic mission compilation remains a future capability.

Exit gate: direct eligibility has been server-validated, or one accepted Plan
revision exists for the current accepted Spec hash. Spec changes invalidate the
choice and any Plan and require approval again.

### 3. Allocate

Choose agents, models, reasoning levels, tools, permissions, repositories, and
isolation according to the mission—not as a single global model choice.

Default GPT-5.6 policy for EvoFlux Coding mode:

| Responsibility | Default | Why |
|---|---|---|
| Lead/convergence owner | GPT-5.6 Sol, high | cross-mission reasoning and gate ownership |
| Architect | GPT-5.6 Sol, high | public contracts and dependency design |
| Explorer | GPT-5.6 Luna or Terra, medium | bounded source mapping and read-heavy work |
| Builder | GPT-5.6 Terra, medium/high | efficient focused implementation |
| Independent verifier | GPT-5.6 Sol, high | adversarial cross-criterion review |

Model choice is policy, not evidence. A stronger model never weakens test,
review, permission, or convergence requirements.

### 4. Execute

Agents work only within their mission contract. Existing repository instructions,
sandbox policy, path claims, worktrees, dependency gates, and permission prompts
still apply. Agents may communicate discoveries, but another mission owns any
resulting change until ownership is explicitly revised.

Every delegation names the exact run, spec hash, plan hash, approved plan mission
ID, AC set, and bounded repository/path scope. The server rejects work from the
wrong phase or a task that does not match its plan mission.

The desired execution unit is a small commit or artifact snapshot that can be
reviewed, rejected, retried, and traced without replaying the whole run.

### 5. Challenge

After implementation missions are terminal, the user starts Review. Treat every
handoff as a claim requiring examination. Runtime verification binds real
command results to the changed-file snapshot. For isolated worktrees, evidence
is admitted only after lead review accepts the merge; a rejected worktree does
not satisfy an AC merely because its local tests passed.

Higher-risk runs add an independent reviewer that did not author the change.
The reviewer inspects the integrated revision, reruns checks, maps findings to
ACs, and reports concrete sources. Review prose without sources is not machine
evidence. The review submission uses runtime identity and, when delegated, must
match the approved review mission; public payloads cannot claim
independent-review trust.

### 6. Verify and Converge

After review missions are terminal and required passing review evidence exists,
the user starts Verify. Verify re-evaluates the accepted spec/plan hashes, AC
matrix, planned commands, integration, deviations, docs, and manual-required
gaps. Approved verification missions produce a fresh CompletionContract bound
to the current repository revision even when the verifier changed no product
file. Verify can recommend convergence but cannot call itself Done.

The user then invokes Converge. The server evaluates persisted state and accepts
only a `verifying` run. A run is Done only when:

- an accepted spec revision is active;
- an accepted plan revision for that spec hash is active;
- every required AC is passed or explicitly waived under its policy;
- required machine/review evidence exists;
- all EASD missions are terminal and accepted;
- no blocking deviation remains open or merely approved;
- cross-layer/critical review requirements are satisfied;
- the report records spec/plan hashes and final Git revision when available.

A rejected convergence attempt is useful evidence. Structured rejection reasons
drive rework; they are not overwritten by the later successful result.

### 7. Learn

After convergence, compare intended and actual execution:

- AC pass/fail/waive/uncovered counts;
- escaped defects and post-convergence regressions;
- attempts, rejection reasons, conflicts, and scope deviations;
- critical-path duration and parallel width;
- token/tool cost by role and passed AC;
- model/role allocation and human interventions.

Learning may recommend a future allocation, but it cannot retroactively change
the accepted spec or evidence trust level.

## Contracts

### Specification contract

Minimum fields:

```text
title, problem, outcome
goals[], non_goals[], source_refs[], risk_tier
criteria[] = {id, statement, required, evidence_policy}
```

Agent-assisted authoring may begin from title and problem alone and draft the
intended outcome from authorized repository evidence. Outcome remains mandatory
in the reviewed specification before acceptance; generation never accepts that
draft on the user's behalf.

An AC should be observable and falsifiable. “Code is clean” is weak; “the 11th
request inside one minute returns 429” identifies an observable boundary.

### Optional Plan contract

```text
spec_hash, review_required, integration_owner
missions[] = {
  id, kind, title, goal, acceptance_criteria[],
  target_repositories[], target_paths[], depends_on[], expected_output,
  constraints[], verification_commands[], isolation
}
```

For `planned`, the graph is acyclic, covers every required AC through implementation/
integration ownership, stays inside accepted Scope, and contains an independent
review mission when policy requires it. Agent submission creates only a draft;
the user's plan acceptance establishes the executable plan hash.

### Mission contract

Minimum EASD identity for both flows:

```text
trace_run_id, trace_spec_hash
acceptance_criteria[]
goal, expected_output, constraints[], evidence_policy
target_paths[], dependencies[], isolation, target_repos[]
```

Planned flow additionally requires `trace_plan_hash` and `plan_mission_id`.
Direct flow must omit them and stays bounded by the accepted Spec.

Mission IDs and attempts remain stable across rejection/rework so the history
shows improvement instead of replacing the failed attempt.

### Handoff contract

```text
summary, findings[], exact revision/artifact
verification = {method, commands, exit codes, artifact hash}
criteria_results[] = {criterion_id, result, summary, evidence_ids[]}
deviations[]
```

A handoff with changed files but no passing runtime CompletionContract is not an
acceptable machine-verified delivery. For worktrees, handoff enters review; lead
merge acceptance is the evidence-admission boundary.

### Evidence contract

| Kind | Producer | Trust and use |
|---|---|---|
| `machine` | EvoFlux runtime | process result bound to command IDs and artifact/revision |
| `review` | independent agent or human | concrete inspection/check evidence with provenance |
| `manual` | user/lead | explicit observation; never promoted to machine evidence |
| `waiver` | authorized human | accepts an unmet AC with a visible reason |

Public API/UI callers cannot manufacture `machine` evidence. Failed and
inconclusive evidence remains in the ledger even after later success.

### Deviation contract

A deviation records the originating spec hash, affected AC/mission, description,
blocking state, proposed change, and resolution. Normative change requires a new
accepted revision; resolving against the same hash is permitted only for an
explicitly non-normative clarification.

## Roles and separation of duties

- **Spec owner:** accepts normative intent and normative revisions.
- **Lead/convergence owner:** compiles and allocates missions, reviews handoffs,
  integrates accepted work, and initiates convergence.
- **Mission owner:** implements only the assigned contract and returns evidence.
- **Integration owner:** resolves shared contracts and produces the final tree.
- **Independent verifier:** challenges the integrated result without authorship
  responsibility for it.
- **EASD service:** validates identities and computes the AC matrix/gates.

One person or agent may hold multiple roles for trivial/standard work. For
cross-layer and critical work, author and verifier should be different actors.
The service—not either actor—owns the final convergence calculation.

## Risk scaling

| Tier | Typical change | Minimum operating shape |
|---|---|---|
| `trivial` | typo, narrow docs, mechanical rename | one owner; manual or machine evidence; no forced fan-out |
| `standard` | isolated feature/fix | accepted ACs; focused mission; machine or review evidence |
| `cross_layer` | API/UI/data or multiple owners | mission DAG; isolation; machine evidence; independent integrated review |
| `critical` | auth, permissions, migrations, concurrency, production | explicit human acceptance; isolation; upgrade/failure tests; independent review; no self-waiver |

Parallelism is a consequence of independent ownership, not a success metric.
Do not create extra agents when coordination cost exceeds the work.

## Rework rules

1. Reject the handoff with criterion-specific issues.
2. Preserve the failed evidence and rejection reason.
3. Increment the same mission attempt unless ownership/spec changed.
4. If the mission contract was wrong but the spec remains valid, recompile the
   mission without changing the spec.
5. If intended behavior changed, record a blocking deviation and accept a new
   spec revision before continuing.
6. Rerun affected checks and independent review on the integrated result.

## Anti-patterns

- **Prompt-as-spec:** a long chat message with no immutable acceptance point.
- **Agent says Done:** treating a polished summary as convergence.
- **Evidence laundering:** entering a human claim as machine evidence.
- **Review-before-integration:** accepting isolated worktree tests as proof of
  the final tree.
- **Silent expansion:** shipping “helpful” behavior absent from accepted intent.
- **Orphan AC:** a required criterion with no owner/evidence plan.
- **Shared-file swarm:** multiple writers editing the same contract without an
  integration owner.
- **Model prestige:** using a larger model as a substitute for constraints and
  verification.
- **Green-only report:** deleting failed attempts, conflicts, or rework from the
  benchmark narrative.

## Worked example

For “add per-client rate limiting,” the spec accepts `AC-1` (11th request returns
429), `AC-2` (window resets), and `AC-3` (configuration documented). The lead
allocates a backend policy mission (`AC-1`, `AC-2`), a config/help mission
(`AC-3`), and an integrated verifier (`AC-1`–`AC-3`). Builders work in disjoint
paths/worktrees. A discovered distributed-limit requirement becomes a blocking
deviation because distributed behavior was a non-goal. Convergence waits for a
new spec revision or rejection of that deviation, accepted merges, machine
tests, and independent review of the final revision.

## Maturity model

| Level | Description |
|---|---|
| 0 — Prompted | agents receive instructions; completion is conversational |
| 1 — Specified | accepted spec/ACs exist, but execution/evidence is mostly manual |
| 2 — Traceable | missions map to ACs with durable ownership and attempts |
| 3 — Evidence-gated | machine/review provenance and deviations control convergence |
| 4 — Learning | validated run outcomes improve allocation and policy |

EvoFlux EASD targets Level 3 and records the metrics needed to evaluate
Level 4. It does not claim autonomous self-improvement or automatic mission
compilation today.

## Method governance

- Version the EASD schema and this normative document together.
- Treat feature, architecture, API, and in-app Help pages as the implemented
  product contract; dated research/plans are supporting records.
- Publish reproducible benchmark seed/final revisions and failures.
- Re-audit competitive “first” claims at release time. EASD may be presented as
  EvoFlux's ADD protocol without claiming invention of SDD, ADD, multi-agent
  coding, or evidence-based engineering.

Related documents: [Evo Agent Specs](../features/evo-agent-specs.md),
[EASD architecture](../architecture/evo-agent-specs.md), [HTTP API](http-api.md),
[prior-art audit](../research/easd-prior-art-2026-08-23.md), and
[benchmark protocol](../plans/easd-benchmark-protocol.md).
