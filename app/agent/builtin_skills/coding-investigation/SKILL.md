---
name: coding-investigation
description: Investigate unfamiliar code behavior when the exact source root is unknown or static relationships alone cannot explain activation, ownership, data flow, configuration, registration, or runtime wiring. It produces a bounded source-and-runtime evidence chain without mutating code. Do not use it for a known symbol's purely structural graph question; use code-graph-navigation for that workflow.
---

# Investigate code behavior

Answer a concrete behavior question when its root or wiring is not yet known.
Do not turn the user's natural-language request into a structural query; first
resolve exact identifiers, configuration keys, or runtime boundaries.

## Investigation loop

1. Define the question as an observable relationship: entry point, owner,
   activation condition, caller set, downstream effect, state transition, or
   repository boundary.
2. Locate the exact root identifier. Use literal discovery for user-facing
   strings, routes, feature flags, configuration, registration keys, comments,
   generated names, and dynamic wiring.
3. If locating the root reduces the remaining question to a known symbol's
   structural relationships, switch to the `code-graph-navigation` workflow;
   this skill does not redefine that operation contract.
4. Otherwise, inspect only the branches, state changes, configuration,
   registration, generated wiring, and repository boundaries needed to explain
   the behavior.
5. Follow another evidence step only when the current one cannot establish the
   deciding condition or downstream effect. Avoid expansion that grows context
   without increasing confidence.
6. Seek runtime evidence for reflection, registries, dependency injection,
   generated code, dynamic imports, or environment-specific behavior that
   static relationships cannot prove.

Read [references/evidence-chain.md](references/evidence-chain.md) when the path
crosses repositories, contains duplicate symbols, mixes static and dynamic
wiring, or needs an impact assessment rather than a simple caller answer.

## Evidence discipline

- Never merge several plausible roots into one narrative.
- Do not recollect source evidence already returned by a selected specialist or
  native tool.
- Separate confirmed source facts, runtime evidence, and unresolved
  hypotheses.
- Stop when every material claim in the answer has a bounded source or runtime
  anchor.

## Deliverable

Lead with the direct answer. Then show the minimal evidence chain with file and
line anchors, relevant conditions, downstream effect, and any dynamic or
cross-repository limitation. Remain read-only unless the user separately asks
for a change.
