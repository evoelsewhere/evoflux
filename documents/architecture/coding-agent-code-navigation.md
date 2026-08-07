# Coding Agent Code-Navigation Contract

## Purpose

EvoFlux separates two different jobs:

1. **Discovery** finds the identifier or file the user is talking about.
2. **Structural navigation** follows relationships for one exact code symbol.

The native `code_graph` tool performs only the second job. It must never rank
source against the user's natural-language request. This boundary keeps
callers, callees, references, and impact deterministic and auditable.

## Runtime instruction layers

The same contract is enforced at several independent layers:

| Layer | Responsibility |
|---|---|
| Coding skill body | Teaches exact-symbol workflow only after the relevant Coding workflow activates |
| Tool JSON schema | Accepts one non-whitespace symbol and a closed operation enum |
| Native service boundary | Rejects empty/prose symbols even when invoked outside the agent tool |
| Exact resolver | Matches `name`/`qualified_name`; suggestions are never traversed |
| Traversal engine | Follows only operation-appropriate edge directions and kinds |
| Ambiguity guard | Refuses to traverse multiple exact definitions as one root |
| Renderer | Returns definition source and bounded call-site windows |
| Telemetry/tests | Detects duplicate/fallback navigation and locks the contract in regression tests |

The loader never appends graph workflow policy at mode level. Exact-symbol
guidance lives inside activated Coding skills such as investigation, debugging,
implementation, review, testing, security, migration, and performance. Schema
and service validation protect execution independently of which workflow is
loaded.

## Agent decision flow

```text
Does the task name a code identifier?
  no  -> discover an identifier/file with glob or grep
  yes -> normalize only syntax such as trailing ()
           |
           v
        choose one structural question
        definition | callers | callees | references | impact | neighborhood
           |
           v
        call code_graph at depth 1
           |
           +-- no exact match -> inspect suggestions, call exact candidate
           +-- multiple matches -> add qualified symbol/path/repository, retry
           +-- exact match -> use returned definition and callsites directly
           +-- static limitation -> declare it, then use the narrow fallback
```

### Operation semantics

| Operation | Direction | Intended question |
|---|---|---|
| `definition` | none | Where is X and what is its complete indexed body? |
| `callers` | inbound `calls` plus callable references | Where can X be invoked? |
| `callees` | outbound `calls` | What does X directly invoke? |
| `references` | all inbound structural references | Where is X statically used? |
| `impact` | transitive inbound references | What can be affected by changing X? |
| `neighborhood` | inbound and outbound | What immediately surrounds X? |

Depth defaults to one because it answers the most common question with the
least noise. Only `impact` or an explicitly transitive user request normally
justifies a larger depth.

## Tool-selection rules

Use `code_graph` for a known symbol's structure. Use `grep`/`glob` before the
graph only when the identifier is unknown, or instead of the graph for literal
strings, comments, configuration, documentation, generated files, or languages
outside parser coverage. Use `read` when source outside the returned ranges is
actually required.

Runtime observes tool capabilities for telemetry but never guesses intent from
keywords or tool-call counts and never rewrites the model's next request.

LSP is a fallback for a graph coverage/resolution gap or language-aware editor
operation. Tests, logs, debugger output, and runtime inspection are the source
of truth for reflection, dynamic imports, dependency injection, framework
registries, monkey-patching, generated code, and other runtime-only behavior.

## Ambiguity and cross-repository scope

All authorized repositories participate by default. The model does not choose
a repository before resolution. When exact duplicates exist, traversal stops;
the result lists definitions and asks for a qualified symbol, path, or
repository. Combining relationships from multiple same-named roots is
forbidden because the result would look precise while answering no single
question.

Resolved cross-repository edges join the same directional traversal. Pending
edges are reported as a limitation and must prevent claims of completeness.

## Evidence and token discipline

The tool returns the complete root definition within a fixed source budget and
small windows around each relationship site. Agents reuse that evidence rather
than immediately calling `read` or `grep` on the same locations. A follow-up
graph call targets a returned neighbor only when the investigation moves to
that symbol.

Before reporting, agents inspect freshness, dirty files, pending edges,
truncation, and limitations. A clean empty relationship list means no resolved
static edge was indexed; it is not proof that runtime invocation is impossible.

## Regression checklist

Any change to coding navigation must verify:

- No coding agent receives graph policy through mode-level system-prompt
  injection or request-text routing. Graph guidance enters context only with a
  relevant activated Coding workflow. `coding-investigation` owns exact-symbol
  questions and discovery of unknown roots. Unselected agents receive only the
  native tool schema and bounded skill metadata.
- `symbol` rejects whitespace/prose at both tool-schema and service boundaries.
- Prefix suggestions never become traversal roots.
- Multiple exact roots return zero relationships until disambiguated.
- Callers and callees preserve direction and exact call-site file/line.
- Cross-repository traversal follows resolved edges in the same direction.
- Output remains bounded and exposes freshness, limitations, and truncation.
- Prompt, skill, schema, renderer, API, telemetry, and README describe the same
  operation names and behavior.
