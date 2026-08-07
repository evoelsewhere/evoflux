# Code Graph, Cross-Repo, and Auto-Index Audit

| | |
|---|---|
| Date | 2026-07-31 |
| Scope | Coding-session bootstrap, query-time freshness, filesystem watcher, graph-first agent guidance, telemetry, incremental symbol resolution, path aliases, and cross-repository job chaining |
| Verdict | Parser coverage was already broad; the main accuracy risks were lifecycle races, stale resolution context, and incomplete graph-first policy coverage. Those confirmed gaps are fixed and covered by regressions. |

## Confirmed findings and remediation

| Severity | Finding | Impact | Remediation |
|---|---|---|---|
| P0 | A new save could cancel the task already performing an incremental reindex. | Partially written or rolled-back work could leave the graph stale until a later edit. | Release the debounce slot before indexing; later saves now become a serialized pending pass. |
| P0 | File events arriving during a first-open/API index job were logged and dropped. | Code written while the background build was running might never enter the graph. | Wait for the active job and automatically retry the incremental pass. |
| P1 | First-open auto-index built member repos independently but did not chain cross-repo resolution. | Local graph search worked while cross-repo links remained absent until manual resolve or a later edit. | Start one project resolve job that waits for every member index job. |
| P1 | A standalone graph reused after the repo joined a project contained no project-scoped unresolved candidates. | Cross-repo links from unchanged files were silently missing. | Compare per-file index timestamps with membership creation time and perform one project-aware full bootstrap when needed. |
| P1 | A resolve request received while another project resolve was running was deduplicated and lost. | A newly indexed reference could remain unresolved until another save. | Coalesce requests into one guaranteed follow-up pass before the job becomes done. |
| P1 | Incremental indexing omitted stored symbols' qualified names. | A changed caller could not select the correct unchanged target when siblings shared the same leaf name. | Carry `qualified_name` through `ExistingDef` and seed the qualified lookup map. |
| P1 | `tsconfig.json` was cached for the life of the backend process. | Edited TS path aliases continued resolving with the old config until restart. | Read the config once per index invocation instead of process-global caching. |
| P1 | Watcher filtering covered source extensions only. | Manifest, path-dependency, `.gitignore`, and TS alias edits did not refresh graph relationships. | Recognize graph metadata, perform a full relationship rebuild, and re-run cross-repo resolution. |
| P1 | Previously resolved cross-repo links survived package/layout metadata changes without reevaluation. | A link could remain confidently attached after its evidence changed. | Invalidate active resolver-produced links involving that workspace; preserve rejected/manual decisions. |
| P1 | The watcher was paused for an entire agent run, including graph queries made after edits in that run. | The same agent could write a symbol and immediately receive a stale graph result. | All four graph tools now cross a synchronous incremental freshness barrier before their first DB query; the barrier bypasses pause, folds pending debounce work, and waits for active index jobs/passes. |
| P1 | Earlier revisions attached graph-navigation preload through Coding-mode policy. | The mode-specific default coupled duplicated skill prose to loader behavior and prompt policy. | Historical remediation: the preload path was removed and execution moved behind the single native `code_graph` contract. Superseded on 2026-08-07: `code-graph-navigation` is again available as progressively disclosed Coding-only workflow guidance, while no mode-level graph injection remains. |
| P2 | There was no product metric for graph-first adoption or the efficiency of graph results. | Regressions in navigation behavior or result cost could not be detected from production telemetry. | Record first navigation strategy, per-tool count/latency, result tokens, and explicitly labeled estimates of avoided full-file reads and tokens. |

## Accuracy policy

The graph remains conservative:

- exact file/module scope and qualified names win over global leaf-name matching;
- ambiguous matches stay ambiguous instead of selecting an arbitrary node;
- receiver-type inference is not guessed when the parser has no static evidence;
- metadata changes rebuild relationships because content hashes alone cannot detect changed resolution semantics;
- manual rejections survive automatic indexing and metadata invalidation.

## Validation

The following groups pass after remediation:

- parser/import/type/decorator/structural/manifest corpus;
- incremental graph, navigation, watcher, job registry, and cross-repo service tests;
- code-graph, project reindex, project cross-repo, filtering, path-dependency, usage-edge, and auto-index API tests;
- Ruff check and format verification for every changed Python file.

New regressions specifically cover qualified unchanged targets, live `tsconfig` edits, metadata-triggered full indexing, non-cancellable in-flight indexing, retry after background indexing, query-time flush while paused, freshness waiting on in-flight work, project-membership bootstrap, metadata invalidation, first-open cross-repo chaining, queued resolver follow-up passes, absence of mode-level graph prompt and skill-body preload, explicit opt-out, graph-first classification, latency recording, and saving estimates.

## Residual limits

These remain intentional rather than lifecycle defects:

1. Dynamic imports, runtime monkey-patching, reflection, generated code, and receiver dispatch without static type evidence are not guessed.
2. Metadata-triggered rebuilds are intentionally heavier than source-only incremental passes, but manifest/config edits are low-frequency and correctness-sensitive.
3. Cross-repo Tier B is lexical and deterministic; it will leave a row unresolved when evidence is tied or absent.
4. The watcher covers active coding workspaces and project repos, not every repository ever registered in the sidebar.
5. Token and file-read savings are counterfactual estimates, not provider billing data. The published baseline is one full-file read per unique source location returned and UTF-8 bytes divided by four for tokens.
