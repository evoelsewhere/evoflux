---
name: coding-investigation
description: Investigate unfamiliar code behavior, or answer an exact symbol's definition, callers, callees, references, impact, and cross-repository relationship questions. Use it to trace activation, ownership, data flow, configuration, registration, and runtime wiring with bounded source evidence without mutating code; do not use it for a reproducible failure, implementation request, or review of an existing diff.
---

# Investigate code behavior

Remain read-only. Resolve one observable relationship at a time and stop as
soon as its entry point, deciding condition, and downstream effect are proven.
Do not load any bundled reference when this skill activates.

## Select one lane

- **Exact-symbol lane:** the user or current source already names a function,
  method, class, constant, or qualified symbol. Go directly to the graph gate.
- **Unknown-root lane:** the request names behavior, UI text, a route, flag,
  configuration key, event, or runtime effect. Discover one source anchor
  before using the graph. Never pass the request prose itself as `symbol`.

Do not run both lanes in parallel. Promotion from unknown-root to exact-symbol
ends broad discovery.

## Required tool transition

Apply this control flow literally:

```text
if the request names an exact declared symbol:
    code_graph(exact_symbol, smallest_operation)
else:
    result = one_literal_discovery(observed_request_artifact)
    if result shows a declared symbol tied to the behavior:
        code_graph(that_symbol, smallest_operation)
    else:
        read_only_the_matching_range_needed_to_reveal_a_declared_symbol
        code_graph(that_symbol, smallest_operation)
```

No `read`, second broad `grep`, task-tracker update, resource load, or graph call
on a filename/module may occur between a promotable declared symbol and the
required graph call. This transition is the execution contract; the remaining
sections explain how to choose its inputs and interpret its result.

Apply the post-graph exit gate literally:

```text
if the graph resolves one exact root, answers the requested structural
relationship, and reports no relevant ambiguity/freshness/truncation/dynamic gap:
    stop observing and answer from graph-returned source and call sites
else:
    name the one reported gap, then use one narrow observation that can resolve it
```

For a direct definition, callers, callees, or references question, a clean
graph result is complete evidence. Reading the returned definition/callsite
again is forbidden even when more context looks interesting.

## State machine

### 1. FRAME

Rewrite the request internally as one relationship to prove: definition,
inbound caller, outbound callee, non-call reference, activation condition,
state transition, impact, or repository boundary. Record the three possible
stop facts: entry point, deciding condition, downstream effect. Omit any fact
that the user's narrower question does not require.

Keep this state machine internal for one investigation. Do not create a task
tracker merely to restate these stages; use one only when the request contains
independent deliverables that require coordination.

### 2. DISCOVER — unknown-root lane only

Use one literal search for the most stable artifact visible in the request:
exact UI text, route, serialized field, configuration key, event name, tag,
registration key, or error text. Inspect only enough surrounding source to
connect a result to the requested behavior.

Search the observed spelling first. Do not combine guessed spelling variants or
run parallel broad searches for the feature name and mode name. A second
discovery call must be narrowed by a concrete result from the first.

Promote a result to an **anchor** only when source shows that it participates in
the behavior through an assignment, branch, call, registration, serialization,
or state transition. The graph anchor must be a declared code identifier such
as a function, method, class, or constant. A filename, module path, package,
comment, documentation mention, route string, config value, or same-looking
name is not a graph symbol. If discovery yields only a file, inspect the narrow
matching range to expose the declared identifier; never call `definition` on
`tier_policy.py`, `routes/chat`, or another file/module label.

If several candidates appear, choose the one closest to the requested control
point. Do not investigate every candidate. Make another broad discovery call
only when no result can be promoted; narrow the next search using evidence from
the previous result instead of trying a synonym.

### 3. GRAPH — mandatory transition for exact symbols

Once an anchor is an exact code symbol and a structural relationship is needed,
the **next structural observation must be** native `code_graph`. Do not continue
repo-wide grep, load background references, or reread source first.
Choose among `definition`, `callers`, `callees`, `references`, `impact`, and
`neighborhood` from the question being proved:

| Question to prove | Operation |
| --- | --- |
| Where is this exact symbol declared? | `definition` |
| Which sites can invoke it? | `callers` |
| What does it invoke directly? | `callees` |
| Where is a constant, type, callback, or symbol used? | `references` |
| What can a change affect transitively? | `impact` |
| What immediately surrounds this boundary? | `neighborhood` |

Use `freshness_policy="fast"` for the first graph call and normal interactive
navigation. If it returns `fresh`, do not rerun with a stronger policy. If it
returns `partial` and a reported dirty file overlaps the question, use a
targeted source read for a local gap or retry once with `"balanced"` when the
relationships must be recomputed. After an edit that can change relationships,
use `"balanced"` once before relying on the updated structure. Use `"strict"`
only for a final,
high-consequence completeness check when watcher coverage is unavailable or
untrusted; never use it for discovery.

Start at depth 1. Use `impact` or a greater depth only for an explicitly
transitive question. Disambiguate multiple definitions before traversal.
Treat an empty edge set as no resolved static relationship, not proof that no
dynamic relationship exists. Reuse graph-returned definition and call-site
source instead of reading those ranges again.

### 4. VERIFY — only the unresolved semantic gap

Read targeted source only for branch conditions, value semantics, persistence,
configuration, generated wiring, or repository boundaries not established by
the graph result. Use tests, logs, a debugger, or runtime inspection for
reflection, dependency injection, registries, dynamic imports, concurrency,
or environment-specific behavior.

Every additional observation must name one missing stop fact that it can prove.
If it cannot, stop. Never repeat an unchanged failed graph query, zero-result
search, or unchanged file range.

### 5. STOP AND CHECK

Stop when every required stop fact has bounded evidence. Before answering:

- test the negative path as well as the enabling path;
- distinguish persisted state from transient UI or process state;
- distinguish deferred/hidden capability from hard exclusion;
- preserve direction, repository identity, freshness, dirty-file, pending-edge,
  truncation, and dynamic-boundary limitations;
- remove any claim that is not supported by the cited range or runtime result.

## Trajectory example

For “find the logic that enables WebBridge,” a valid trajectory is:

```text
literal discovery of "webbridge_enabled"
  -> source ties WEBBRIDGE_SESSION_TAG to the request handler
  -> code_graph(symbol="WEBBRIDGE_SESSION_TAG", operation="references")
  -> targeted reads for the returned branch conditions
  -> stop after entry, enable/disable conditions, and effect are proven
```

An invalid trajectory repeatedly searches `WebBridge`, `webbridge`, policy
filenames, and guessed variants, reads whole files, then calls `definition` on
a symbol already inspected. Calling `definition` on `tier_policy.py` or a
module name is also invalid. These actions expand context without answering a
new fact.

## Optional resources

- Read [references/code-graph-contract.md](references/code-graph-contract.md)
  only after a graph result reports ambiguity, degraded freshness, truncation,
  pending cross-repository edges, or a named transitive-impact question.
- Read [references/evidence-chain.md](references/evidence-chain.md) only after
  evidence confirms competing anchors, a cross-repository boundary, or a
  static path that ends at dynamic/generated wiring.

## Deliverable

Lead with the direct answer. Show the smallest evidence chain with file and
line anchors, relevant conditions, downstream effect, and explicit static or
runtime limitations. Separate confirmed facts from bounded inference and
unresolved gaps.
