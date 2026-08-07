---
name: code-graph-navigation
description: Navigate indexed structural relationships for an exact source identifier with EvoFlux's native code graph. Use when a known function, method, class, or qualified symbol needs its definition, callers, callees, references, change impact, immediate neighborhood, or cross-repository links. Do not use it to discover an unknown identifier from natural-language prose, search literals or configuration, or prove dynamic runtime behavior.
---

# Navigate exact code symbols

Use the native `code_graph` tool as a structural navigator, not as a search
engine. Keep identifier discovery separate from relationship traversal.

## Navigation workflow

1. Establish one exact identifier from source, a user-supplied code token, or a
   previous tool result. Normalize syntax only, such as removing trailing
   parentheses. Never translate the user's sentence into the `symbol` field.
2. If the identifier is unknown, first use narrow literal/source discovery or
   the `coding-investigation` workflow. Use the graph only after an identifier
   is visible in evidence.
3. Choose the smallest structural operation:
   - `definition` for the resolved declaration and indexed body.
   - `callers` for inbound invocation sites.
   - `callees` for outbound calls.
   - `references` for all inbound structural uses.
   - `impact` for transitive inbound dependency risk.
   - `neighborhood` for immediate inbound and outbound context.
4. Start at depth 1. Increase depth only for explicitly transitive impact or
   reachability questions; prefer following one returned neighbor over a broad
   recursive expansion.
5. If several exact definitions match, stop traversal and disambiguate with a
   qualified symbol, repository, or path. Treat prefix suggestions only as
   candidates for a new exact call.
6. Reuse the returned definition and call-site source. Do not immediately grep
   or read the same ranges again.
7. Inspect freshness, dirty files, pending cross-repository edges, limitations,
   and truncation before claiming completeness.

Read [references/navigation-contract.md](references/navigation-contract.md)
when choosing between adjacent operations, handling ambiguity or cross-repo
results, or selecting a fallback for a graph limitation.

## Evidence boundary

- Treat an empty relationship set as no resolved static edge, not proof that a
  runtime relationship cannot exist.
- Use literal search for strings, comments, routes, flags, configuration,
  generated names, and unsupported languages.
- Use LSP for receiver/type resolution or editor diagnostics when graph
  resolution is incomplete.
- Use tests, logs, debugger output, or runtime inspection for reflection,
  dependency injection, registries, generated wiring, dynamic imports, and
  environment-dependent behavior.
- Keep repository identity on every cross-repository definition and edge.

## Deliverable

Answer the structural question directly, cite exact definition and call-site
locations, and state any ambiguity, stale coverage, pending edge, dynamic gap,
or truncation that limits the conclusion.
