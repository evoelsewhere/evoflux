# Harness Evolution for EvoFlux

## Purpose

Evolve EvoFlux's shared agent harness using reproducible evidence. Changes should improve task outcomes or reduce wasted work while preserving the task's full context, user controls, and safety boundaries.

This plan covers a common Work and Coding harness, progress-aware runtime behavior, evaluation, and a review-gated path for future configuration changes. Work and Coding remain application modes; they are not separate harness products.

## Design principles

1. **One shared harness, complete task context.** Each run retains its mode, role, prompt, relevant history, workspace, permissions, tools, and other effective configuration. Modes and task families are useful reporting slices, not reasons to strip context from a run.
2. **Measure before changing behavior.** Compare the same versioned cases, fixtures, provider/model, permissions, and attempt policy before and after a change. Separate deterministic runtime checks from provider-backed task-quality results.
3. **Keep evolution bounded and reviewable.** Start with explicit configuration proposals. Do not execute generated code, modify the active harness automatically, or change model weights.
4. **Protect user data.** Use sanitized, versioned evaluation fixtures. Do not ingest ordinary private session transcripts by default. Any opted-in trace must be redacted and access-controlled; credentials never enter snapshots or reports.
5. **Keep comparisons attributable.** Hold provider/model and fallback behavior constant for harness-only comparisons. Evaluate model changes as separate experiments.
6. **Fail open when progress is uncertain.** A runtime guard should explain a block and preserve a path for legitimate work to continue.

## Existing foundation and gap

EvoFlux already compiles agent configuration from user-authored instructions and code-owned mode/role profiles, assembles ordered hook stages, creates run-local tool registries, and records model/tool activity. Tool definitions can also describe batching and reusable observations.

The missing pieces are a reproducible case protocol tied to the effective runtime configuration, comparable run evidence, and progress tracking across model iterations. Future configuration evolution also needs an explicit candidate format and review gate. Extend existing runtime boundaries; do not create a parallel agent loop or transcript store.

## Shared harness and evaluation architecture

### Evaluation cases

Each versioned case describes the full task context, starting messages, mode and role, workspace fixture, permissions, tool adapter profile, grader, and repeat/progress expectations. Every attempt starts from a clean fixture so one run cannot affect another.

The suite should cover ordinary successful Work and Coding tasks, multi-step work, legitimate research across distinct evidence, changed-argument calls that make progress, repeated reads that make no progress, transient and terminal errors, side-effecting tools, and delegation where relevant. Cases should include both allowed progress and expected blocking so the guard cannot pass by simply suppressing calls.

### Effective harness snapshot

Build evaluations through the same configuration compiler and hook/tool assembly used by production. Record a stable snapshot identity containing the source revision, mode, role, provider/model, prompt digest, ordered hook manifest, tool schema/policy digest, skill versions, MCP names without secrets, permission profile, and fixture digest.

Candidate changes may alter only fields explicitly listed in their manifest. A comparison is valid only when case and context identity, suite version, fixture, adapter profile, provider/model, fallback policy, permissions, and attempt policy match. Intended candidate changes are recorded as such; they are not silently treated as missing context.

### Run evidence

Keep append-only run records with case and suite IDs, snapshot ID, run/attempt identity, outcome and grader result, model/tool counts, progress and block signals, token use, latency, and a reference to any protected redacted trace. Store large prompts, workspaces, and tool payloads in fixtures or protected artifacts rather than duplicating them in the result index.

Report overall outcomes and Work/Coding or task-family slices. Slices help explain trade-offs; the complete suite is the promotion surface. Scripted-provider results establish deterministic loop behavior only. Provider-backed quality results belong in a separate cohort and need pinned configuration and repeated attempts where model behavior is stochastic. Live external services should use recorded fixtures or be reported separately.

## Progress-aware runtime guard

Retain existing same-response batch limits and observation reuse. Add run-local tracking across model iterations using canonical tool identity, normalized arguments, tool outcome, and explicit tool metadata for observation identity, read-only behavior, side effects, idempotency, and error retry policy.

- A changed argument is a signal to inspect, not proof of progress or repetition.
- A repeated read can be blocked only when the policy has evidence that the same target remains unchanged and the outcome adds no new evidence.
- Explicitly safe transient reads may receive a bounded retry. Unchanged permission, validation, and not-found failures should not be retried as if successful evidence had been produced.
- Unknown tools, missing metadata, classifier failures, and uncertain progress fail open.
- Side-effecting calls are not deduplicated unless the tool explicitly declares suitable idempotency semantics.
- A block is visible to the model and represented in evaluation evidence with its reason.

## Candidate evolution

The initial evolution flow is offline and review-gated. A human-authored or externally proposed candidate is a declarative patch with a parent snapshot, patch digest, evidence references, hypothesis, target cases, at-risk cases, paired evaluation report, and review state.

The initial editable surface may include system/profile text, available-tool selection, assigned skills, and MCP selection when stable adapters exist. Provider/model and fallback settings remain fixed during harness-only evaluation. Permission policy, sandbox rules, executable hook code, tool implementations, and provider wire formats are not candidate-editable in the first iteration.

Validate a candidate against the allow-listed schema, evaluate it on isolated fixtures, and return a report without changing active user configuration. Applying or rejecting a candidate is a separate user action. Preserve the parent snapshot for rollback. Do not auto-promote ambiguous results.

## Data model

```text
EvaluationCase
  case_id, suite_version, task_family, app_mode, role
  initial_messages, fixture_workspace, permissions, tool_adapter_profile
  grader_id, task_context_digest, progress_expectations

HarnessSnapshot
  snapshot_id, source_revision, app_mode, role, provider_model
  prompt_digest, ordered_hook_manifest, tool_schema_digest
  skill_version_digests, mcp_names_without_credentials
  permission_profile, workspace_fixture_digest

EvaluationRun
  run_id, case_id, suite_version, snapshot_id, attempt_policy
  outcome, grader_result, model_calls, tool_calls, progress_signals
  blocked_calls, tokens, latency_ms, redacted_trace_ref

CandidateManifest
  candidate_id, parent_snapshot_id, config_patch_digest, evidence_refs
  hypothesis, target_cases, at_risk_cases, gate_report, review_state
```

## Evaluation and promotion criteria

For each change, retain the before result and run the same cases after the change. Compare paired per-case outcomes, task compliance, regressions, repeated no-progress calls, legitimate calls wrongly blocked, completion after safe retry, prevented unsafe repeats, model/tool calls, tokens, and latency. Include mode/task-family slices and retain per-task outputs so an aggregate improvement cannot hide a regression.

Scripted runtime invariants can be deterministic gates. Quality and cost thresholds must be declared in the run report. A grader/provider outage, fixture drift, or incomplete adapter makes a run invalid or incomplete; it is not counted as success or failure and cannot promote a candidate. A changed case increments the suite version and requires a new baseline. Keep evolution, validation, and sealed holdout partitions separate before candidates learn from evaluation evidence.

Do not claim generalization from cases used to develop a candidate. Provider-backed results should disclose model/configuration and attempt policy, and avoid treating stochastic differences as deterministic proof. Report monetary cost only when a pinned price source is available; otherwise report token use and latency.

## Implementation sequence

1. **Establish the evaluation contract.** Define versioned full-context cases, fixture isolation, task-specific graders, snapshot identity, and paired-run checks. Capture a baseline before changing loop behavior.
2. **Add progress-aware tracking.** Implement opt-in metadata and run-local tracking in the production agent loop. Add focused cases for useful changed arguments, changed arguments without new evidence, terminal/transient errors, missing metadata, and side effects.
3. **Measure the runtime change.** Re-run the same deterministic cases and compare blocks, false blocks, task outcomes, and call counts. Add provider-backed paired quality evaluation when a suitable pinned environment is available; keep that evidence separate.
4. **Add offline candidate evaluation.** Define the allow-listed patch schema, bind each candidate to its parent snapshot and paired report, and keep evaluation from mutating active configuration.
5. **Expand only when evidence supports it.** Add candidate search, bounded harness variants, task routing, or broader edit surfaces only when repeated cross-group conflicts or measured limitations justify them.

## Research that informs the approach

These projects offer reusable evaluation and search ideas; EvoFlux should preserve its own runtime, full task context, and safety boundaries rather than depending on another agent framework.

| Project | Useful idea for EvoFlux |
| --- | --- |
| [HarnessX](https://github.com/Darwin-Agent/HarnessX) | Explicit harness components, processors, recipes, and benchmark-driven iteration. Treat reported scores on optimization task sets as development evidence; use a separate holdout for generalization claims. |
| [GEPA](https://github.com/gepa-ai/gepa) and [DSPy GEPA](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/GEPA/overview.md) | Trace-grounded feedback, stage-specific reflection, bounded search, and preserving candidates with different strengths. Reuse the method without adding a broad optimization dependency initially. |
| [OpenHands Benchmarks](https://github.com/OpenHands/benchmarks) | Pinned runners, isolated task environments, and per-instance artifacts. External suites can complement EvoFlux cases but do not replace complete Work/Coding context. |
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) and [tau-bench](https://github.com/sierra-research/tau2-bench) | Reproducible interactive/tool-agent evaluation and explicit stateful task environments. Use adapters where the task and environment match. |
| [ADAS](https://github.com/ShengranHu/ADAS) | Treat agent-structure search as a later research direction. EvoFlux should first demonstrate value with a constrained, reviewable configuration surface. |

## Safety, failure handling, and boundaries

- Evaluation runs use disposable fixtures and never write to live sessions, user workspaces, or active configuration.
- Exclude credentials and secret values from snapshots, candidates, and indexed evidence. Redact private paths, personal data, and untrusted tool content in stored traces.
- Reject candidate patches that exceed the allowed configuration surface.
- Preserve user control over applying and rolling back a candidate.
- Keep uncertain runtime decisions visible and recoverable; do not silently suppress a possibly legitimate action.
- This plan does not include model-weight updates, GRPO/training infrastructure, automatic production self-modification, arbitrary generated tools or processors, or provider-specific behavior.

## Cross-feature impact

- `app/agent/agent_loop/`: run-local progress accounting and model-visible block/retry outcomes.
- `app/agent/tools/`: metadata for observation identity, error policy, side effects, idempotency, and adapters.
- `app/agent/hooks/`, mode/team composition, and effective-config loading: snapshot the production context without replacing its assembly path.
- Observability: correlate evaluation cost/latency while keeping evaluation artifacts distinct from ordinary session telemetry.
- Tests and evaluation tooling: deterministic fixtures, paired-run validation, and reports.
- Architecture/feature documentation and in-app Help if evaluation controls become user-visible.

No database migration or user-facing evaluation screen is required for the initial runtime guard.

## Current implementation status

The feature branch implements opt-in, run-local progress tracking for repeated safe reads, including built-in filesystem-read scoping and explicit retry/error behavior. Candidate evolution and provider-backed task-quality evaluation remain separate follow-on work; deterministic fixture results must not be presented as proof of model quality or generalization.
