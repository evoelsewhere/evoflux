# EASD prior-art and market audit — 2026-08-23

## Decision

EvoFlux will use **EASD** as the name of its spec-governed Agent-Driven
Development methodology:

> **EASD — Evo Agent Specification-Driven Development**

EASD is not presented as the invention of Spec-Driven Development, multi-agent
coding, or the phrase Agent-Driven Development. Those all have public prior art.
The defensible product thesis is narrower:

> EvoFlux can become the first local-first, multi-model coding workspace that
> compiles an accepted specification into accountable agent missions and
> requires snapshot-bound evidence before convergence.

This is a positioning hypothesis, not a release claim. It must be re-audited
against shipping products before public use.

## Research questions

1. Which products already operationalize SDD?
2. Which products already orchestrate multiple coding agents?
3. Has Agent-Driven Development already been named or formalized?
4. What remains meaningfully different and technically defensible for EvoFlux?
5. Which existing EvoFlux primitives reduce implementation risk?

## Market evidence

### GitHub Spec Kit

[GitHub Spec Kit](https://github.com/github/spec-kit) makes specifications the
primary executable development artifact. Its current sequence is constitution,
specify, plan, tasks, implement, and converge. It also includes evidence-based
bug assessment and idea-assessment workflows.

Implication: EvoFlux cannot claim to originate SDD or spec-to-implementation
convergence. EASD should interoperate with Spec Kit artifacts rather than
forcing users to replace them.

### Kiro Specs

[Kiro Specs](https://kiro.dev/docs/specs/) creates requirements/bug analysis,
design, and tasks artifacts. It tracks task status and builds a dependency graph
that runs independent tasks concurrently in waves.

Implication: “SDD plus parallel tasks” is already a product capability. EASD
must add accountable agent ownership, artifact-bound evidence, explicit spec
deviation, and cross-agent convergence rather than only another task graph.

### OpenAI Codex

[Official OpenAI documentation for Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
describes specialized agent threads, context isolation, parallel work, custom
agents, model/reasoning selection, sandbox inheritance, steering, and result
collection. The official guidance recommends GPT-5.6 for demanding agents,
GPT-5.6 Terra for efficient read-heavy workers, and GPT-5.6 Luna for narrow,
repeatable work.

Implication: spawning role-specific agents and selecting models per role is not
an EASD differentiator. Binding those agents to versioned requirements and
machine evidence can be.

### Claude Code agent teams

[Claude Code agent teams](https://code.claude.com/docs/en/agent-teams) provide a
lead, independent teammates, shared tasks, direct messaging, model selection,
plan approval, hooks, and explicit guidance for avoiding write conflicts.

Implication: lead-and-specialists, shared task lists, plan approval, and quality
hooks are prior art. EASD must make the specification and evidence graph a
durable product domain, not rely on prompts or a transient task list.

### Cursor subagents

[Cursor subagents](https://cursor.com/docs/subagents) provide separate context
windows, foreground/background execution, automatic delegation, custom prompts,
tool/model selection, read-only agents, and built-in Explore/Bash/Browser roles.

Implication: context isolation and specialized agents are expected baseline
features. EASD should expose why each agent exists, which acceptance criteria
it owns, and what evidence it produced.

### Devin managed sessions

[Devin advanced capabilities](https://docs.devin.ai/work-with-devin/advanced-capabilities)
include a coordinator that scopes work, launches isolated managed sessions,
monitors them, resolves conflicts, compiles results, analyzes prior sessions,
and creates reusable playbooks.

Implication: parallel isolated sessions and learning from completed work are
also prior art. EASD learning must remain grounded in AC outcomes, evidence,
rework, conflict, cost, and final defects rather than only session summaries.

### Published ADD methodologies

[agentdriven.dev](https://agentdriven.dev/) already uses Agent-Driven
Development for a role-based human/agent working protocol.
[Pyro-IV's ADD framework](https://github.com/Pyro-IV/Agent-Driven-Development)
defines Scope → Frame → Constrain → Execute → Verify → Consolidate, plus agent
briefs, context packs, constraints, validation checklists, execution logs, and
a maturity model.

Implication: EvoFlux must not claim to coin ADD. EASD is EvoFlux's concrete,
product-executable ADD protocol and reference implementation.

### Multi-agent research

[MetaGPT](https://arxiv.org/abs/2308.00352) shows that encoding standardized
operating procedures, role-specific intermediate artifacts, and verification
can reduce cascading inconsistency compared with naive chains of agents.

Implication: EASD should use typed contracts and artifacts at every boundary.
Free-form inter-agent prose is useful for discussion but insufficient for
acceptance, evidence, and convergence.

## Competitive gap

| Capability | Spec Kit | Kiro | Codex | Claude Code | Cursor | Devin | EASD target |
|---|---:|---:|---:|---:|---:|---:|---:|
| Versioned specification artifacts | Yes | Yes | Project instructions, not a full feature spec flow | Plan/task-oriented | Plan/rules | Prompt/playbook/knowledge | Yes |
| Parallel specialized agents | Via integrated agent | Parallel tasks | Yes | Yes | Yes | Yes | Yes |
| Explicit task dependencies | Tasks | Dependency graph/waves | Parent orchestration | Shared task list | Parent orchestration | Coordinator/workflows | Durable mission DAG |
| Exclusive write ownership | Agent-dependent | Not established by cited Specs page | Sandbox/worktree-dependent | Guidance, not a spec relation | Worktrees available | Isolated VMs | Required path/repo claims |
| AC-to-agent traceability | Not established | Tasks derive from requirements | Not established | Not established | Not established | Not established | Required |
| Evidence bound to exact artifact hash | Not established | Not established | Tool/test results | Hooks/results | Agent results | Session/PR results | Required |
| Explicit spec deviation workflow | Not established | Requirements analysis/revision | Not established | Plan revision | Plan revision | Coordinator feedback | Required |
| Convergence report across ACs | Spec convergence | Task completion | Parent summary | Lead synthesis | Parent summary | Coordinator synthesis | Required, machine-derived |
| Local-first, multi-model reference runtime | Toolkit | Product/provider-controlled | OpenAI/Codex models | Claude models | Multi-model product | Devin models | Yes |

“Not established” means the cited public source did not prove that capability;
it is not a claim that no internal or newer implementation exists.

## EvoFlux fit

EvoFlux already ships most lower-level primitives required for EASD:

- durable `DelegationTask` rows with dependencies, attempts, deadlines, target
  path claims, and worktree isolation;
- typed `TaskSpec` delegation and `HandoffArtifact` results;
- machine-generated `CompletionContract` evidence bound to an artifact hash;
- hash-bound Plan and Workflow approvals;
- stale-base and atomic ChangeSets;
- Goal mode, Monitor/SSE, Problems/LSP feedback, code context, and OTEL;
- independent per-agent model/reasoning configuration across 19 providers.

The missing layer is one durable root that connects:

```text
spec revision → AC → delegation mission → evidence → deviation → convergence
```

## Defensible differentiation

EASD should be published as an open protocol with EvoFlux as its first
reference runtime. The durable moat is the implementation:

1. **Spec compiler:** normalize Markdown, Spec Kit, Kiro, or native manifests
   into one versioned internal contract.
2. **Mission compiler:** create an ownership/dependency graph with explicit AC
   coverage, models, tools, paths, repositories, isolation, and evidence policy.
3. **Evidence ledger:** accept machine, review, and human evidence but bind every
   claim to spec revision and code artifact/revision.
4. **Deviation control:** prevent agents from silently expanding normative
   behavior.
5. **Convergence engine:** calculate Done from AC coverage and open risks rather
   than from agent prose.
6. **Learning loop:** compare roles/models using accepted ACs, conflicts,
   rework, cost, latency, and post-merge outcomes.

## Public-claim gate

Before using “first” publicly:

- repeat this audit on the target release date;
- publish the exact feature matrix and source dates;
- demonstrate a reproducible EASD run from accepted spec to convergence;
- publish the EASD schema and methodology version;
- include a benchmark comparing single-agent and EASD runs;
- qualify the claim as local-first, multi-model, spec-compiled, and
  evidence-gated.
