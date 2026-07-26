---
name: code-graph-navigation
description: "Use when navigating symbols and structural relationships across repositories. Triggers include: code graph, impact analysis, cross-repo, callers, dependency path"
---

# Code Graph Navigation

Use the code graph to route investigation quickly, then verify important claims
against source and live language tooling. The graph is a static, indexed model;
it is strong evidence about definitions and resolved relationships, but it is
not proof of runtime behavior.

## When to Use

- Locating definitions, callers, callees, imports, inheritance, type references,
  decorators, dependency injection, or containment.
- Estimating change impact before editing a shared symbol.
- Tracing a dependency path within one repository or across a linked project.
- Understanding an unfamiliar codebase without opening many whole files.
- Investigating duplicate names or an ambiguous relationship reported by the graph.

## When NOT to Use

- Searching for string literals, error text, comments, config keys, or concepts;
  use `grep` for those.
- Proving dynamic dispatch, reflection, generated code, framework registration,
  or runtime data flow; use source reads, LSP, tests, or runtime evidence.
- Continuing to query an unindexed workspace. Fall back to `grep` and normal file
  navigation so work can proceed while indexing is unavailable.

## Workflow

### 1. Check Scope and Freshness

Call `code_overview` once when the repository or project is unfamiliar. Confirm
that expected languages and a plausible number of files are indexed. In a linked
project, note sibling repository labels and whether any repository has zero files.

If the graph says there is no index, do not stall. Use `grep`/`glob`/`read`, and
report that graph-based impact analysis remains unverified. If recently edited
source is missing, treat the index as stale and prefer live source/LSP evidence.

### 2. Locate Symbols Precisely

Use `code_search` for identifiers. Start with a qualified name when known; use a
simple name only to discover candidates. Use `grep` for non-identifiers.

When several symbols match, keep repository, file, kind, signature, and qualified
name together. Never choose a candidate from name similarity alone.

### 3. Expand Relationships

Call `code_graph(name=..., direction="both")` for the selected symbol. Interpret
the edge kind literally:

- `calls` and `called by`: statically resolved invocations.
- `imports` and `imported by`: module or symbol imports.
- `extends`, `implements`, and their inverse forms: type hierarchy.
- `uses` and `used by`: wired or required dependencies.
- `references`: signature/type references.
- `decorated by`: annotations, attributes, or decorators.
- `contains` and `contained by`: structural ownership.

Use `direction="in"` for impact analysis and `direction="out"` for dependency
analysis. A missing edge means "not resolved by the index", not "cannot happen".

### 4. Handle Ambiguity Explicitly

An `ambiguous <kind> '<name>'` line means the index deliberately refused to guess.
Compare candidate locations with imports, receiver types, namespace/package, and
the call site. Read the call site and the smallest relevant candidate definitions.
Do not report the relationship as resolved until source or LSP evidence selects it.

### 5. Trace Across Repositories

Repository scope is automatic for linked projects. Preserve repository labels in
notes and use `code_path` when the question is how one symbol reaches another.
If no path is found, inspect unresolved imports and manifest/package boundaries;
do not assume the repositories are independent.

### 6. Verify Before Editing

Read the exact source ranges identified by graph results. Use LSP for receiver
types, aliases, overrides, and dynamic language facts when available. Before a
shared API edit, inspect inbound relationships and run the repository's focused
tests after the change.

## Verification

Before concluding a graph-based investigation, verify all of the following:

- The workspace or relevant sibling repository was indexed.
- The chosen symbol was disambiguated by qualified name and location.
- Both inbound and outbound relationships were checked when impact matters.
- Ambiguous and missing edges were reported as uncertainty, not absence.
- Material claims were confirmed from source, LSP, tests, or runtime evidence.
- Cross-repository labels and paths were preserved in the final explanation.