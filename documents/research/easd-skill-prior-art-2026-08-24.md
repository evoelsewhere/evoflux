# EASD repository skill prior-art review

Date: 2026-08-24
Status: implementation input, not a market-ranking claim

## Question

Which public SDD/agent-development skills and command workflows contain useful
operating invariants for a repository-scoped EASD skill bundle, and which parts
must remain distinct because EvoFlux gives users specification authority and
computes Done from persisted evidence?

## Sources reviewed

The review used source snapshots rather than product landing-page summaries.

| Project | Snapshot | Material read |
|---|---|---|
| [OpenSpec](https://github.com/Fission-AI/OpenSpec/tree/f1b521dffac38ed6638689cd28b0c204b1eef0f1) | `f1b521d`, 2026-08-21 | all 12 generated Skills: explore, new/continue/fast-forward/propose/update, apply, verify, sync, archive/bulk-archive, and onboard |
| [GitHub Spec Kit](https://github.com/github/spec-kit/tree/27f50f7e6b618ea14d74dd4037f9e7c60218b16c) | `27f50f7`, 2026-08-21 | `specify`, `clarify`, `plan`, `tasks`, `analyze`, `implement`, and `converge` command templates |
| [Superpowers](https://github.com/obra/superpowers/tree/b36e0829c6d0140e93cfef2ca599b1b07d4a7797) | `b36e082`, 2026-08-12 | `brainstorming`, `writing-plans`, `test-driven-development`, `subagent-driven-development`, review, and verification-before-completion skills |
| [cc-sdd](https://github.com/gotalab/cc-sdd/tree/29aee950f4addc36f9aeecb9881c46540e71ecc9) | `29aee95`, 2026-04-27 | Codex Skills for requirements, design, tasks, autonomous implementation, task review, integration validation, and completion verification |
| [BMad Method](https://github.com/bmad-code-org/BMAD-METHOD/tree/1479a58b2d604382541a184cd59105a580f4e48a) | `1479a58`, 2026-08-23 | PRD, architecture spine, epics/stories, readiness, build, code-review, and evidence-based retrospective Skills |
| [Agent OS](https://github.com/buildermethods/agent-os/tree/cae8e664fb59a01869718c3151e0f45b7a06a2fb) | `cae8e66`, 2026-05-05 | product planning, spec shaping, codebase-standard discovery/indexing/injection commands |
| [Metaswarm](https://github.com/dsifry/metaswarm/tree/33d39f776f7fe29098dcf048955756a237e8cb40) | `33d39f7`, 2026-06-19 | design/plan review gates, orchestrated execution, adversarial review, recovery state, and handoff Skills |
| [Socratic SDD](https://github.com/genkovich/sdd/tree/44c517ef472e0f2eb9c12360d572de6321ac6932) | `44c517e`, 2026-08-19 | size classification, specify/clarify/design/tasks/implement/review Skills and clean-context critic contracts |

These projects are representative public prior art, not an exhaustive market
survey. Their names, prompts, and lifecycle semantics remain their own; EASD
adopts only general engineering invariants compatible with EvoFlux contracts.

## Findings

### 1. Phase-specific discovery beats one universal skill

OpenSpec separates exploration, proposal, apply, and verification. Superpowers
also uses narrow skills whose descriptions select one activity. This supports a
small EASD bundle whose metadata is cheap to discover and whose full body loads
only for the current phase.

EASD response: keep five phase skills rather than one long router:

- `easd-specify`: Discover + Specify + draft review;
- `easd-plan`: Compile + Allocate;
- `easd-implement`: Execute;
- `easd-review`: independent clean-context Challenge;
- `easd-verify`: evidence/integration gate + convergence preparation.

### 2. Specification and implementation need an explicit authority boundary

OpenSpec's proposal skill stops after planning artifacts. Superpowers requires
human approval before implementation. Spec Kit makes clarification and
spec-quality checks precede technical planning.

EASD strengthens this with product state: a skill cannot approve a revision.
Only the user-driven accept endpoint establishes the normative hash, and the
runtime blocks mutation until the accepted run becomes active.

OpenSpec also consistently re-resolves change status, artifact paths, and
instructions before acting instead of trusting conversation memory. EASD Skills
therefore start with a persisted-state/hash gate and invalidate plans, reviews,
or verdicts when the durable revision/snapshot changes.

### 3. Clarification should be impact-driven, not exhaustive

Spec Kit scans scope, roles, state/data, failure paths, security/privacy,
observability, integration, concurrency, compatibility, terminology, and
completion signals. It prioritizes questions by impact and uncertainty rather
than asking about every missing detail. OpenSpec likewise pauses for ambiguity
that changes externally observable behavior, scope, compatibility, or ACs.

EASD response: `easd-specify` performs a bounded ambiguity scan and asks before
selecting behavior when the choice can change product outcomes. Minor inferred
details remain explicit assumptions with source/confidence rather than hidden
facts.

### 4. Plans need traceability, implementability, and independently reviewable units

Spec Kit maps stories, contracts, models, dependencies, file paths, and
independent test criteria into ordered tasks. Superpowers emphasizes exact
interfaces between tasks and task boundaries that carry their own test/review
cycle. OpenSpec re-reads dependency artifacts and treats schema state as the
source of readiness.

EASD response: the plan must expose
`AC → owner/mission → repository/path → evidence → docs`, identify interface
producers/consumers, name overlap/integration ownership, and reject uncovered
required ACs before mutation. A readiness pass also asks whether a specialist
could execute every slice without inventing product behavior, setup, interface
ownership, or verification; a real gap returns to specification/design.

### 5. Implementation progress is not proof of completion

OpenSpec Apply marks work only after a task is actually complete and stops on a
design/scope problem. Superpowers TDD requires observing the failing behavior
before the fix, while verification-before-completion requires fresh command
output before a pass claim. Spec Kit adds checklist gates and checks work back
against the original spec.

EASD response: `easd-implement` uses a regression-first cycle for observable
behavior when practical, records exact verification outcomes, and never turns a
checkbox, handoff, or agent confidence into trusted evidence. The accepted Proof
policy—not a universal TDD slogan—decides the required evidence.

### 6. Independent review and final verification are different gates

OpenSpec Verify separates those three dimensions. Spec Kit Analyze builds
requirement-to-task coverage and flags inconsistency before implementation;
its Converge command appends remaining work rather than silently rewriting past
tasks. cc-sdd has a task-local adversarial reviewer plus a separate
cross-task/integration validator and completion-claim verifier. BMad and
Socratic SDD likewise use clean-context whole-change review, while Metaswarm
separates independent validation, adversarial review, and final cross-unit
review. Superpowers requires fresh evidence before completion claims.

EASD response: add `easd-review` for read-only, cited AC/boundary findings and
keep `easd-verify` for the final integration/evidence gate. Verification checks:

- completeness: every required AC, mission, command, doc, and deviation gate;
- correctness: real behavior and negative paths against the accepted hash;
- coherence: integrated cross-layer contracts, architecture, and current docs.

Only the convergence service can persist Done.

### 7. Ceremony should scale, but gates must stay explicit

Socratic SDD routes work by change size; BMad scales document depth and reviewer
lenses by stakes; cc-sdd and Metaswarm avoid multi-agent review for truly small
work. Agent OS keeps shaping lightweight and selects only relevant repository
standards rather than loading every rule.

EASD response: risk tier and evidence policy—not prompt length or agent count—
control ceremony. Skills may merge or skip unnecessary exploration, but user
spec approval, accepted-hash scope, truthful evidence provenance, and required
independent review remain explicit gates.

### 8. Post-run learning needs product evidence access, not another prompt

BMad retrospectives and Metaswarm recovery/knowledge records show the value of
source-backed learning after delivery. They inspect diffs, commits, story/run
state, verification gaps, and observed behavior; unsupported process stories are
dropped.

EASD response: do not ship an `easd-learn` Skill yet. EvoFlux first needs a
bounded read-only run-report context/tool exposing convergence, rework,
deviations, cost, and final artifact identity. Until then, a Learn Skill would
encourage narrative conclusions without authoritative run evidence.

## Deliberately not adopted

| Prior-art pattern | Reason EASD does not adopt it as a standard skill rule |
|---|---|
| Agent makes product rulings and continues through ambiguity | EASD requires user clarification when the choice can alter product behavior or accepted intent. |
| Mandatory subagent/reviewer fan-out per task | ADD delegates only when bounded independent work or required independence improves correctness or latency; simple work stays with the lead. |
| Mandatory commit after every micro-step | Commit authority and history policy belong to the user/repository workflow, not a project Skill. |
| Universal test-first for generated/config/docs changes | EASD applies regression-first work in proportion to observable behavior and the accepted evidence policy. |
| Task checkbox or artifact presence means Done | EASD requires accepted-hash evidence and deterministic convergence gates. |
| Heuristic source search alone proves requirement coverage | Search is discovery evidence; passing evidence must satisfy the criterion's persisted policy. |
| Skill-specific permission or repository widening | Existing workspace authorization, sandbox, trust, and tool policy remain authoritative. |

## Resulting bundle contract

The standard five-Skill bundle is repository-scoped under `.evoflux/skills`, Coding-only,
and editable by the repository owner. Setup installs or upgrades missing files
without replacing an existing valid edited Skill. Each Skill is procedural and
must fail visibly when EASD state or tools reject an operation; none may bypass
the lifecycle with shell or direct API calls.

The bundle intentionally has no scripts, MCP dependencies, network operations,
or built-in registration. This keeps activation local to repositories that have
explicitly initialized EASD and leaves every security/state mutation at the
existing EvoFlux service boundary.

## Information-architecture extension — 2026-08-25

The initial EASD store only standardized `templates/` and `runs/`. A second
audit reviewed how established spec-first systems separate living contracts,
active changes, reusable project knowledge, and historical evidence.

### Additional source evidence

| Source | Snapshot | Observed structure | EASD implication |
|---|---|---|---|
| [OpenSpec concepts](https://github.com/Fission-AI/OpenSpec/blob/f1b521dffac38ed6638689cd28b0c204b1eef0f1/docs/concepts.md) | `f1b521d`, 2026-08-21 | `openspec/specs/<domain>/spec.md` is current behavior; `openspec/changes/<change>/` contains proposal, design, tasks and delta specs; completed changes move under `changes/archive/` | Separate living specifications from change/run evidence. Do not use an execution folder as the only discoverable spec catalogue. |
| [Spec Kit plan template](https://github.com/github/spec-kit/blob/27f50f7e6b618ea14d74dd4037f9e7c60218b16c/templates/plan-template.md) | `27f50f7`, 2026-08-21 | Each feature-local spec directory can contain plan, research, data model, quickstart, contracts and tasks | Keep change-specific planning together, but route stable API/config contracts into a living reference section when the change ships. |
| [Agent OS product planning](https://github.com/buildermethods/agent-os/blob/cae8e664fb59a01869718c3151e0f45b7a06a2fb/commands/agent-os/plan-product.md) | `cae8e66`, 2026-05-05 | `agent-os/product/` holds mission, roadmap and tech stack; standards are separately indexed | Preserve a small set of stable project-level knowledge sections instead of loading every historical run. |
| [Agent OS spec shaping](https://github.com/buildermethods/agent-os/blob/cae8e664fb59a01869718c3151e0f45b7a06a2fb/commands/agent-os/shape-spec.md) | `cae8e66`, 2026-05-05 | A timestamped spec folder groups plan, shape, standards, references and visuals | EASD Runs already provide the self-contained change folder; avoid adding parallel top-level `changes/`, `tasks/` or `archive/` trees. |

### Taxonomy decision

`<data_directory>` is the repository-local EASD knowledge base. Its stable
sections are available without forcing a migration of documentation that the
repository already owns elsewhere:

| Section | Authority and retention |
|---|---|
| `specs/` | Accepted, behavior-first normative specifications, indexed independently from Runs. |
| `features/` | Current shipped product behavior and ownership; reconciled at Converge. |
| `architecture/` | Current system/trust/storage/concurrency boundaries; ADR-style decisions live in `architecture/decisions/`. |
| `reference/` | Exact API, configuration, schema, CLI and repository contracts. |
| `guides/` | Task-oriented human/operator workflows that are not normative product behavior. |
| `development/` | Contributor, test, build and release procedures. |
| `runs/` | Active and completed EASD change ledgers: Intent, Plan, missions, evidence, deviations, events and convergence. |
| `records/` | Non-normative analysis, research, historical plans and release evidence. |
| `templates/` | Current shapes used to create each supported artifact. |
| `images/` | Media referenced by knowledge-base Markdown. |

The required initialized core is `specs`, `features`, `architecture`,
`reference`, `runs`, and `templates`. The remaining sections are standardized
and indexed so repositories can add them without inventing new roots, but they
may contain only their README until needed.

### Deliberately rejected folders

- No top-level `changes/`: `runs/` already owns active and completed changes.
- No top-level `plans/`: accepted implementation plans are Run-bound; historical
  methodology/design plans belong in `records/plans/`.
- No top-level `tasks/` or `evidence/`: missions and evidence are meaningful only
  when bound to a Run, Spec hash and repository snapshot.
- No separate `archive/`: terminal Run status plus `records/` preserve history
  without moving paths and breaking references.
- No automatic migration or mirroring of an existing `docs/`, `documents/`, or
  custom documentation tree. Setup creates the EASD skeleton only; existing
  project knowledge remains authoritative until maintainers explicitly adopt or
  link it.

### Publication rule

Draft Spec revisions remain inside their Run while awaiting review. User
acceptance publishes an immutable, hash-identical copy into `specs/` and updates
only that Spec's small current-revision index. The Run-local copy remains the
audit snapshot. This is intentional immutable denormalization, not two mutable
sources of truth: a hash mismatch is a repository conflict.
