# AIM Production-Readiness Audit

| | |
|---|---|
| Date | 2026-07-24 |
| Scope | AIM mode UI/UX, domain state, six workflows, rulebooks, compare engine, collaboration, observability, and tests |
| Baseline | `main` at the time of audit |
| Verdict | Strong vertical POC; **not ready for a real migration engagement** |

## Remediation status — 2026-07-24

The implementation was refactored after this audit. The findings below remain
the historical baseline; current status is:

| Audit blocker | Remediation |
|---|---|
| P0-1 phase is a writable label | Fixed: workflow-owned transition policy, active claims, optimistic revisions, file-backed transition events, evidence refs, schema-v2 tamper checks, explicit legacy reconciliation |
| P0-2 compare false equivalence | Fixed: empty golden fails closed, undecodable/binary data compares byte-exact, golden metadata/provenance/sign-off required, missing canonicalizers fail closed |
| P0-3 partial-wave cutover | Fixed: backend readiness blocks incomplete waves; operational deployment/data/rollback/monitoring checklist and approver required before gate |
| P0-4 no recovery | Improved: execution inputs and retry lineage persist; failed/stopped/completed attempts can retry; terminal/restart paths release claims. Full in-place node resume remains outside workflow v1 |
| P0-5 runs/links are DB-only | Fixed: runs and trace links write metadata into the KB and reindex rebuilds both projections |
| P0-6 rulebook harness stubs | Improved: packs declare lifecycle maturity; Java runners are executable case-command adapters. VB6 remains template and COBOL remains analysis-only by explicit capability policy |
| P0-7 no concurrency authority | Fixed for shared DB deployments: exclusive expiring unit claims, batch selected-unit claims, same-attempt evidence, restart cleanup. Separate local databases still require shared Postgres for realtime cross-machine exclusion |

UI remediation includes Mission Control queues, Project Health, wave progress,
Approval Inbox, backend-derived allowed actions, blocked pipeline execution,
traceable Retry, cutover checklist, explicit legacy reconciliation, rulebook
capability maturity, and a real mobile overlay drawer.

## 1. Executive conclusion

AIM has completed a meaningful vertical POC. It can create/join a project, isolate an AIM roster, index legacy code, render a project board, browse the KB/rulebook, start real workflow executions, answer gates, inspect node logs, run a deterministic directory comparison, and show reports. The implementation is not a mock shell.

However, the current system proves **wiring**, not **migration correctness**. Lifecycle authority is split across prompts, workflow YAML, free-form KB files, and frontend hints. The backend validates phase names but not legal transitions or required evidence. This permits a unit to appear `converted`, `equivalent`, or `cutover` without the artifacts and approvals those states claim.

The production decision is therefore:

- **GO** for internal demos, UX discovery, parser experiments, and one controlled engineering pilot with disposable data.
- **NO-GO** for customer delivery, certification, audit reporting, multi-operator conversion, or cutover decisions.
- Do not start with a visual polish pass. First make state transitions, compare verdicts, claims, approvals, and evidence authoritative; then redesign the UI around those contracts.

## 2. Audit method and evidence

The audit used four evidence sources:

1. Read the owning backend/frontend paths, six builtin workflows, AIM roster, rulebook packs, tests, and the original framework/UX documents.
2. Exercised the live UI on existing Java, COBOL, and Servlet/JSP migration projects at desktop, 768 px, and 390 px viewports without starting mutating workflows.
3. Queried live summaries/units/runs to compare displayed state with recorded evidence.
4. Ran the existing AIM-focused test slice and two discriminating compare checks.

Baseline validation:

```text
150 AIM-related backend/workflow/sandbox tests: PASS
web TypeScript typecheck: PASS
```

Discriminating compare checks:

```text
empty expected/ directory + missing actual directory -> pass, diff_count=0
expected binary 0xFF + actual binary 0xFE       -> pass, diff_count=0
```

These results mean the primary gaps are contract/design gaps, not incidental compile or test failures.

## 3. POC completion map

| Capability | What genuinely works | Production gap | Assessment |
|---|---|---|---|
| AIM mode shell | Separate mode, project sidebar, routes, command palette, shared shell | Mobile sidebar consumes most of a 390 px viewport; main surface is unusable | POC complete |
| Project setup | One-folder detection, create/join, local role mapping, KB scaffold | No preflight for git state, target-base readiness, rulebook completeness, runners, permissions, or stack compatibility | POC complete |
| Source safety | AIM source paths are passed as `read_only_paths`; direct write/edit/patch/rm and shell redirects are tested | Shell protection is explicitly best-effort and does not catch `sed -i`, scripts that write internally, or every git mutation | Guardrail, not a hard boundary |
| Rulebooks | KB-first resolution, manifests, overlays, skills/runners install, read-only viewer | Java/VB6 runners are intentional stubs; COBOL pack is parser-only; no capability/readiness validator | Content framework POC |
| Legacy parsing | Structural COBOL/JCL/VB6 extraction and code-graph integration have tests | No engagement-level recall/precision report or inventory reconciliation | Parser POC |
| Assess | Agent can create inventory stubs, complexity, waves, and a review gate | Completeness and dependency ordering are prompt-judged; no deterministic estate snapshot or stale-unit reconciliation | Pipeline POC |
| Understand | Agent writes unit docs/rules; tool node marks `understood` | No artifact/schema validator, dependency precondition, or SME-confirmation state | Pipeline POC |
| Design | Mapping is written and shown to an approval gate | Design is bundled into convert-unit; mapping existence/content and confirmed-rule citations are not validated | Pipeline POC |
| Convert | Agent writes target code and can run build/tests | Agent-turn completion is treated as success; no required build/test evidence, target revision, claim, or atomic worktree result | Unsafe for delivery |
| Convert wave | Deterministic list of `designed` units; sequential foreach | Phase update is delegated back to prompt; no unit lock, dependency preflight, retry policy, or partial-failure plan | Unsafe for scale |
| Test compare | Pure Python canonicalization and text/JSON/fixed-width directory diff; report generation | False-pass cases, no golden provenance validation, no real runner in pilot packs, no binary/PDF/DB/online compare | Unsafe for certification |
| Cutover | Queries wave units, asks a gate, marks units | Allows partial-wave cutover and has no operational/rollback/deployment readiness contract | Production blocker |
| KB | File tree, markdown/config preview, manual unit reindex | No git status/pull health, schema lint, structured rule/evidence views, or automatic full projection rebuild | Read-only POC |
| Runs/monitor | Workflow node log, pending gate reply, report, Discussion | In-memory execution only; no resume/retry/clone/supersede; run ledgers are split and can duplicate | Debug POC |
| Collaboration | KB files can be shared through git; `assignee` is visible | No atomic claim/lease, revision check, pull/push protocol, conflict handling, or stale projection warning | Not implemented as a system |
| Audit trail | `AimLink`, `AimRun`, reports, session/execution IDs exist | Runs/links are DB-only and cannot be rebuilt from KB despite the documented contract | Incomplete |
| UI tests | Backend routes/services have broad unit coverage | No frontend component/e2e test files; no lifecycle workflow contract suite | Missing |

## 4. Production blockers

### P0-1. Phase is a writable label, not a governed state machine

[`aim_units`](../../app/agent/tools/builtin/aim.py) checks only whether a phase string is in `VALID_PHASES`; it does not check the current phase, expected predecessor, active claim, workflow execution, approval, or required evidence. Existing tests intentionally create a new unit directly at `converted`, so the current behavior is part of the tested contract.

The six workflow files then call `set_phase` after an agent turn completes. An agent turn can complete with prose saying a build or artifact failed; the workflow engine still considers the node successful unless the turn itself raises.

There is also prompt drift:

- [`aim-understand.yaml`](../../app/agent/builtin_aim/workflows/aim-understand.yaml) says the pipeline marks the phase; both [`aim-archaeologist.md`](../../seed/agents/aim/aim-archaeologist.md) and [`aim-legacy-comprehension`](../../app/agent/builtin_skills/aim-legacy-comprehension/SKILL.md) say the agent must mark it.
- [`aim-convert-unit.yaml`](../../app/agent/builtin_aim/workflows/aim-convert-unit.yaml) says architect/converter must not mark phases; their blueprints still instruct them to do so.
- Live history contains an interrupted pre-approval conversion-plan run whose transcript shows the agent setting `designed` before the approval gate.

Required correction: all lifecycle mutations must go through one domain transition service with preconditions, evidence validation, actor/execution identity, optimistic concurrency, and an append-only transition event.

### P0-2. `aim_compare` can certify false equivalence

[`compare_dirs`](../../app/services/aim/compare.py) returns pass when both discovered file sets are empty. `_aim_compare` only checks that `expected/` is a directory, not that it contains a valid, non-empty expected manifest. A missing actual directory is treated as an empty set.

The same compare path decodes every file as text and eventually uses `errors="replace"`. Different invalid bytes can normalize to the same replacement character. The audit reproduced `0xFF` vs `0xFE` as a pass.

Other gaps:

- Golden `meta.yaml` provenance and SME sign-off are never read or validated.
- A missing canonicalizer profile silently becomes an empty profile.
- No binary byte comparator, PDF extraction, DB snapshot schema, case manifest, case coverage calculation, or online replay exists.
- The workflow can reach the certify gate solely from this verdict.

Required correction: fail closed on missing/empty expected data, missing actuals, missing profile, invalid metadata, unsupported media, and runner failure. Use type-specific comparators and include coverage/provenance in the signed verdict.

### P0-3. Cutover does not require wave readiness

[`aim-cutover-check.yaml`](../../app/agent/builtin_aim/workflows/aim-cutover-check.yaml) calculates equivalent and total counts, but the gate is always reachable. Choosing `cutover` iterates only the equivalent subset.

This was verified in the live UI: wave 1 showed `1 of 4 unit(s) ... certified equivalent`, while Run remained enabled. The original roadmap even records `1 of 2` followed by one unit being marked cutover as a successful AIM-4 demo.

Required correction: a deterministic precondition must block the gate unless every in-scope unit is equivalent and the wave has no open blockers. Cutover also needs deployment, data reconciliation, rollback, ownership, monitoring, and go/no-go evidence; a phase flip alone is not cutover.

### P0-4. Workflow executions are not durable or recoverable

[`WorkflowExecution`](../../app/models/workflow.py) is explicitly a best-effort debug log. Live execution state exists only in process memory and is never read to resume. A restart marks active/gated runs failed.

The Run Monitor is useful for diagnosis but offers no resume-from-gate, retry failed node, clone inputs, compensate side effects, or supersede attempt. Long-running migration steps can therefore leave KB/target side effects without a recoverable execution state.

Required correction: either add durable workflow checkpoints or model AIM stage attempts as restartable, idempotent domain jobs whose side effects are committed only after validation. At minimum, persist node inputs/outputs, pending approval, artifact hashes, and attempt lineage.

### P0-5. The declared system of record is not implemented for runs and links

The architecture says KB files are authoritative and `aim_units`, `aim_runs`, and `aim_links` are rebuildable projections. In code:

- [`reindex_project`](../../app/services/aim/reindex.py) rebuilds units only.
- `aim_compare` writes report files but no run `meta.yaml`, then inserts `AimRun` directly.
- `record_run` and `add_link` write only database rows.
- There is no run/link reindexer.

A cloned KB therefore loses run metadata and traceability edges. The audit trail is neither fully git-portable nor fully database-authoritative.

Required correction: choose and enforce one authority. For the current local-first design, persist transition/run/approval/link metadata in append-only KB files and rebuild every projection from them. If the product instead chooses a shared database, revise the architecture and collaboration model explicitly.

### P0-6. Shipped rulebooks do not provide an executable migration harness

The Java 8→21 and VB6→.NET runner files print `TODO` and exit with code 1. The COBOL→Java pack declares itself parser-first and has no conversion mappings, overlays, or runners. Tests verify runner copying, not runner usability or declared entrypoint existence.

Required correction: stop treating all packs as equivalent. Add capability flags and validation (`inventory`, `understand`, `convert`, `compare`, `ui`) and select one production pilot pack. Java 8→21 is the lowest-risk candidate; make its runners and fixture estate real before expanding breadth.

### P0-7. No concurrency authority exists

`assignee` is a free string, not an atomic claim. There is no lease, expected revision, active-attempt uniqueness, unit/wave lock, or target-path ownership check. Two operators can start convert-unit for the same unit or overlapping target files.

KB writes are read-modify-write operations followed by a separate DB update. A crash or concurrent write can leave file and projection state inconsistent. Git synchronization is described operationally but no workflow performs or verifies pull/commit/push.

Required correction: add atomic claims with owner, execution ID, lease expiry, and revision; reject overlapping active attempts; validate repository revisions before and after writes; expose conflicts as blockers rather than silently overwriting state.

## 5. High-priority pipeline gaps

1. **No artifact contracts.** Unit docs, mappings, business rules, target code, tests, and reports are prose/file conventions with no phase-specific validators.
2. **No deterministic dependency gate.** `depends_on` is stored and displayed, but no service checks cycles, missing units, same/later-wave dependencies, or prerequisite phases.
3. **No target-base preflight.** Setup accepts a directory called target; it does not verify build, CI, sample architecture, UI kit, clean git state, or rulebook compatibility.
4. **Project phase is dead state.** Assess sets project phase to `understand`; later workflows do not update it and the UI does not use it.
5. **Two run ledgers drift.** Workflow status and domain verdict are joined heuristically by session ID. `aim_compare` and triage can create separate rows for one report; live UI already displays execution `pass` plus verdict `pass`.
6. **Repair is guidance, not control flow.** Converter has a verbal `~3 rounds` budget; no counter, timeout policy, attempt lineage, or deterministic escalation enforces it. The test-compare graph triages and ends; it does not perform a bounded repair/re-compare loop.
7. **Reindex is incomplete.** Deleted/moved units are deliberately never pruned because deleting their index row would cascade into run history. That protects history but leaves stale units active on the board. Use an explicit tombstone/archive state and path-move reconciliation instead; malformed docs are currently silently skipped and the response reports neither stale nor invalid records.
8. **Success metrics are not captured.** First-pass compile/equivalence, automation rate, coverage, human overrides, SME time, and per-phase duration are proposed in the framework but absent from the domain model.

## 6. UI/UX audit

### 6.1 Information architecture

The current IA is feature-centric: Overview, KB, Rulebook, Pipelines. A migration operator is event-centric and asks:

- What is blocked now?
- What needs my approval?
- Which wave is ready, at risk, or drifting?
- Which units can safely start next?
- Which evidence is missing?
- Which failed/interrupted attempts need recovery?

Those questions cannot be answered from the current four surfaces without manually correlating phase cards, run rows, reports, and KB files.

### 6.2 Verified UX issues

1. **Readiness is decorative.** [`eligibility`](../../web/src/components/AimPipelinesPanel.tsx) renders warning text but is not part of `canRun`. The incomplete cutover case remains runnable.
2. **Unsafe unit actions are always offered.** Unit detail shows Understand, Convert, and Test-compare buttons regardless of phase or evidence.
3. **Kanban optimizes for phase counts, not flow decisions.** Six fixed columns create large empty areas while 31 inventory units become one long list. There are no wave swimlanes, blockers, aging, WIP, owner load, or dependency readiness.
4. **The pipeline screen is an execution console.** The generic workflow picker is useful as an advanced/admin surface, but should not be the primary daily workflow. It exposes graph internals while hiding business readiness.
5. **Run triage is weak.** Rows are dense and truncate key names. Execution outcome and domain verdict can appear as duplicate labels. There is no Needs approval / Failed / Interrupted / Blocked queue.
6. **Recovery actions are absent.** Monitor has logs, gate reply, stop, report, and Discussion, but no retry/resume/clone/supersede.
7. **Empty-project space is underused.** The screen shows four zero metrics and Run assess, but no prerequisite health for source index, target base, rulebook, runners, KB git, or golden setup.
8. **Mobile is broken.** At 390 px the desktop sidebar remains roughly 276 px wide and the main surface collapses to a narrow blank strip. AIM provides no mobile drawer to `AppShell`.
9. **KB is only a file browser.** It lacks structured views for rules, mappings, unresolved ambiguities, coverage, traceability, schema errors, and git freshness.
10. **Rulebook viewer shows declarations, not health.** It can display runner paths even when scripts are stubs; it does not validate capabilities or execute preflight checks.
11. **Frontend regression protection is absent.** No `web/src/**/*.test|spec` or `web/tests` files exist.
12. **Maintainability is concentrated.** `AimPipelinesPanel.tsx` combines trigger form, policy hints, sessions/execution joins, run table, monitor, gate, report, and Discussion in one very large component.

### 6.3 Target AIM experience

The default screen should be **Mission Control**, not a generic kanban or workflow picker:

1. **Project health header**: source index freshness, target build, KB git state, rulebook capability, runner health, active claims.
2. **Work queues**: Needs approval, Blocked, Failed/interrupted, Ready next, Running.
3. **Wave control**: readiness %, burn-up, dependency blockers, WIP, pass rate, estimate vs. actual.
4. **Unit table/board toggle**: compact sortable table for operations; board for flow visualization. Cards/rows show next legal action and missing evidence.
5. **Approval Inbox**: durable approvals with artifact diff, policy checks, approver, decision, and expiry/supersession.
6. **Unit workspace**: Summary, Evidence, Dependencies, Rules/mapping, Attempts, Traceability, and contextual actions.
7. **Run recovery**: Resume, Retry node, Clone with inputs, Supersede, and open resulting artifacts.
8. **Advanced Pipelines**: retain the generic picker as a secondary expert surface for custom workflows.
9. **Responsive shell**: sidebar drawer/overlay on mobile and stable table/detail layouts on tablet.

## 7. Target domain contract

Do not expand the current `AimUnit.phase` setter. Introduce a domain layer with explicit entities:

| Entity | Purpose |
|---|---|
| `AimUnit` | Stable identity and current projection only |
| `AimTransition` | Append-only from/to event with actor, execution, timestamp, reason, evidence hashes, and expected revision |
| `AimStageAttempt` | One assess/understand/design/convert/compare/cutover attempt with inputs, status, retry lineage, revisions, and failure kind |
| `AimEvidence` | Typed artifact: unit doc, rule set, mapping, build, test, golden manifest, compare report, approval, deployment check |
| `AimApproval` | Durable request/decision bound to artifact hashes; pending/approved/rejected/superseded |
| `AimClaim` | Atomic unit/wave ownership with lease and workflow execution ID |
| `AimWave` | Explicit scope, dependency closure, readiness, release/cutover status, and operational checklist |
| `AimTraceLink` | File-backed typed edge between rules, source, mapping, target revision, test cases, reports, and approvals |

Minimum transition policy:

| Transition | Required evidence/preconditions |
|---|---|
| inventory → understood | Non-stub unit doc, dependency docs ready or explicit blocker/waiver, extraction result, rule files schema-valid |
| understood → designed | Mapping schema-valid, target conventions present, required rules confirmed or explicitly waived, architect approval |
| designed → converted | Exclusive claim, approved mapping hash unchanged, target revision recorded, build/test commands passed, target paths recorded |
| converted → equivalent | Valid non-empty golden manifest, trusted provenance/sign-off, runner success, supported comparator, deterministic pass, human certification |
| equivalent → cutover | Every wave unit equivalent, no open blocker/claim, deployment/data/rollback/monitoring checklist complete, go/no-go approval |

The frontend asks the backend for `allowed_actions` and `readiness`; it must never reimplement these rules in TypeScript.

## 8. Pipeline redesign

### Assess

`snapshot source revisions → deterministic inventory/extractor report → reconcile added/changed/removed units → agent enrichment/complexity → dependency validation → wave proposal → approval → commit evidence`

### Understand

`claim unit → dependency preflight → agent comprehension → validate unit/rule/data-dictionary artifacts → SME review queue → transition → release claim`

### Design

Replace the current bundled `aim-convert-unit` plan/convert graph with a separate design workflow and a conversion workflow:

`claim → target-base/rule readiness → generate mapping/ADR → validate citations and UI pattern → architect approval → transition designed`

### Convert

`claim → verify approved mapping hash → isolated worktree → implement → deterministic build/test → collect target revision/paths → validate evidence → transition converted → release claim`

Do not let a final agent message decide build success.

### Test compare

`validate golden manifest/coverage/provenance → run legacy/target adapters → validate outputs → typed compare → triage → bounded repair attempt → re-run → certification approval → transition equivalent`

Every attempt has a hard budget and a terminal failure category (`runner`, `coverage`, `unsupported_format`, `target_defect`, `golden_suspect`, `policy`).

### Cutover

`resolve explicit wave scope → hard readiness preflight → deployment/data/rollback/monitor checks → go/no-go approval → execute/record external cutover step → verify → transition entire wave atomically`

No partial subset should be silently marked cutover under a wave-level command.

## 9. Refactor roadmap

### Phase 0 — Safety freeze (3–5 engineering days)

1. Add failing regression tests for empty golden, missing actuals, differing binary, missing profile, illegal phase skip, incomplete wave cutover, and duplicate active unit attempt.
2. Make compare fail closed for unsupported/empty/missing inputs.
3. Block cutover before the gate when readiness is incomplete; disable the UI action from backend readiness.
4. Align all AIM blueprints and workflow prompts so agents never own phase transitions.
5. Mark builtin rulebook capabilities honestly and surface runner stubs as not ready.

Exit criterion: current known false certification/cutover paths are impossible.

### Phase 1 — Domain authority (1–2 weeks)

1. Implement transition policy/evidence validation service and route `aim_units` through it.
2. Add attempt, transition, approval, claim, and evidence schemas.
3. Decide KB-vs-DB authority; make runs/links/approvals rebuildable or revise the local-first contract.
4. Add optimistic revisions and exclusive active claims.
5. Merge workflow/domain run identity instead of joining heuristically by session.

Exit criterion: every displayed state has queryable evidence and an append-only reason.

### Phase 2 — Restartable pipelines (1–2 weeks)

1. Split design and convert.
2. Add deterministic validator/preflight nodes and structured failure kinds.
3. Add bounded retry/repair and retry lineage.
4. Add resume/clone/supersede semantics or durable AIM stage jobs.
5. Add dependency closure and wave readiness services.

Exit criterion: kill/restart at every node and recover without lying about state or duplicating side effects.

### Phase 3 — Mission Control UX (1–2 weeks)

1. Build project health, approval inbox, exception queues, and wave readiness from backend contracts.
2. Replace unconditional unit actions with `allowed_actions`.
3. Make contextual unit/wave actions primary; move generic workflow picker to Advanced.
4. Add run recovery controls and structured evidence/report views.
5. Implement mobile drawer/responsive layouts and frontend component/e2e coverage.

Exit criterion: an operator can run one wave, resolve gates/failures, and explain every status without opening chat or raw files.

### Phase 4 — One real pilot pack (2–4 weeks)

1. Choose one stack pair; recommended first target is Java 8→21, not COBOL/VB6.
2. Ship executable legacy/target adapters, a representative fixture estate, golden manifests, and supported comparator types.
3. Run at least 20 units with intentional failures, restart tests, concurrent operators, and a staged cutover rehearsal.
4. Measure first-pass build/equivalence, human override rate, elapsed/cost per phase, and evidence completeness.

Exit criterion: evidence from the pilot, not a wiring demo, supports the production claim.

## 10. Required test strategy

Add a workflow contract suite that executes the real six YAML definitions with deterministic fake agents/tools and asserts artifacts plus transitions, not only workflow discovery.

Required layers:

- Domain property tests: no illegal transition sequence; stale revisions and duplicate claims rejected.
- Compare conformance fixtures: empty, missing, binary, encoding, fixed-width, JSON/CSV, large files, masks/tolerance, unsupported formats.
- Workflow restart matrix: stop/restart before and after every side-effecting node/gate.
- Rulebook contract tests: manifest schema, declared files exist, executable adapter preflight, capability flags, canonicalizer validation.
- API/UI tests: readiness and allowed actions agree; incomplete cutover cannot be triggered.
- Playwright: setup, mission control, approval, failed-run recovery, report evidence, 1440/768/390 px screenshots.
- Multi-operator tests: claim collision, stale KB revision, target-path overlap, reindex convergence.

## 11. Production Definition of Done

AIM can enter real use only when all statements below are demonstrably true:

- A unit cannot skip or regress phase without an explicit authorized override event.
- Every phase transition has validated evidence and artifact hashes.
- Compare cannot pass missing, empty, unsupported, or runner-failed cases.
- Golden provenance and coverage are visible and enforced before certification.
- A restart at any gate/node has a documented resume/retry outcome.
- Two operators cannot mutate the same unit or overlapping target scope concurrently.
- A fresh clone/reindex reconstructs units, runs, links, approvals, and current projections.
- A wave cannot cut over partially through a wave-level action.
- UI actions come from backend readiness/policy and impossible actions are disabled with reasons.
- Operators can see approvals, blockers, failures, aging, ownership, and next legal work from Mission Control.
- One rulebook has passed an end-to-end representative pilot with real runners and measured quality.
- Desktop, tablet, and mobile critical journeys have automated visual/interaction coverage.

## 12. Recommended first implementation slice

The first coding slice should be narrow and safety-focused:

1. Add compare regression tests and fail-closed behavior.
2. Add `AimReadinessService` for unit/wave checks, starting with cutover.
3. Add legal transition enforcement to `aim_units` with an explicit override path reserved for repair/admin use.
4. Update the six workflows and six affected blueprints to remove phase ownership conflicts.
5. Expose `readiness`, `blockers`, and `allowed_actions` in the unit/wave API; wire the current UI to disable unsafe actions.

This creates the first trustworthy contract on which the larger pipeline and UX refactors can build.