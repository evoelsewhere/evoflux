# EASD benchmark protocol

Status: executed and converged on 2026-08-24; see the
[benchmark report](../analysis/easd-benchmark-2026-08-24.md)

## Purpose

The benchmark must prove the EASD product contract, not merely show that one
model can write code. It compares a documented specification, mission ownership,
evidence collection, and convergence outcome in a separate reproducible Coding
Project.

## Benchmark repository

Create a separate Git repository named `evoflux-easd-benchmark`. It contains a
small standard-library Python project so results do not depend on network or
third-party package availability.

The first run predates the final EASD name and remains at the legacy filesystem
path `evoflux-trace-benchmark`; the benchmark report preserves that exact
reproduction identity. New runs use the EASD repository name.

The project will implement a deterministic job scheduler library with:

- input/schema parsing;
- dependency validation and cycle detection;
- stable wave scheduling for parallelizable jobs;
- execution-result aggregation;
- JSON CLI output;
- tests and documentation.

The seed intentionally omits the implementation while shipping public tests,
an accepted EASD specification, and a hidden-oracle script retained outside
agent context for final audit.

## Why this workload

- It mirrors EASD's own mission DAG without testing EASD through a trivial
  CRUD toy.
- Parser, graph, scheduler, CLI, tests, and docs can be given disjoint ownership.
- Cross-module integration is required, so convergence is meaningful.
- The expected result is deterministic and runs offline.

## Benchmark acceptance criteria

- **BENCH-AC-1:** Valid jobs are parsed from JSON and invalid shapes fail with
  stable typed errors.
- **BENCH-AC-2:** Missing dependencies and cycles are rejected with deterministic
  diagnostics.
- **BENCH-AC-3:** Independent jobs are grouped into stable topological waves;
  ordering is deterministic across repeated runs.
- **BENCH-AC-4:** Result aggregation distinguishes passed, failed, skipped, and
  blocked jobs.
- **BENCH-AC-5:** CLI reads a file/stdin and emits stable JSON with documented
  exit codes.
- **BENCH-AC-6:** Public and hidden tests pass without network access.
- **BENCH-AC-7:** Every implementation Mission maps to at least one BENCH AC and
  has non-overlapping ownership or explicit integration ownership.
- **BENCH-AC-8:** EASD Convergence Report covers all required ACs with evidence
  bound to the final Git revision.

## Role/model policy

Use the configured Codex OAuth provider:

| EASD role | Preferred model | Reasoning |
|---|---|---|
| Lead / Convergence owner | `codex:gpt-5.6-sol` | `high` or `xhigh` |
| Architect / graph designer | `codex:gpt-5.6-sol` | `high` |
| Explorer / source mapper | `codex:gpt-5.6-luna` or `codex:gpt-5.6-terra` | `medium` |
| Builder missions | `codex:gpt-5.6-terra` | `medium` or `high` |
| Independent verifier | `codex:gpt-5.6-sol` | `high` |

This follows official OpenAI guidance: GPT-5.6 for demanding multi-step agents,
Terra for efficient worker/exploration tasks, and Luna for narrow repeatable
work. Actual selected IDs and fallbacks must be recorded in the report.

## Run protocol

1. Record EvoFlux commit, benchmark seed commit, provider/model catalogue, and
   environment/tool versions.
2. Create/register the repository as an EvoFlux Coding Project.
3. Create EASD Development Run and accept the benchmark spec.
4. Lead compiles missions and records AC/path ownership before delegation.
5. Execute missions through EvoFlux team runtime and worktrees where mutable
   work runs in parallel.
6. Import machine evidence from mission completion contracts.
7. Run independent verification and the hidden oracle.
8. Attempt convergence; any rejected attempt and reasons stay in the report.
9. Record final revision, tests, AC matrix, deviations, conflict/rework, usage,
   elapsed time, and model allocation.

## Metrics

- required AC pass/waive/uncovered counts;
- machine/review/manual evidence counts;
- mission count, dependency depth, parallel width;
- mission attempts/rejections and worktree conflicts;
- spec deviations and resolutions;
- elapsed wall time;
- total and per-agent tokens;
- tokens per passed AC;
- final public/hidden test outcomes;
- convergence attempts and rejected-gate reasons;
- human interventions.

## Baseline

If time/provider budget permits, run one single-agent baseline using
`codex:gpt-5.6-sol` against the same seed/spec. The comparison is directional,
not a scientific generalization. Report workload, prompts, context, model,
reasoning, and test oracle identically.

## Success gate

The benchmark succeeds only if:

- all BENCH ACs pass with acceptable evidence;
- no blocking deviation remains;
- public and hidden tests pass at the recorded final revision;
- the Convergence Report is reproducible from persisted EASD state;
- the report includes failures/rework rather than presenting only the final
  successful transcript.
