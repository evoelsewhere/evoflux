# Indexed code-context contract

`code_context` is the single indexed-code tool. Search combines a local
code-aware vector with FTS5; no embedding package or service is required. It refreshes a regeneratable,
repository-local desired-state index by default and can query every repository
authorized by the current sandbox. It does not use the application database.

## Choose the action from the evidence you have

| Evidence or question | Action |
| --- | --- |
| Behavior, error, literal, prose, or unknown implementation | `search` |
| By-example code shape such as `def \NAME(\(ARGS*\)):` | `grep` |
| Exact declaration | `definition` |
| Inbound invocation | `callers` |
| Outbound invocation | `callees` |
| Structural use | `references` |
| Transitive inbound risk | `impact` |
| Immediate bidirectional boundary | `neighborhood` |

Use `search` once to reveal a declared identifier, then call the necessary
exact-symbol action through the same tool. Never put request prose, a path, or a
guessed identifier into an exact-symbol action. Start graph traversal at depth
1; increase it only for an explicitly transitive question.

Keep `refresh=true` for the first query and after edits. Set it to `false` only
for immediate follow-ups that intentionally reuse the returned index version.
Do not repeat an unchanged query.

## Interpret results conservatively

- Multiple definitions are ambiguity; disambiguate with repository, path, or a
  qualified name before traversal.
- Cross-repository edges are resolved dynamically over the current authorized
  repository set. They are not persisted guesses.
- For graph actions, `repository` disambiguates the root only; authorized sibling
  repositories remain available for cross-repository traversal.
- Preserve relation direction, repository identity, and call-site anchors.
- Empty relations mean no resolved static relationship, not proof of runtime
  absence.
- Reuse returned definition and call-site source instead of rereading it.
- Treat `limitations` and truncation as explicit coverage bounds.

Use LSP for receiver/override precision and live diagnostics. Use a targeted
read, test, log, or debugger for reflection, registries, dependency injection,
generated wiring, concurrency, environment behavior, or unsupported languages.
