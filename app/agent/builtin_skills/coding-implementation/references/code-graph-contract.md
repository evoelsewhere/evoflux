# Indexed code navigation contract

Use `code_search` only while the implementation location or exact identifier is
unknown. It accepts behavior terms, literals, errors, and code fragments and
returns parser-aligned, repository-qualified source ranges. Treat those ranges
as discovery candidates, not call-graph proof.

Use `code_graph` only after an exact source identifier is visible in user input,
a search result, or source evidence. Never translate a natural-language request,
error sentence, route description, configuration question, or feature name into
the `symbol` field. Once a search result reveals a promotable declaration, make
the graph the next structural observation.

## Choose one operation

| Structural question | Operation | Initial depth |
| --- | --- | --- |
| Where is this exact symbol declared? | `definition` | 1 |
| Which call sites invoke it? | `callers` | 1 |
| Which symbols does it invoke? | `callees` | 1 |
| Where is it structurally used? | `references` | 1 |
| What can this change affect upstream? | `impact` | 1 |
| What immediately surrounds it? | `neighborhood` | 1 |

Increase depth only for a named transitive impact question. `callers` may
include callable references used through dispatchers or executors;
`references` includes other inbound structural uses. `impact` is static
dependency reachability, not a runtime execution trace.

## Choose freshness deliberately

| Policy | Use when | Cost and constraint |
| --- | --- | --- |
| `fast` | First `code_search` or graph call and normal interactive navigation | Uses the latest indexed snapshot without a blocking repository validation. It may return `partial` with dirty files. A workspace with no index still requires its initial build. |
| `balanced` | A `fast` result is `partial` and dirty files overlap the question, or current post-edit relationships are required | Flushes watcher changes and validates/reindexes before answering, so it may block. Retry once, then use the result. |
| `strict` | Final high-consequence completeness proof when watcher coverage is unavailable or untrusted | Performs an independent repository check and is the most expensive policy. Never use it for discovery or as the first call. |

If `fast` returns `fresh`, do not rerun the same query with a stronger policy.
For a small dirty-file gap, a targeted source read is cheaper than rebuilding
relationships. Never repeat an unchanged `balanced` or `strict` query.

## Interpret results before claiming coverage

- Treat multiple definitions as ambiguity. Disambiguate with qualified symbol,
  repository, or path before combining relationships.
- Preserve relationship direction, repository identity, and exact call-site
  anchors.
- Treat `freshness`, dirty files, pending cross-repository edges,
  `limitations`, and truncation as answer constraints.
- Treat an empty edge set as no resolved static relationship, not proof that no
  dynamic relationship exists.
- Reuse definition and call-site source returned by the graph. Do not
  immediately grep or reread the same ranges.

## Use the narrow fallback for the actual gap

- Unknown identifier, literal, route, flag, config, comment, or error text:
  use one `code_search` call, then a narrow `grep`/targeted read only if the
  indexed result exposes no promotable declaration.
- Alias, receiver type, override, or live diagnostic: LSP.
- Reflection, registry, dependency injection, generated code, or dynamic
  import: source plus tests, logs, debugger, or runtime evidence.
- Unsupported language, stale index, pending edges, or truncation: report the
  bound and verify only the unresolved source surface.

Do not repeat an unsuccessful graph call unchanged. Correct the exact symbol,
operation, disambiguator, or evidence source.
