---
name: coding-router
description: Use this skill to route non-trivial software-engineering work to the smallest appropriate coding specialist. Apply it when a request involves investigating, debugging, implementing, migrating, optimizing, reviewing, securing, or testing code; skip it for simple factual answers or one-step file operations that need no specialist workflow.
---

# Route coding work

Classify the user's outcome before changing code. Activate the smallest
specialist set that provides material guidance, then follow those instructions
instead of expanding this router into a second workflow.

## Routing procedure

1. Identify the primary outcome: explain, diagnose, change, transition,
   optimize, assess, harden, or prove.
2. Select one primary specialist:
   - `code-graph-navigation` when an exact function, method, class, or qualified
     symbol is already known and the question is its definition, callers,
     callees, references, impact, neighborhood, or cross-repository edges.
   - `coding-investigation` for ownership, enablement, data flow, or unfamiliar
     behavior when the exact structural root is not known yet or static and
     dynamic evidence must be combined.
   - `coding-debugging` for a reproducible failure with an unknown cause.
   - `coding-implementation` for a scoped feature or fix whose intended
     contract is already clear.
   - `coding-migration` for staged compatibility, data movement, or ordered
     producer/consumer transitions.
   - `coding-performance` for measured latency, throughput, memory, I/O, or
     cost work.
   - `coding-review` for a read-only defect audit of an existing change.
   - `coding-security` for trust boundaries, attacker-controlled input,
     authorization, secrets, or abuse cases.
   - `coding-testing` for test strategy, missing coverage, flakes, or proving a
     contract across boundaries.
3. Activate a second specialist only when the request contains a distinct
   secondary outcome. Investigation before implementation is usually one
   workflow, not two simultaneous activations.
4. Preserve the user's requested posture. A review remains read-only; a
   diagnosis does not silently become a fix; an implementation request may
   include the investigation necessary to implement safely.
5. If no specialist adds meaningful procedure, continue without one.

Read [references/routing-matrix.md](references/routing-matrix.md) when two
specialists appear plausible, the request crosses repositories or deployment
boundaries, or the work changes posture during execution.

## Guardrails

- Route by desired outcome and evidence state, not by keywords alone.
- Do not activate every adjacent specialist "just in case."
- Do not restate specialist instructions in the final answer.
- Keep repository-native navigation and execution capabilities native; this
  router chooses a workflow. The `code-graph-navigation` workflow teaches the
  native graph contract but does not replace or wrap the native tool.
