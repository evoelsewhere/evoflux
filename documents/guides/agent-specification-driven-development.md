# Agent Specification-Driven Development

Agent Specification-Driven Development (EASD) is EvoFlux's contract-first workflow for agentic software delivery. It turns a user's intent into an immutable, reviewable specification; binds implementation to explicit acceptance criteria and scope; and requires revision-bound evidence before work can converge.

This guide explains how to use the workflow. The normative rules are defined in [EASD Core Rules](../../.evoflux/easd/RULES.md), and the repository-local knowledge taxonomy is defined in the [Evo Agent Specs knowledge base](../README.md).

## Why EASD exists

Coding agents can produce changes quickly, but speed without a durable contract creates predictable failure modes:

- requirements drift during implementation;
- agents silently broaden scope or ownership;
- tests prove incidental behavior rather than the intended outcome;
- reviews evaluate summaries instead of the integrated change;
- stale plans or evidence are reused after the code or specification changes;
- an agent's confidence is mistaken for proof that the work is done.

EASD separates product authority, execution, and evidence. Humans decide what is accepted and when the workflow advances. Agents draft, plan, implement, challenge, and verify within explicit boundaries. A deterministic convergence gate decides whether the persisted evidence satisfies the accepted contract.

## Core principles

1. **Intent and specification precede code.** Product files must not change until the user accepts an observable, testable specification.
2. **Accepted contracts are immutable.** A changed requirement creates a new revision and content hash; it never rewrites an accepted Spec or Plan in place.
3. **Humans own lifecycle authority.** Only the user may approve a Spec or Plan, start the next phase, authorize a normative deviation, or invoke Converge.
4. **Use the lightest safe flow.** A low-risk, single-boundary change may use `direct`; cross-layer, multi-repository, security, migration, persistence, compatibility, concurrency, and critical work requires `planned`.
5. **Scope and ownership are explicit.** Every mission identifies its acceptance criteria, repositories, paths, dependencies, expected output, constraints, and verification commands.
6. **Evidence precedes Done.** Agent prose, task completion, and confidence are not proof. Evidence must be tied to the accepted Spec and the inspected or tested revision.
7. **Review is mandatory.** Reviewer independence increases with risk; cross-layer and critical work requires a reviewer who did not implement the reviewed criteria.
8. **Stale state fails closed.** Hash or generation conflicts stop the workflow until the current state is reconciled.

## Lifecycle

```text
Intent
  -> Spec authoring
  -> User accepts Spec
  -> Direct flow OR Plan authoring
  -> User starts implementation
  -> Implement
  -> User starts Review
  -> Review
  -> User starts Verify
  -> Verify
  -> User invokes Converge
  -> Converged or Rework
```

Each transition is an authority boundary. An agent may prepare the next artifact or recommendation, but it must not silently cross a user-controlled gate.

### 1. Intent

Intent captures the requested problem and desired outcome before solution details dominate the discussion.

A useful Intent states:

- the current observable problem;
- why the problem matters;
- the outcome the user wants;
- the repository that owns the behavior.

Intent is exploratory. It is not permission to modify product code.

### 2. Specify

The specification turns Intent and repository evidence into a behavior-first contract. The authoring agent inspects relevant documentation, source, configuration, migrations, and focused tests before drafting.

A complete Spec includes:

- title, problem, and observable outcome;
- goals and explicit non-goals;
- source references with repository-qualified paths;
- impact targets and the reason each target is affected;
- architecture, compatibility, security, operational, or product constraints;
- risk tier and recommended delivery flow;
- stable acceptance criteria;
- an evidence policy for every acceptance criterion;
- canonical verification commands that can run without shell composition.

The draft is persisted for human review. It becomes normative only after the user accepts it. Acceptance publishes a hash-identical immutable revision under [`documents/specs/`](../specs/README.md).

### 3. Choose direct or planned delivery

| Flow | Use when | Contract binding |
| --- | --- | --- |
| `direct` | The accepted change is low-risk and contained within one boundary | Implementation binds directly to the accepted Spec, owned acceptance criteria, repositories, and paths |
| `planned` | The change is cross-layer, multi-repository, security-sensitive, persistence-related, compatibility-sensitive, concurrent, critical, or needs dependent work | Implementation binds to both the accepted Spec and an accepted Plan mission |

`direct` skips Plan authoring, not Review, Verify, or Converge.

### 4. Plan

For a planned flow, the Plan compiles the accepted Spec into immutable missions. It must not reinterpret or weaken accepted behavior.

Each mission defines:

- a stable mission ID, kind, title, and goal;
- the acceptance criteria it owns;
- target repositories and paths;
- dependencies;
- expected output;
- constraints;
- verification commands;
- workspace isolation.

The Plan should make ownership non-overlapping, dependency order acyclic, and integration responsibility explicit. The user must accept the Plan before implementation begins.

### 5. Implement

Implementation is bounded by the accepted hash and assigned ownership. The implementing agent should:

1. re-read the current Run, accepted Spec, flow, mission, and working-tree baseline;
2. inspect the nearest repository instructions and existing implementation patterns;
3. add a focused regression first for observable behavior when practical;
4. make the smallest coherent change that satisfies the owned criteria;
5. run the accepted repository-native checks;
6. report exact changed paths, command outcomes, criterion results, evidence gaps, and deviations.

If implementation reveals that the accepted contract is wrong or scope must expand, the agent stops that slice and records a deviation. It does not silently alter the contract or weaken an acceptance criterion to match the code.

### 6. Review

Review is a read-only challenge of the integrated change against the exact accepted Spec hash. The reviewer inspects the implementation and evidence directly rather than treating the implementer's summary as authoritative.

The review covers, where applicable:

- happy and error paths;
- authorization and trust boundaries;
- domain invariants;
- recovery and concurrency;
- compatibility and cross-layer behavior;
- scope, ownership, and dependency direction;
- documentation required by the accepted behavior.

Every finding cites an acceptance criterion or contract clause and repository source evidence. Review produces a per-criterion verdict: `passed`, `failed`, or `inconclusive`.

### 7. Verify

Verification is the final integration and evidence gate before convergence. It evaluates three dimensions:

- **Completeness:** all required acceptance criteria, missions, commands, documentation, and reviews are covered.
- **Correctness:** the integrated behavior satisfies the accepted scenarios and invariants.
- **Coherence:** architecture, interfaces, terminology, and living documentation agree with the delivered change.

Evidence retains its provenance:

- `machine` for command or test results;
- `review` for persisted reviewer verdicts;
- `manual` for human-observed behavior;
- `waiver` for an explicitly authorized exception.

Verification recommends one of three outcomes: `ready for convergence`, `rework required`, or `manual verification required`. It does not itself declare the Run converged.

### 8. Converge

Converge is a user-invoked deterministic decision over the persisted Run state. A Run can converge only when the active accepted hash, required evidence policies, missions, reviews, commands, documentation obligations, and deviations satisfy the gate.

Convergence is therefore stronger than "the agent finished" or "tests passed." It means the evidence for the integrated revision satisfies the accepted contract.

## Acceptance criteria and evidence policy

Acceptance criteria describe observable outcomes, not implementation tasks.

Weak criterion:

> Add validation to the session service.

Stronger criterion:

> When a client submits a session request without a repository identifier, the API rejects the request with the existing validation error shape and does not persist a session.

Each criterion has an evidence policy:

| Field | Meaning |
| --- | --- |
| `allowed_kinds` | Evidence types that may satisfy the criterion: `machine`, `review`, `manual`, or `waiver` |
| `machine_required` | Whether at least one machine-generated result is mandatory |
| `minimum_passes` | Minimum number of passing evidence records required |

A good criterion is stable across implementation choices, has a clear pass/fail signal, includes relevant failure or authorization behavior, and can be traced to concrete evidence.

## Contract and storage model

EASD separates shared, version-controlled knowledge from local operational state.

| Location | Purpose | Authority |
| --- | --- | --- |
| `documents/specs/` | Accepted immutable behavior specifications | Normative |
| `documents/features/` | Explicitly adopted descriptions of shipped behavior | Current state |
| `documents/architecture/` | Explicitly adopted system boundaries and design | Current state |
| `documents/reference/` | Explicitly adopted APIs, configuration, and schema contracts | Current state |
| `.evoflux/easd/.local/runs/` | Run state, drafts, plans, missions, evidence, reviews, deviations, and convergence data | Operational execution |
| Existing repository docs outside `documents/` | Existing project knowledge until explicitly adopted or linked | Remains authoritative in place |

EASD initialization creates missing skeletons only. It must not implicitly copy, move, or claim existing documentation.

## Roles and authority

| Actor | Responsibilities | Must not do |
| --- | --- | --- |
| User | Accept Spec and Plan revisions, start phases, authorize normative deviations, invoke Converge | Delegate product authority implicitly to agent confidence |
| Spec author | Ground Intent in repository evidence and draft testable criteria | Implement product changes or approve the draft |
| Planner | Decompose an accepted Spec into bounded missions | Redefine accepted behavior |
| Implementer | Change only assigned scope and provide exact verification results | Broaden scope or weaken the Spec silently |
| Reviewer | Independently inspect the integrated revision and submit cited verdicts | Modify product files during independent review |
| Verifier | Evaluate the final evidence matrix and recommend a convergence outcome | Fabricate evidence or declare convergence |
| Convergence service | Compute whether persisted gates are satisfied | Infer completion from prose or confidence |

## Minimal working example

Suppose a user requests: "Reject duplicate project names."

### Intent

- **Problem:** users can create projects with identical names and cannot distinguish them in selection lists.
- **Outcome:** duplicate names are rejected consistently without changing existing projects.

### Spec excerpt

- **Goal:** enforce name uniqueness at project creation.
- **Non-goal:** rename existing duplicates.
- **AC-1:** creating a project with a name already used in the same uniqueness scope returns the documented conflict response and creates no additional project.
- **AC-2:** creating a project with a new name continues to succeed.
- **Evidence policy:** machine evidence required for both criteria; review evidence required if persistence or API compatibility makes the change cross-layer.

### Plan excerpt

If the change spans API validation and persistence, use `planned`:

1. persistence mission: define and enforce the uniqueness invariant;
2. API mission: preserve the documented error contract;
3. verification mission: run focused persistence and API regressions against the integrated revision.

### Completion

The Run is not done when the implementation missions report success. It is ready for convergence only after the accepted commands pass, the integrated review covers the relevant criteria, documentation obligations are reconciled, and no blocking deviation remains.

## Author checklist

Before submitting a Spec draft:

- [ ] The problem and outcome are observable.
- [ ] Goals and non-goals bound the change.
- [ ] Source references and impact targets are repository-qualified.
- [ ] Product, architecture, security, compatibility, and operational constraints are explicit where applicable.
- [ ] The risk tier and `direct` or `planned` recommendation match the actual boundaries.
- [ ] Every critical journey has testable acceptance criteria, including relevant error and recovery behavior.
- [ ] Every criterion has a concrete evidence policy.
- [ ] Verification commands are canonical argv-style commands without `&&`, pipes, redirection, or inline scripts.
- [ ] The draft contains no placeholders, contradictions, silent scope expansion, or unsupported claims.

## Further reading

- [EASD Core Rules](../../.evoflux/easd/RULES.md)
- [Evo Agent Specs knowledge base](../README.md)
- [Specifications catalogue](../specs/README.md)
- [EASD configuration](../../.evoflux/easd/config.json)
