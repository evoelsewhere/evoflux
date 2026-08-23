# Native symbol-graph rebuild

Date: 2026-08-06

## Final decision

EvoFlux's model-facing code graph has two deliberately separate layers: the
native `code_graph` **symbol navigation** primitive executes graph operations,
while the Coding-only `code-graph-navigation` skill provides progressively
disclosed workflow guidance. Neither layer is a natural-language retrieval
engine or an MCP adapter.

The final boundary is intentionally strict:

1. the agent supplies one raw identifier or qualified symbol;
2. EvoFlux resolves exact definitions across every authorized repository;
3. the requested direction selects `definition`, `callers`, `callees`,
   `references`, `impact`, or `neighborhood`;
4. local `CodeEdge` and resolved `CrossRepoEdge` rows enter the same bounded
   traversal;
5. the result returns the root definition plus exact call/reference-site lines.

Natural-language requests are rejected at both the tool schema and engine
boundary. When a symbol is not known yet, the agent must identify one with a
separate symbol/source search. FTS remains useful for the human Graph panel and
cross-repository link resolution, but it no longer ranks prose from a user's
request for model-facing graph navigation.

## Why CodeGraph was the baseline

[colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) is MIT
licensed and separates its native SDK/index from its MCP adapter. The useful
parts for EvoFlux were its persistent parser graph, exact symbol lookup,
bounded traversal, incremental watcher, and source-aware formatting. MCP is a
transport, not the graph implementation, so EvoFlux integrates the same class
of capability directly into its Coding tool registry.

Upstream source reviewed:

- `src/db/schema.sql` — nodes, edges, files, unresolved references, and FTS5;
- `src/db/queries.ts` — exact symbol lookup and indexed search;
- `src/graph/traversal.ts` — bounded edge/node traversal;
- `src/sync/watcher.ts` — incremental index synchronization;
- `src/context/formatter.ts` — source and output budgeting;
- `src/context/index.ts` — native SDK entry point used by the MCP adapter.

CodeGraph stores one database per repository. EvoFlux extends the graph identity
to `(workspace_id, node_id)` and admits only resolved cross-repository edges
whose endpoints are inside the session's authorized repository set.

## Corrected architecture

The first rebuild attempt incorrectly combined two concerns: it interpreted the
entire user request, generated weighted concepts, fused broad FTS results, and
then expanded selected roots through the graph. Although ranking improved, the
tool was still doing semantic retrieval rather than answering the graph's core
question: *where is this function called, what does it call, and what depends on
it?*

That concept/FTS/set-cover pipeline was removed. The current path is:

- `resolver.py`: exact `name`/`qualified_name` resolution, explicit ambiguity,
  optional repository/path disambiguation, and non-traversed prefix suggestions;
- `traversal.py`: directional callers/callees/references/impact traversal over
  local and resolved cross-repository edges;
- `context.py`: complete root definitions and compact three-line call-site
  windows;
- `engine.py`: watcher/index freshness, graph versioning, resolution, traversal,
  and limitations;
- `code_graph_navigation_service.py`: application/API facade;
- model tool `code_graph`: a native, always-visible symbol-first contract;
- skill `code-graph-navigation`: optional selection, ambiguity, evidence, and
  fallback guidance loaded only after semantic or explicit selection.

The skill never wraps or replaces tool execution. Its body is not injected by
Coding mode, and server code does not turn raw request prose into a graph
symbol or route it with hard-coded keywords.

The old `code_query` tool and service were removed. The Graph UI search box now
uses indexed symbol search and explicitly asks for symbol names rather than
behavioral prose.

## Graph correctness improvements retained

The rebuild keeps parser/index work that directly improves structural graph
quality:

- Python named callables passed through dispatch boundaries are indexed as
  references, allowing `callers` to report indirect invocation sites such as
  `asyncio.to_thread(fn, ...)` without pretending the syntax is a direct call;
- Python builtins are not emitted as local call edges;
- import resolution prefers the precise imported module and records unresolved
  external bindings so generic method names do not fall back to unrelated local
  symbols;
- qualified-member fallback is limited to distinctive identifiers, removing
  false edges such as `append`, `select`, and `str` across unrelated languages;
- the index content hash carries a format tag, so parser/resolver upgrades cause
  one automatic reconciliation and steady-state queries remain watcher-driven.

## Acceptance criteria

The final browser acceptance test must start a fresh EvoFlux Coding session and
ask about a known symbol. Success means:

- the agent calls `code_graph` rather than `code_query` or grep;
- arguments contain the raw symbol and an explicit structural operation;
- `code-graph-navigation` can be selected or explicitly activated without
  mode-level body injection or server-side keyword routing;
- callers/callees contain exact source and target symbols plus the call-site
  file and line;
- only one graph call is needed for the requested direction;
- the result remains inline rather than being offloaded to an artifact;
- no natural-language FTS strategy or generic cross-language false edge appears.

## Attribution

The architecture is informed by the MIT-licensed CodeGraph project; EvoFlux
does not embed its MCP server. Upstream project:
<https://github.com/colbymchenry/codegraph>.
