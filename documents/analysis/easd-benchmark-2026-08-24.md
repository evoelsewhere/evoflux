# EASD benchmark report — 2026-08-24

Status: completed and converged
Methodology: **EASD — Evo Agent Specification-Driven Development**
Protocol: [EASD benchmark protocol](../plans/easd-benchmark-protocol.md)

## Result

The first EvoFlux EASD benchmark converged successfully after two independent
challenge failures and explicit rework.

| Gate | Final result |
|---|---|
| Benchmark acceptance criteria | 8 passed, 0 waived |
| EASD missions | 8 completed, 0 cancelled |
| Public tests | 30 passed |
| Hidden oracle | 4 checks passed |
| Converged benchmark revision | `0754feddd2a8cc979a43bbc963726d02215286cd` |
| EASD branding revision | `49dd4cc3869eab904162ab518dd20d3737f50c7c` |
| EASD repository setup revision | `6a7eda03ad5f6b302c24dd81530b969d5ae9ed88` |
| Blocking deviations | 0 |
| Convergence API attempts | 1 successful, 0 rejected |
| EASD run elapsed time | 62 minutes 58 seconds |

This is evidence that the implemented EASD contracts can govern one real
Coding Project. It is not evidence that EASD is universally more productive
than another method, and it does not establish a market-wide “first” claim.
That claim still requires a release-time competitive audit with dated sources.

## Follow-up real UI agent run

The README's long recording is a second persisted run on the same Coding
Project, captured from run creation through linked UI chat, implementation,
worktree integration, independent review, evidence admission and server-owned
Convergence. It is not a staged/manual-only lifecycle.

| Record | Result |
|---|---|
| Run | `06a8b521-b5e9-7b28-8000-8f4777060715` — Add deterministic schedule summary mode |
| Linked Coding session | `06a8b514-37b9-7a8c-8000-65ed316683b3` |
| Accepted spec hash | `e8344164d4d75a8e7a674b8f87a434ca57fe3e8a827aa9916f350a66cfa4dd57` |
| Risk | Standard |
| Acceptance | 4 passed, 0 waived |
| Missions | `coder#1` and `debate#1`, both completed |
| Evidence | 13 records: 4 machine, 5 review, 4 manual, 0 waiver |
| Public verification | 33 tests passed; `compileall` and diff check passed |
| Converged revision | `a43397b1450453e4c3754b2823cc26aa861efb4a` |
| Run elapsed | 51 minutes 37 seconds, including real provider/tool timeout and coordination recovery |
| README recording | 20 minutes 9 seconds, H.264 1280×720 |

The run exposed the missing **Run in chat/Open active chat** handoff and a stale
list-cache bug. The final UI flow activates an accepted run, targets its linked
session, resumes without duplicating work in a busy chat, and refreshes every
run list/detail cache after lifecycle/evidence mutations.

## Reproduction identity

### EvoFlux

- repository base revision: `77cfd8711db2e4426b3fad9c580039214824535b`;
- implementation state: uncommitted EASD working tree on that base revision;
- schema head: `00000056`;
- server version: `0.0.8`;
- benchmark server: local loopback only;
- platform: macOS 15.7.5, x86_64;
- Python runtime: 3.12.13 through the EvoFlux virtual environment;
- Git: 2.39.5; uv: 0.11.27; pytest: 9.0.3.

Because the EvoFlux feature change was not committed as part of this task, the
base revision alone does not reproduce the product implementation. The source,
tests, migrations, docs, and UI changes in the current working tree are the
implementation under test. The separate benchmark repository is clean and
fully revision-addressable.

### Coding Project and EASD run

| Record | ID |
|---|---|
| Coding Project | `06a8b242-37a3-7c74-8000-5049863ab812` |
| Project name after rebrand | `EASD Benchmark` |
| Coding workspace | `/Users/khuonghung/Workspace/morphai-lab/evoflux-trace-benchmark` |
| Coding session | `06a8b245-8b0b-785a-8000-4cb810dae581` |
| EASD run | `06a8b252-1475-7caf-8000-ce9b8f51a20d` |
| Accepted spec revision | `06a8b252-1497-7be9-8000-0e62c95886e1` |
| Accepted spec hash | `9b6e1dfe50f672d9936061e34c9a5834e71cee8ddbc1e6c95fb69a691c0b1deb` |

The workspace path is a historical compatibility identifier from before the
EASD rename. New benchmark repositories use `evoflux-easd-benchmark`.

The run was created at `2026-08-23T16:51:45.278898Z` and converged at
`2026-08-23T17:54:43.524399Z` (`2026-08-24` in Asia/Ho_Chi_Minh).

### Benchmark repository

- seed revision: `bf4a1a9f720887d152c869162ac0a83fbab28229`;
- first integrated revision: `94a69adca4ec01cff61a99baeee9e44d9aac1352`;
- recursion repair integration: `6eb057186d21eb854159e25a0ab0ef58553fafb1`;
- CLI contract repair: `fad55297cd2d488b96cd961708b17af5b6e24d57`;
- converged functional revision: `0754feddd2a8cc979a43bbc963726d02215286cd`;
- post-convergence EASD-only branding revision:
  `49dd4cc3869eab904162ab518dd20d3737f50c7c`;
- repository-local EASD setup revision:
  `6a7eda03ad5f6b302c24dd81530b969d5ae9ed88`;
- follow-up real UI agent-run revision:
  `a43397b1450453e4c3754b2823cc26aa861efb4a`;
- final tree: clean `main`.

The seed deliberately contained `NotImplementedError` paths. Its public
baseline was 15 failed tests. The EASD-branded final tree has 30 passing public
tests and a passing external hidden oracle. The branding commit changed only
AGENTS, README, package description, and the specification's method name; it did
not rewrite the persisted Convergence Report bound to `0754fed…`.

## Model allocation

The configured Codex OAuth provider and GPT-5.6 family were used throughout.

| Runtime role | Actual model | Reasoning | Use |
|---|---|---|---|
| Lead / convergence owner | `codex:gpt-5.6-sol` | high | mission graph, review routing, merge/finalization |
| Builder `coder#1` | `codex:gpt-5.6-terra` | medium | parser/schema mission and retry |
| Builder `coder#2` | `codex:gpt-5.6-terra` | medium | graph, integration, recursion repair, CLI repair |
| Independent verifier `debate#1` | `codex:gpt-5.6-sol` | high | adversarial integrated reviews |

Luna was configured as the preferred narrow explorer, but no explorer Mission
was needed or instantiated. Model selection was treated as allocation policy,
not as evidence.

## Mission graph and ownership

The persisted graph has maximum dependency depth four and an initial parallel
width of two. Five missions used isolated worktrees; three review missions used
the shared integrated tree.

| Mission | Owner | ACs | Isolation | Attempts | Outcome |
|---|---|---|---|---:|---|
| Parser/schema `06a8b25e-ad17…` | `coder#1` | 1, 6 | worktree | 2 | completed after verification-path retry |
| Graph/scheduler `06a8b25e-c2d8…` | `coder#2` | 2, 3, 6 | worktree | 2 | completed after verification-path retry |
| Results/CLI integration `06a8b2ad-843f…` | `coder#2` | 1–7 | worktree | 1 | completed; later hidden audit found weakened test |
| Initial independent review `06a8b2cc-3bf4…` | `debate#1` | 1–8 | shared | 1 | completed with blocking recursion finding |
| Recursion repair `06a8b2e5-8c2a…` | `coder#2` | 2, 3, 5, 6, 8 | worktree | 1 | completed |
| Recursion re-review `06a8b2f4-84dd…` | `debate#1` | 1–8 | shared | 1 | completed |
| CLI contract repair `06a8b30f-e4d9…` | `coder#2` | 5, 6, 8 | worktree | 1 | completed |
| Final independent review `06a8b31f-3262…` | `debate#1` | 5, 6, 8 | shared | 1 | completed |

There were eight durable missions and ten mission attempts. The two formal
rejections were retained on the first parser and graph/scheduler missions rather
than replaced by clean-history tasks.

## Challenge and rework chronology

1. The seed baseline failed all 15 public tests as intended.
2. Parser and graph/scheduler ran concurrently in separate worktrees.
3. Both first handoffs failed runtime completion because the console-script
   `pytest` did not make the worktree source root importable. The lead rejected
   both rather than accepting prose or local ad-hoc path mutations.
4. A repository-level `pythonpath = ["."]` contract was integrated. One parser
   merge conflict in `pyproject.toml` was resolved by the integration owner.
5. Completion verification then reused a stale artifact cache after Git
   integration. A comment-only config refresh exposed that cache bug and let the
   benchmark proceed.
6. Results/CLI integration produced revision `94a69ad…`; 25 public tests passed.
7. The first independent Sol review generated a 1,101-node DAG and cycle. The
   recursive graph validator raised `RecursionError`, blocking AC-2/3/5/8.
8. A Terra repair replaced recursive DFS with deterministic iterative traversal
   and added deep regressions. Public tests increased to 29 and the Sol re-review
   passed at `6eb0571…`.
9. The external hidden oracle then failed `6eb0571…`. The integration Mission
   had removed the seed test's `job_count` assertion and the CLI omitted that
   field. This escaped the public suite and both prior independent reviews.
10. EASD retained the failed review evidence for AC-5/6/8. A new Terra Mission
    restored `job_count`, restored and strengthened file/stdin/zero-job tests,
    and updated the README. A new Sol reviewer compared seed to final tests and
    verified exact bytes at `0754fed…`.
11. The hidden oracle passed all four checks at the final revision. Only then
    was passing external review evidence recorded and convergence requested.

The two pre-convergence revision rejections were therefore useful outputs, not
failed demonstrations: each prevented a false Done state and produced a bounded
repair Mission.

## Verification outcomes

### Benchmark project

| Check | Before rework | Final |
|---|---|---|
| Public tests | 15 failed at seed; 29 passed at `6eb0571…` | 30 passed |
| Compile | not applicable at incomplete seed | `python -m compileall -q tracebench`, exit 0 |
| Deep DAG/cycle probes | `RecursionError` at `94a69ad…` | four focused deep regressions passed |
| Hidden oracle | failed at `6eb0571…` | 4 checks passed |
| Git state | integration/worktree state during execution | clean `main` at `0754fed…` |

The hidden oracle verified deterministic self/multi-node cycle diagnostics,
input-independent waves, transitive failed-dependency blocking, and byte-exact
compact CLI output:

```json
{"job_count":1,"order":["a"],"waves":[["a"]]}
```

The independent reviewer also measured the scheduler's one-job-wave scaling at
approximately 0.112s/0.516s/3.712s/17.664s for 1k/2k/5k/10k chains. The
quadratic shape was not a benchmark AC because no size or latency SLO was
accepted; it is a valid future workload finding.

### EvoFlux product implementation

| Gate | Result |
|---|---|
| Full backend pytest | passed, exit 0 |
| Ruff check | passed |
| Ruff format, changed/new Python files | passed |
| Targeted `ty` on EASD/runtime paths | passed |
| Alembic/schema upgrade suite | 12 passed |
| Frontend lint/typecheck/build | passed; one pre-existing SchedulerPanel hooks warning and normal chunk warning |
| EASD/workbench frontend tests | 6 passed |
| Localized Help/i18n focused tests | 27 passed |
| Tauri `cargo check` | passed |
| Markdown link audit | passed before this report; repeated after documentation update |

The full repository `ruff format --check` still reports 74 pre-existing files,
and full `ty check app/` still reports 21 pre-existing diagnostics outside EASD.
The full frontend test run passed 378 tests but two unrelated settings/plugin
tests timed out under contention; their focused rerun passed. These are not
reported as clean full-suite gates.

## Evidence and convergence

The final ledger contains:

- 47 evidence records: 25 machine, 19 manual, and 3 review;
- 42 passing and 5 failing records;
- 8 passed ACs, 0 waived ACs;
- 0 persisted spec deviations;
- 8 completed missions and 0 cancelled missions.

The five failing records remain intentionally visible. Rework did not require a
normative spec change, so defects and process failures were handled as failed
evidence/retry history rather than manufactured specification deviations.

The benchmark started against a long-running development process before the
final evidence-admission fix was loaded. That process admitted isolated
worktree evidence at review time and retained duplicates across attempts. The
source now admits isolated evidence only after lead merge; the server was
restarted with the corrected implementation before final review evidence and
convergence. The inflated 47-record count is disclosed rather than normalized
away.

The persisted Convergence Report records:

```json
{
  "git_revision": "0754feddd2a8cc979a43bbc963726d02215286cd",
  "criteria": {"total": 8, "passed": 8, "waived": 0},
  "missions": {"total": 8, "completed": 8, "cancelled": 0}
}
```

The service was called once and converged once. There was no rejected service
attempt because independent and hidden challenges ran before the convergence
gate, as the protocol requires.

## Usage

Usage was reconstructed from persisted assistant messages. For each agent run,
the last cumulative `turn_usage` sample before its call counter reset was
counted once. Cached tokens are a subset of input tokens, not an additional
amount.

| Agent | Model | Model runs | Input tokens | Output tokens | Cached input | Model calls |
|---|---|---:|---:|---:|---:|---:|
| Lead `evoflux` | GPT-5.6 Sol | 18 | 8,762,155 | 25,952 | 1,213,952 | 208 |
| `coder#1` | GPT-5.6 Terra | 15 | 1,551,541 | 15,371 | 560,128 | 80 |
| `coder#2` | GPT-5.6 Terra | 6 | 1,948,531 | 27,560 | 802,816 | 108 |
| `debate#1` | GPT-5.6 Sol | 12 | 1,566,851 | 33,300 | 194,560 | 77 |
| **Total** |  | **51** | **13,829,078** | **102,183** | **2,771,456** | **473** |

Total model tokens were 13,931,261 input plus output, or approximately 1,741,408
tokens per passed AC. This is not an efficiency success. Repeated full-context
lead turns and coordination loops dominated usage and are the strongest
negative result of the run.

## Human/operator interventions

Six substantive interventions were required:

1. a comment-only refresh to expose and work around stale verification cache;
2. interrupt/resume of the first idle-agent coordination loop;
3. interrupt/resume of the second idle-agent coordination loop;
4. interrupt/resume of a third repeated team-status loop before finalization;
5. external hidden-oracle rejection and the resulting corrective Mission
   directive;
6. explicit correction of stale README wording from post-convergence audit to
   pre-convergence audit.

Operational cleanup also removed one generated `.DS_Store` that blocked final
worktree finalization. An accidental temporary Work session created during API
setup was immediately interrupted and deleted; it did not affect the Coding
Project, benchmark repository, EASD run, or reported usage.

## Product defects found by dogfooding

The benchmark directly changed the EvoFlux implementation in three places:

- Completion verification now uses `sys.executable -m pytest`, preserving the
  source root inside isolated worktrees.
- Completion artifact identity now includes the current Git revision, so a
  cherry-pick/rebase/config change cannot reuse stale passing evidence.
- Isolated worktree machine evidence is admitted only after lead merge rather
  than when a member merely requests review.

The final public API also forbids callers from creating `machine` evidence;
only runtime completion verification can produce it.

## Conclusions and next actions

The EASD benchmark demonstrated its core value proposition: accepted intent, bounded
missions, retained failures, independent challenge, rework, final-revision
evidence, and service-computed Done. The run also showed that agent orchestration
can be wasteful and can weaken tests unless the method explicitly compares the
final suite to its seed contract.

Recommended next work:

1. add a deterministic test-strengthening gate that flags removed assertions or
   reduced seed coverage before integration;
2. add lead stop conditions for repeated `status`/`wait` calls to idle agents;
3. make artifact-cache identity and evidence-admission boundaries observable in
   the Evo Agent Specs panel;
4. run multiple identical seeds, including a single-agent control, before using
   cost or elapsed time to recommend model allocation;
5. add an accepted workload-size/SLO criterion before treating scheduler
   complexity as a blocking benchmark result;
6. repeat the competitive audit at release time before publishing any
   “first-to-market” wording.

The optional single-agent baseline in the protocol was not run. This report is
therefore a reproducible product-contract benchmark, not a controlled comparison
of EASD against single-agent development.
