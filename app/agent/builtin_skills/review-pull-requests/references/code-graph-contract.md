# Native code-graph contract

Use the graph only after an exact source identifier is visible in user input or
source evidence. Never translate request prose, errors, routes, configuration,
or feature names into the `symbol` field.

Choose the smallest operation at depth 1: `definition`, `callers`, `callees`,
`references`, `impact`, or `neighborhood`. Increase depth only for a named
transitive-impact question. Disambiguate duplicate definitions with qualified
symbol, repository, or path before combining relationships.

Preserve relationship direction, repository identity, and call-site anchors.
Treat freshness, dirty files, pending cross-repository edges, limitations, and
truncation as coverage bounds. An empty edge set means no resolved static edge,
not that dynamic wiring is absent. Reuse graph-returned source rather than
immediately grepping or rereading the same range.

Use literal search for unknown identifiers, routes, flags, config, comments,
and error text; LSP for aliases/types/overrides; and tests, logs, debugger, or
runtime evidence for reflection, registries, dependency injection, generated
code, and dynamic imports. Do not repeat an unsuccessful graph call unchanged.
