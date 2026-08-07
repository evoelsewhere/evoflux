# Native code-graph contract

Use the graph only after an exact source identifier is visible in user input or
source evidence. Never translate a natural-language request, error sentence,
route description, configuration question, or feature name into the `symbol`
field.

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
  narrow `grep`/`glob` and targeted source reading.
- Alias, receiver type, override, or live diagnostic: LSP.
- Reflection, registry, dependency injection, generated code, or dynamic
  import: source plus tests, logs, debugger, or runtime evidence.
- Unsupported language, stale index, pending edges, or truncation: report the
  bound and verify only the unresolved source surface.

Do not repeat an unsuccessful graph call unchanged. Correct the exact symbol,
operation, disambiguator, or evidence source.
