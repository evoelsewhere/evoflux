---
name: coding-investigation
description: Investigate unfamiliar code behavior, or answer an exact symbol's definition, callers, callees, references, impact, and cross-repository relationship questions. Use it to trace activation, ownership, data flow, configuration, registration, and runtime wiring with bounded source evidence without mutating code; do not use it for a reproducible failure, implementation request, or review of an existing diff.
---

# Investigate code behavior

Remain read-only. Prove only the requested entry point, deciding condition, and
downstream effect, then stop. Do not load bundled references unless a condition
under **Gaps** requires one.

## Choose one lane

- **Exact symbol:** the request or observed source names a function, method,
  class, constant, or qualified symbol. Skip `code_context` with `action="search"` and call native
  `code_context` immediately.
- **Unknown root:** the request names behavior, UI text, route, field, tag,
  configuration key, event, or runtime effect. Run one `code_context` with `action="search"` using that
  stable artifact, select one declared identifier, then promote it to graph.

Never pass request prose, a filename, module, route, comment, or guessed spelling
as the exact-symbol `query`. Promotion from unknown-root to exact-symbol ends broad
discovery.

```text
exact declared symbol known
  -> code_context(action=smallest operation, query=symbol)

unknown root
  -> code_context(action="search", query=observed artifact, refresh=true)
  -> code_context(action=smallest operation, query=one returned declared identifier)
  -> targeted source only for one named semantic gap
  -> answer
```

After a promotable search result, do not run another `code_context` with `action="search"`, `grep`,
`read`, resource load, or filename graph query before the graph call. If search
has no promotable result, use one narrow literal search or read to expose an
identifier, then call graph. Once promoted, the **next structural observation
must be** `code_context`.

## Graph operation

Choose the smallest of `definition`, `callers`, `callees`, `references`,
`impact`, or `neighborhood` that proves the requested relationship.

| Relationship to prove | Operation |
| --- | --- |
| declaration | `definition` |
| inbound invocation | `callers` |
| outbound invocation | `callees` |
| constant/type/callback use | `references` |
| transitive inbound effect | `impact` |
| immediate bidirectional boundary | `neighborhood` |

Start at depth 1. Increase depth only for an explicitly transitive question.
Disambiguate multiple definitions before traversal. Reuse graph-returned source
and callsites; never read the same evidence again.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

## Gaps

A clean exact graph result fully answers a direct definition/callers/callees/
references question. Otherwise name one gap before observing more source:

- branch/value semantics or persistence: read the smallest returned range;
- reflection, DI, registry, generated wiring, concurrency, or environment:
  use a bounded test, log, debugger, or runtime check;
- empty edges: report no resolved static relationship, not proof of absence;
- ambiguity, truncation, or reported index limitations:
  narrow using the limitation reported by the tool.

Keep evidence proportional to the question. Stop when the requested
relationship is proven; when static analysis reaches a dynamic boundary,
state that limitation instead of expanding discovery without a new hypothesis.

Read [references/code-context-contract.md](references/code-context-contract.md) only
for ambiguity, truncation, or reported index limitations,
or explicitly transitive impact. Read
[references/evidence-chain.md](references/evidence-chain.md) only for competing
anchors, repository boundaries, or static paths ending in dynamic wiring.

## Final evidence check

Before answering:

- verify both enable and disable/negative paths;
- distinguish persisted state from transient UI/process state;
- distinguish deferred/hidden tools from hard exclusions;
- preserve direction, scope, repository, index version,
  truncation, and dynamic-boundary limitations;
- remove any claim not supported by a cited range or runtime result.

For example, tracing WebBridge should be bounded to:

```text
code_context(action="search", query="webbridge_enabled")
  -> code_context(action="references", query="WEBBRIDGE_SESSION_TAG")
  -> targeted reads only for request mapping and branch semantics
  -> enable path + negative path + downstream exclusion effect
```

## Deliverable

Lead with the direct answer. Give the smallest evidence chain with file/line
anchors, deciding conditions, downstream effect, and explicit limitations.
Separate confirmed facts from bounded inference. Do not narrate the search.
