# Native code-graph contract

## Operation selection

| Question | Operation | Default depth |
| --- | --- | --- |
| Where is this symbol defined? | `definition` | 1 |
| Which call sites invoke it? | `callers` | 1 |
| Which symbols does it invoke? | `callees` | 1 |
| Where is it structurally used? | `references` | 1 |
| What may a change affect transitively? | `impact` | 1, then 2–3 only when needed |
| What directly surrounds it? | `neighborhood` | 1 |

`callers` returns inbound direct calls plus callable references that may be
invoked indirectly through dispatchers, executors, or handlers. `references`
also admits the other inbound structural kinds indexed for the symbol.
`impact` follows those inbound dependencies transitively and is not an
execution trace.

## Result interpretation

- `strategy` identifies the exact-symbol resolver/traversal path used.
- `freshness` and `dirty files` describe index reconciliation, not runtime
  deployment state.
- `matches` are exact definitions. Several matches require disambiguation
  before any combined relationship claim.
- `relationships` preserve source/target direction, repository labels, and an
  exact call-site location.
- `pending cross-repo edges` prevent claims of complete cross-repository
  coverage.
- `limitations` and `truncated` are part of the answer contract, not incidental
  logging.

## Ambiguity procedure

1. Compare qualified names, kinds, repository labels, paths, and signatures.
2. Use local imports, receiver types, or the user's named subsystem to select
   one root.
3. Retry with the exact qualified symbol plus `repository` or `path` only when
   duplicate identities remain.
4. Never merge relationships from plausible same-named roots.

Prefix suggestions are not resolved roots. Inspect the candidate location and
submit its exact identifier in a new graph call.

## Fallback matrix

| Gap | Narrow fallback |
| --- | --- |
| Identifier not known | `grep`/`glob` or `coding-investigation` to discover one |
| Literal, config key, route, comment, error text | Literal search and targeted read |
| Alias, receiver type, override, live diagnostic | LSP |
| Reflection, registry, DI, generated or dynamic wiring | Source plus tests/logs/runtime evidence |
| Unsupported or unindexed language | Normal source navigation |
| Stale, pending, or truncated graph output | Report the bound, narrow scope, then verify source |

Do not repeat the same graph call as a fallback. Change the exact root,
operation, disambiguator, or evidence source only when it answers a distinct
unresolved question.
